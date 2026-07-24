"""Callback signing, SSRF validation, HTTP delivery, and dispatcher."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import ipaddress
import socket
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol
from urllib.parse import urlsplit

import httpx
from pydantic import HttpUrl
from sqlalchemy.exc import IntegrityError

from ..persistence import CallbackRepository, Database, SystemSettingRepository
from ..persistence.models import TaskRecord
from ..observability import trace_span
from ..schema.callback import (
    CallbackEvent,
    CallbackTestEvent,
)
from ..schema.error import ErrorCode, ErrorDetail
from ..schema.management import SettingKey
from ..schema.trace import TraceContext
from ..settings import Settings


CallbackBody = CallbackEvent | CallbackTestEvent
AddressResolver = Callable[[str, int], Awaitable[set[str]]]


class UnsafeCallbackUrlError(ValueError):
    """A callback target resolves to a forbidden network address."""


@dataclass(frozen=True, slots=True)
class CallbackHttpResult:
    delivered: bool
    status_code: int | None
    duration_ms: int
    response_summary: str | None
    error: ErrorDetail | None


class CallbackTransport(Protocol):
    async def deliver(
        self,
        *,
        event: CallbackBody,
        target_url: HttpUrl,
        secret: str | None,
        now: datetime,
    ) -> CallbackHttpResult: ...


async def resolve_host(host: str, port: int) -> set[str]:
    loop = asyncio.get_running_loop()
    addresses = await loop.getaddrinfo(
        host,
        port,
        type=socket.SOCK_STREAM,
    )
    return {str(item[4][0]) for item in addresses}


async def validate_callback_url(
    url: HttpUrl,
    *,
    resolver: AddressResolver = resolve_host,
) -> None:
    parsed = urlsplit(str(url))
    if parsed.scheme not in {"http", "https"}:
        raise UnsafeCallbackUrlError("callback URL must use HTTP or HTTPS")
    if parsed.username is not None or parsed.password is not None:
        raise UnsafeCallbackUrlError("callback URL must not include credentials")
    host = parsed.hostname
    if host is None:
        raise UnsafeCallbackUrlError("callback URL must include a hostname")
    if host.casefold().rstrip(".") == "localhost":
        raise UnsafeCallbackUrlError("localhost callback targets are forbidden")
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    try:
        literal = ipaddress.ip_address(host)
        addresses = {str(literal)}
    except ValueError:
        try:
            addresses = await resolver(host, port)
        except OSError as exc:
            raise UnsafeCallbackUrlError(
                "callback hostname could not be resolved"
            ) from exc
    if not addresses:
        raise UnsafeCallbackUrlError("callback hostname has no addresses")
    for address in addresses:
        try:
            parsed_address = ipaddress.ip_address(address)
        except ValueError as exc:
            raise UnsafeCallbackUrlError(
                "callback hostname resolved to an invalid address"
            ) from exc
        if not parsed_address.is_global:
            raise UnsafeCallbackUrlError(
                f"callback target address is not public: {parsed_address}"
            )


def callback_signature(
    *,
    secret: str,
    timestamp: str,
    body: bytes,
) -> str:
    payload = timestamp.encode("ascii") + b"." + body
    digest = hmac.new(secret.encode("utf-8"), payload, hashlib.sha256).hexdigest()
    return f"v1={digest}"


class HttpCallbackTransport:
    def __init__(
        self,
        *,
        timeout_seconds: float,
        maximum_response_bytes: int,
        resolver: AddressResolver = resolve_host,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        if timeout_seconds <= 0 or maximum_response_bytes < 1:
            raise ValueError("callback transport limits must be positive")
        self.timeout_seconds = timeout_seconds
        self.maximum_response_bytes = maximum_response_bytes
        self.resolver = resolver
        self._owns_client = client is None
        self.client = client or httpx.AsyncClient(
            follow_redirects=False,
            timeout=httpx.Timeout(timeout_seconds),
        )

    async def aclose(self) -> None:
        if self._owns_client:
            await self.client.aclose()

    async def deliver(
        self,
        *,
        event: CallbackBody,
        target_url: HttpUrl,
        secret: str | None,
        now: datetime,
    ) -> CallbackHttpResult:
        started = time.monotonic()
        try:
            await validate_callback_url(target_url, resolver=self.resolver)
        except UnsafeCallbackUrlError as exc:
            return self._failure(
                started,
                code=ErrorCode.VALIDATION_ERROR,
                message=str(exc),
                retryable=False,
            )
        body = event.model_dump_json().encode("utf-8")
        timestamp = str(int(now.timestamp()))
        headers = {
            "Content-Type": "application/json",
            "User-Agent": "parser-serve-callback/1.0",
            "X-Parser-Event-ID": event.event_id,
            "X-Parser-Timestamp": timestamp,
        }
        if secret is not None:
            headers["X-Parser-Signature"] = callback_signature(
                secret=secret,
                timestamp=timestamp,
                body=body,
            )
        try:
            async with self.client.stream(
                "POST",
                str(target_url),
                headers=headers,
                content=body,
                timeout=self.timeout_seconds,
            ) as response:
                collected = bytearray()
                async for chunk in response.aiter_bytes():
                    remaining = self.maximum_response_bytes - len(collected)
                    if remaining <= 0:
                        break
                    collected.extend(chunk[:remaining])
                summary = bytes(collected).decode("utf-8", errors="replace") or None
                delivered = 200 <= response.status_code < 300
                return CallbackHttpResult(
                    delivered=delivered,
                    status_code=response.status_code,
                    duration_ms=max(int((time.monotonic() - started) * 1000), 0),
                    response_summary=summary,
                    error=(
                        None
                        if delivered
                        else ErrorDetail(
                            code=ErrorCode.DEPENDENCY_UNAVAILABLE,
                            message=(
                                f"Callback target returned HTTP {response.status_code}"
                            ),
                            retryable=True,
                        )
                    ),
                )
        except httpx.TimeoutException:
            return self._failure(
                started,
                code=ErrorCode.TIMEOUT,
                message="Callback request timed out",
                retryable=True,
            )
        except httpx.HTTPError:
            return self._failure(
                started,
                code=ErrorCode.DEPENDENCY_UNAVAILABLE,
                message="Callback request failed",
                retryable=True,
            )

    @staticmethod
    def _failure(
        started: float,
        *,
        code: ErrorCode,
        message: str,
        retryable: bool,
    ) -> CallbackHttpResult:
        return CallbackHttpResult(
            delivered=False,
            status_code=None,
            duration_ms=max(int((time.monotonic() - started) * 1000), 0),
            response_summary=message,
            error=ErrorDetail(
                code=code,
                message=message,
                retryable=retryable,
            ),
        )


class CallbackDispatcher:
    def __init__(
        self,
        *,
        database: Database,
        repository: CallbackRepository,
        transport: CallbackTransport,
        maximum_attempts: int,
        initial_retry_seconds: float,
        maximum_retry_seconds: float,
        claim_timeout_seconds: float,
        batch_size: int = 20,
        system_settings: SystemSettingRepository | None = None,
        deployment_settings: Settings | None = None,
    ) -> None:
        self.database = database
        self.repository = repository
        self.transport = transport
        self.maximum_attempts = maximum_attempts
        self.initial_retry_seconds = initial_retry_seconds
        self.maximum_retry_seconds = maximum_retry_seconds
        self.claim_timeout_seconds = claim_timeout_seconds
        self.batch_size = batch_size
        self.system_settings = system_settings
        self.deployment_settings = deployment_settings

    async def run_once(self, *, now: datetime | None = None) -> int:
        current = now or datetime.now(UTC)
        async with self.database.session_factory() as session:
            try:
                maximum_attempts = self.maximum_attempts
                if (
                    self.system_settings is not None
                    and self.deployment_settings is not None
                ):
                    maximum_attempts = await self.system_settings.get_int(
                        session,
                        key=SettingKey.CALLBACK_MAXIMUM_ATTEMPTS,
                        defaults=self.deployment_settings,
                    )
                await self.repository.materialize(
                    session,
                    now=current,
                    maximum_attempts=maximum_attempts,
                )
                await session.commit()
            except IntegrityError:
                await session.rollback()

        delivered_count = 0
        for _ in range(self.batch_size):
            async with self.database.session_factory() as session:
                record = await self.repository.claim_due(
                    session,
                    now=current,
                    claim_timeout_seconds=self.claim_timeout_seconds,
                )
                if record is None:
                    await session.commit()
                    break
                config = await self.repository.callback_config(
                    session,
                    record.task_id,
                )
                event = CallbackEvent.model_validate(record.event_payload)
                delivery_id = record.delivery_id
                sequence = record.attempt_sequence
                attempt_number = record.attempt
                target_url = HttpUrl(record.target_url)
                task = await session.get(TaskRecord, record.task_id)
                trace_context = (
                    TraceContext.model_validate(task.trace_context_payload)
                    if task is not None and task.trace_context_payload is not None
                    else None
                )
                await session.commit()
            with trace_span(
                "parser.callback.deliver",
                parent=trace_context,
                attributes={
                    "parser.task.id": event.task_id,
                    "parser.callback.delivery.id": delivery_id,
                    "parser.callback.attempt": attempt_number,
                },
            ):
                result = (
                    await self.transport.deliver(
                        event=event,
                        target_url=target_url,
                        secret=config.secret if config is not None else None,
                        now=current,
                    )
                    if config is not None
                    else CallbackHttpResult(
                        delivered=False,
                        status_code=None,
                        duration_ms=0,
                        response_summary="Callback configuration no longer exists",
                        error=ErrorDetail(
                            code=ErrorCode.NOT_FOUND,
                            message="Callback configuration no longer exists",
                        ),
                    )
                )
            result_error = (
                result.error
                if result.error is not None
                else (
                    None
                    if result.delivered
                    else ErrorDetail(
                        code=ErrorCode.DEPENDENCY_UNAVAILABLE,
                        message="Callback delivery failed",
                        retryable=False,
                    )
                )
            )
            async with self.database.session_factory() as session:
                await self.repository.record_result(
                    session,
                    delivery_id=delivery_id,
                    sequence=sequence,
                    attempt_number=attempt_number,
                    delivered=result.delivered,
                    retryable=(
                        result_error.retryable if result_error is not None else False
                    ),
                    response_status_code=result.status_code,
                    response_summary=result.response_summary,
                    duration_ms=result.duration_ms,
                    error=result_error,
                    now=current,
                    initial_retry_seconds=self.initial_retry_seconds,
                    maximum_retry_seconds=self.maximum_retry_seconds,
                )
                await session.commit()
            delivered_count += 1
        return delivered_count

    async def run(
        self,
        *,
        poll_interval_seconds: float,
        stop: asyncio.Event,
    ) -> None:
        while not stop.is_set():
            await self.run_once()
            try:
                await asyncio.wait_for(
                    stop.wait(),
                    timeout=poll_interval_seconds,
                )
            except TimeoutError:
                pass


__all__ = [
    "AddressResolver",
    "CallbackDispatcher",
    "CallbackHttpResult",
    "CallbackTransport",
    "HttpCallbackTransport",
    "UnsafeCallbackUrlError",
    "callback_signature",
    "resolve_host",
    "validate_callback_url",
]
