"""Generic, versioned HTTP adapter for remote parser services."""

from __future__ import annotations

import asyncio
import hashlib
import mimetypes
from importlib import import_module
from pathlib import Path
from typing import Any

from pydantic import TypeAdapter, ValidationError

from ..schema.artifact import ArtifactType
from ..schema.backend import BackendCapability
from ..schema.hardware import DeviceRuntime
from ..schema.remote import (
    RemoteBackendConfig,
    RemoteParseFailed,
    RemoteParseRequest,
    RemoteParseResponse,
    RemoteSourceFile,
)
from ..schema.result import ImageBlock, KeyframeBlock, ParseResult
from .base import (
    BackendContext,
    BackendExecutionError,
    BackendOutput,
    ProducedArtifact,
)


_response_adapter = TypeAdapter(RemoteParseResponse)
_RETRYABLE_STATUS_CODES = {408, 425, 429, 500, 502, 503, 504}


def _file_digest(path: Path) -> tuple[int, str]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            size += len(chunk)
            digest.update(chunk)
    return size, digest.hexdigest()


class RemoteHttpBackend:
    """Execute one configured parser capability through the remote protocol."""

    def __init__(
        self,
        *,
        config: RemoteBackendConfig,
        runtime: DeviceRuntime,
        transport: Any = None,
    ) -> None:
        self.config = config
        self.transport = transport
        self.capability = BackendCapability(
            name=config.name,
            version=config.version,
            media_categories=config.media_categories,
            mime_types=config.mime_types,
            runtimes=[runtime],
            maximum_concurrency=config.maximum_concurrency,
        )

    async def execute(self, context: BackendContext) -> BackendOutput:
        request = await self._request(context)
        await context.report_progress(5.0)
        response = await self._send(context, request)
        if isinstance(response, RemoteParseFailed):
            raise BackendExecutionError(
                response.error.message,
                retryable=response.error.retryable,
            )
        self._validate_result(context, response.result)

        total_artifact_bytes = 0
        if len(response.artifacts) > self.config.maximum_artifacts:
            raise BackendExecutionError("remote Backend returned too many artifacts")
        attachments: list[ProducedArtifact] = []
        for artifact in response.artifacts:
            content = bytes(artifact.content_base64)
            if len(content) > self.config.maximum_artifact_bytes:
                raise BackendExecutionError(
                    "remote Backend artifact exceeds the configured size limit"
                )
            total_artifact_bytes += len(content)
            if total_artifact_bytes > self.config.maximum_response_bytes:
                raise BackendExecutionError(
                    "remote Backend artifacts exceed the configured total size limit"
                )
            attachments.append(
                ProducedArtifact(
                    type=artifact.type,
                    filename=artifact.filename,
                    mime_type=artifact.mime_type,
                    data=content,
                    metadata=artifact.metadata,
                )
            )

        await context.report_progress(90.0)
        result = ProducedArtifact(
            type=ArtifactType.RESULT_JSON,
            filename="result.json",
            mime_type="application/json",
            data=response.result.model_dump_json(indent=2).encode("utf-8"),
            metadata={
                "remote_backend": self.config.name,
                "remote_backend_version": self.config.version,
                "protocol_version": request.protocol_version,
            },
        )
        return BackendOutput(
            artifacts=(result, *attachments),
            primary_artifact_index=0,
        )

    async def _request(self, context: BackendContext) -> RemoteParseRequest:
        source_file = None
        if context.source_path is not None:
            size, digest = await asyncio.to_thread(
                _file_digest,
                context.source_path,
            )
            source_file = RemoteSourceFile(
                filename=context.source_path.name,
                mime_type=(
                    mimetypes.guess_type(context.source_path.name)[0]
                    or context.lease.source_metadata.mime_type
                ),
                size_bytes=size,
                sha256=digest,
            )
        return RemoteParseRequest(
            task_id=context.lease.task_id,
            stage_id=context.lease.stage_id,
            backend_name=self.config.name,
            backend_version=self.config.version,
            runtime=context.lease.runtime,
            device_id=context.lease.device_id,
            trace_context=context.lease.trace_context,
            source=context.lease.source_metadata,
            source_text=context.source_text,
            source_file=source_file,
            parameters=context.lease.parameters,
            timeout_seconds=context.lease.timeout_seconds,
        )

    async def _send(
        self,
        context: BackendContext,
        request: RemoteParseRequest,
    ) -> RemoteParseResponse:
        try:
            httpx: Any = import_module("httpx")
        except ImportError as exc:  # pragma: no cover - Worker profiles install it
            raise BackendExecutionError(
                "httpx is not installed in this Worker"
            ) from exc

        headers = {
            "Accept": "application/json",
            "User-Agent": "parser-serve-remote-backend/1.0",
        }
        authentication = self.config.authentication
        if authentication.token is not None:
            token = authentication.token.get_secret_value()
            if authentication.type == "bearer":
                headers["Authorization"] = f"Bearer {token}"
            elif authentication.type == "x_api_key":
                headers["X-API-Key"] = token

        timeout = min(
            self.config.timeout_seconds,
            float(context.lease.timeout_seconds),
        )
        client_arguments: dict[str, Any] = {
            "follow_redirects": False,
            "timeout": timeout,
        }
        if self.transport is not None:
            client_arguments["transport"] = self.transport

        try:
            async with httpx.AsyncClient(**client_arguments) as client:
                fields: dict[str, Any] = {
                    "request": (
                        None,
                        request.model_dump_json(),
                        "application/json",
                    )
                }
                if context.source_path is not None:
                    with context.source_path.open("rb") as source:
                        fields["file"] = (
                            context.source_path.name,
                            source,
                            context.lease.source_metadata.mime_type,
                        )
                        response = await self._read_response(
                            client,
                            headers=headers,
                            fields=fields,
                        )
                else:
                    response = await self._read_response(
                        client,
                        headers=headers,
                        fields=fields,
                    )
        except httpx.TimeoutException as exc:
            raise BackendExecutionError(
                "remote Backend request timed out",
                retryable=True,
            ) from exc
        except httpx.RequestError as exc:
            raise BackendExecutionError(
                "remote Backend request failed",
                retryable=True,
            ) from exc

        status_code, content_type, body = response
        if content_type not in {"application/json", "application/problem+json"}:
            raise BackendExecutionError(
                "remote Backend returned a non-JSON response",
                retryable=status_code in _RETRYABLE_STATUS_CODES,
            )
        try:
            parsed = _response_adapter.validate_json(body)
        except ValidationError as exc:
            raise BackendExecutionError(
                "remote Backend response does not match protocol version 1.0",
                retryable=status_code in _RETRYABLE_STATUS_CODES,
            ) from exc

        if not 200 <= status_code < 300:
            message = (
                parsed.error.message
                if isinstance(parsed, RemoteParseFailed)
                else f"remote Backend returned HTTP {status_code}"
            )
            retryable = status_code in _RETRYABLE_STATUS_CODES or (
                isinstance(parsed, RemoteParseFailed) and parsed.error.retryable
            )
            raise BackendExecutionError(message, retryable=retryable)
        return parsed

    async def _read_response(
        self,
        client: Any,
        *,
        headers: dict[str, str],
        fields: dict[str, Any],
    ) -> tuple[int, str, bytes]:
        async with client.stream(
            "POST",
            str(self.config.endpoint),
            headers=headers,
            files=fields,
        ) as response:
            raw_length = response.headers.get("Content-Length")
            if raw_length is not None:
                try:
                    declared_length = int(raw_length)
                except ValueError as exc:
                    raise BackendExecutionError(
                        "remote Backend returned an invalid Content-Length"
                    ) from exc
                if declared_length > self.config.maximum_response_bytes:
                    raise BackendExecutionError(
                        "remote Backend response exceeds the configured size limit"
                    )
            body = bytearray()
            async for chunk in response.aiter_bytes():
                body.extend(chunk)
                if len(body) > self.config.maximum_response_bytes:
                    raise BackendExecutionError(
                        "remote Backend response exceeds the configured size limit"
                    )
            content_type = (
                response.headers.get("Content-Type", "")
                .split(";", maxsplit=1)[0]
                .strip()
                .lower()
            )
            return response.status_code, content_type, bytes(body)

    @staticmethod
    def _validate_result(context: BackendContext, result: ParseResult) -> None:
        if result.task_id != context.lease.task_id:
            raise BackendExecutionError(
                "remote Backend result belongs to a different task"
            )
        if result.source != context.lease.source_metadata:
            raise BackendExecutionError(
                "remote Backend changed the immutable source metadata"
            )
        if result.artifacts:
            raise BackendExecutionError(
                "remote Backend result must not contain server-owned Artifact records"
            )
        if any(
            isinstance(block, (ImageBlock, KeyframeBlock)) for block in result.blocks
        ):
            raise BackendExecutionError(
                "remote Backend result cannot reference unassigned Artifact IDs"
            )


__all__ = ["RemoteHttpBackend"]
