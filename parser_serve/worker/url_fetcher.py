"""Bounded URL source download with application-level SSRF protection."""

from __future__ import annotations

import asyncio
import ipaddress
import socket
from collections.abc import Awaitable, Callable
from pathlib import Path
from urllib.parse import urljoin, urlsplit

import httpx
from pydantic import HttpUrl

from ..backends import BackendExecutionError
from ..security import ContentValidationError, inspect_content


AddressResolver = Callable[[str, int], Awaitable[set[str]]]
_REDIRECTS = {301, 302, 303, 307, 308}
_ALLOWED_CONTENT_TYPES = {
    "application/xhtml+xml",
    "text/html",
    "text/plain",
}


async def resolve_host(host: str, port: int) -> set[str]:
    loop = asyncio.get_running_loop()
    values = await loop.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    return {str(value[4][0]) for value in values}


async def validate_source_url(
    url: HttpUrl,
    *,
    resolver: AddressResolver = resolve_host,
) -> None:
    parsed = urlsplit(str(url))
    if parsed.scheme not in {"http", "https"}:
        raise BackendExecutionError("URL Source must use HTTP or HTTPS")
    if parsed.username is not None or parsed.password is not None:
        raise BackendExecutionError("URL Source must not contain credentials")
    host = parsed.hostname
    if host is None or host.casefold().rstrip(".") == "localhost":
        raise BackendExecutionError("URL Source hostname is forbidden")
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    try:
        addresses = {str(ipaddress.ip_address(host))}
    except ValueError:
        try:
            addresses = await resolver(host, port)
        except OSError as exc:
            raise BackendExecutionError(
                "URL Source hostname could not be resolved",
                retryable=True,
            ) from exc
    if not addresses:
        raise BackendExecutionError("URL Source hostname has no addresses")
    for address in addresses:
        try:
            parsed_address = ipaddress.ip_address(address)
        except ValueError as exc:
            raise BackendExecutionError(
                "URL Source resolved to an invalid address"
            ) from exc
        if not parsed_address.is_global:
            raise BackendExecutionError(
                f"URL Source resolved to a non-public address: {parsed_address}"
            )


async def fetch_url_source(
    url: HttpUrl,
    destination: Path,
    *,
    maximum_bytes: int,
    timeout_seconds: float,
    maximum_redirects: int,
    resolver: AddressResolver = resolve_host,
    client: httpx.AsyncClient | None = None,
) -> Path:
    if maximum_bytes < 1 or timeout_seconds <= 0 or maximum_redirects < 0:
        raise ValueError("URL fetch limits are invalid")
    owned_client = client is None
    resolved_client = client or httpx.AsyncClient(
        follow_redirects=False,
        timeout=httpx.Timeout(timeout_seconds),
    )
    current = url
    try:
        for redirect_count in range(maximum_redirects + 1):
            await validate_source_url(current, resolver=resolver)
            async with resolved_client.stream("GET", str(current)) as response:
                if response.status_code in _REDIRECTS:
                    location = response.headers.get("location")
                    if location is None:
                        raise BackendExecutionError(
                            "URL Source redirect has no Location"
                        )
                    if redirect_count >= maximum_redirects:
                        raise BackendExecutionError(
                            "URL Source exceeded the redirect limit"
                        )
                    redirected = HttpUrl(urljoin(str(current), location))
                    if current.scheme == "https" and redirected.scheme == "http":
                        raise BackendExecutionError(
                            "URL Source cannot redirect from HTTPS to HTTP"
                        )
                    current = redirected
                    continue
                if not 200 <= response.status_code < 300:
                    raise BackendExecutionError(
                        f"URL Source returned HTTP {response.status_code}",
                        retryable=response.status_code >= 500,
                    )
                content_type = (
                    response.headers.get("content-type", "")
                    .split(";", 1)[0]
                    .strip()
                    .casefold()
                )
                if content_type not in _ALLOWED_CONTENT_TYPES:
                    raise BackendExecutionError(
                        f"URL Source content type is not supported: {content_type or 'missing'}"
                    )
                length = response.headers.get("content-length")
                if length is not None:
                    try:
                        declared = int(length)
                    except ValueError as exc:
                        raise BackendExecutionError(
                            "URL Source Content-Length is invalid"
                        ) from exc
                    if declared > maximum_bytes:
                        raise BackendExecutionError(
                            "URL Source exceeds the download size limit"
                        )
                destination.parent.mkdir(parents=True, exist_ok=True)
                size = 0
                handle = await asyncio.to_thread(destination.open, "wb")
                try:
                    async for chunk in response.aiter_bytes():
                        size += len(chunk)
                        if size > maximum_bytes:
                            raise BackendExecutionError(
                                "URL Source exceeds the download size limit"
                            )
                        await asyncio.to_thread(handle.write, chunk)
                except BaseException:
                    await asyncio.to_thread(handle.close)
                    await asyncio.to_thread(destination.unlink, missing_ok=True)
                    raise
                await asyncio.to_thread(handle.close)
                sample = await asyncio.to_thread(_read_sample, destination)
                try:
                    inspect_content(
                        filename=destination.name,
                        declared_mime_type=content_type,
                        sample=sample,
                    )
                except ContentValidationError as exc:
                    await asyncio.to_thread(destination.unlink, missing_ok=True)
                    raise BackendExecutionError(str(exc)) from exc
                return destination
        raise AssertionError("redirect loop invariant was violated")
    except httpx.TimeoutException as exc:
        raise BackendExecutionError(
            "URL Source download timed out", retryable=True
        ) from exc
    except httpx.HTTPError as exc:
        raise BackendExecutionError(
            "URL Source download failed",
            retryable=True,
        ) from exc
    finally:
        if owned_client:
            await resolved_client.aclose()


def _read_sample(path: Path) -> bytes:
    with path.open("rb") as source:
        return source.read(64 * 1024)


__all__ = [
    "AddressResolver",
    "fetch_url_source",
    "resolve_host",
    "validate_source_url",
]
