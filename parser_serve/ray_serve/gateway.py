"""Optional Ray Serve ingress for the Remote Backend 1.0 protocol."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import tempfile
from collections.abc import Callable, Mapping
from importlib import import_module
from typing import Annotated, Any, BinaryIO, Protocol, cast

from pydantic import Field, SecretStr, TypeAdapter, ValidationError

from ..observability import trace_span
from ..schema.base import StrictSchema
from ..schema.error import ErrorCode, ErrorDetail
from ..schema.remote import (
    RemoteParseFailed,
    RemoteParseRequest,
    RemoteParseResponse,
    RemoteParseSucceeded,
)
from ..schema.trace import TraceContext


_RESPONSE_ADAPTER = TypeAdapter(RemoteParseResponse)
_MAXIMUM_MULTIPART_METADATA_BYTES = 1024 * 1024
_MULTIPART_FRAMING_ALLOWANCE_BYTES = 64 * 1024


class RayInferenceHandler(Protocol):
    """Model adapter hosted inside each Ray Serve replica."""

    async def parse(
        self,
        request: RemoteParseRequest,
        file_content: bytes | None,
    ) -> RemoteParseResponse: ...


class RayServeDeploymentConfig(StrictSchema):
    """Typed resource, concurrency, authentication, and input limits."""

    num_replicas: Annotated[int, Field(ge=1, le=10_000, strict=True)] = 1
    max_ongoing_requests: Annotated[int, Field(ge=1, le=100_000, strict=True)] = 1
    max_queued_requests: Annotated[int, Field(ge=0, le=1_000_000, strict=True)] = 100
    num_cpus: Annotated[float, Field(ge=0.0, le=1024.0, strict=True)] = 1.0
    num_gpus: Annotated[float, Field(ge=0.0, le=1024.0, strict=True)] = 0.0
    maximum_file_bytes: Annotated[
        int,
        Field(ge=1, le=1024 * 1024 * 1024 * 1024, strict=True),
    ] = 1024 * 1024 * 1024
    bearer_token: SecretStr | None = None


class RemoteProtocolGateway:
    """Validate protocol and file integrity before invoking model code."""

    def __init__(
        self,
        handler: RayInferenceHandler,
        *,
        maximum_file_bytes: int,
    ) -> None:
        if maximum_file_bytes < 1:
            raise ValueError("maximum_file_bytes must be greater than zero")
        self.handler = handler
        self.maximum_file_bytes = maximum_file_bytes

    async def parse(
        self,
        request_json: str | bytes,
        file_content: bytes | None,
        *,
        parent_trace_context: TraceContext | None = None,
    ) -> RemoteParseResponse:
        try:
            request = RemoteParseRequest.model_validate_json(request_json)
        except ValidationError:
            return self._failure(
                ErrorCode.VALIDATION_ERROR,
                "request does not match Remote Backend protocol 1.0",
            )
        integrity_error = self._validate_file(request, file_content)
        if integrity_error is not None:
            return integrity_error
        try:
            with trace_span(
                "parser.remote.execute",
                parent=parent_trace_context or request.trace_context,
                attributes={
                    "parser.task.id": request.task_id,
                    "parser.stage.id": request.stage_id,
                    "parser.backend.name": request.backend_name,
                    "parser.runtime": request.runtime.value,
                    **(
                        {"parser.device.id": request.device_id}
                        if request.device_id is not None
                        else {}
                    ),
                },
            ):
                response = await asyncio.wait_for(
                    self.handler.parse(request, file_content),
                    timeout=float(request.timeout_seconds),
                )
            parsed = _RESPONSE_ADAPTER.validate_python(response)
        except TimeoutError:
            return self._failure(
                ErrorCode.TIMEOUT,
                "model execution timed out",
                retryable=True,
            )
        except (ValidationError, ValueError):
            return self._failure(
                ErrorCode.INTERNAL_ERROR,
                "model returned an invalid protocol response",
            )
        except Exception:
            return self._failure(
                ErrorCode.INTERNAL_ERROR,
                "model execution failed",
            )
        if isinstance(parsed, RemoteParseSucceeded):
            if parsed.result.task_id != request.task_id:
                return self._failure(
                    ErrorCode.INTERNAL_ERROR,
                    "model result belongs to a different task",
                )
            if parsed.result.source != request.source:
                return self._failure(
                    ErrorCode.INTERNAL_ERROR,
                    "model changed immutable source metadata",
                )
        return parsed

    def _validate_file(
        self,
        request: RemoteParseRequest,
        file_content: bytes | None,
    ) -> RemoteParseFailed | None:
        metadata = request.source_file
        if metadata is None:
            if file_content is not None:
                return self._failure(
                    ErrorCode.VALIDATION_ERROR,
                    "text requests cannot include a file",
                )
            return None
        if file_content is None:
            return self._failure(
                ErrorCode.VALIDATION_ERROR,
                "file request is missing multipart content",
            )
        if len(file_content) > self.maximum_file_bytes:
            return self._failure(
                ErrorCode.FILE_TOO_LARGE,
                "source file exceeds the Ray Serve gateway limit",
            )
        if len(file_content) != metadata.size_bytes:
            return self._failure(
                ErrorCode.VALIDATION_ERROR,
                "source file size does not match its metadata",
            )
        digest = hashlib.sha256(file_content).hexdigest()
        if not hmac.compare_digest(digest, metadata.sha256):
            return self._failure(
                ErrorCode.VALIDATION_ERROR,
                "source file digest does not match its metadata",
            )
        return None

    @staticmethod
    def _failure(
        code: ErrorCode,
        message: str,
        *,
        retryable: bool = False,
    ) -> RemoteParseFailed:
        return RemoteParseFailed(
            status="failed",
            error=ErrorDetail(
                code=code,
                message=message,
                retryable=retryable,
            ),
        )


def build_ray_serve_application(
    handler_factory: Callable[[], RayInferenceHandler],
    *,
    config: RayServeDeploymentConfig | None = None,
) -> Any:
    """Build a Ray Serve application exposing Remote Backend 1.0 at its root."""

    deployment_config = config or RayServeDeploymentConfig()
    try:
        serve = import_module("ray.serve")
        requests = import_module("starlette.requests")
        responses = import_module("starlette.responses")
    except ImportError as exc:
        raise RuntimeError(
            "Ray Serve is not installed; install the ray-serve dependency profile"
        ) from exc

    expected_token = (
        deployment_config.bearer_token.get_secret_value()
        if deployment_config.bearer_token is not None
        else None
    )
    maximum_file_bytes = deployment_config.maximum_file_bytes

    class RemoteBackendIngress:
        def __init__(self) -> None:
            self.gateway = RemoteProtocolGateway(
                handler_factory(),
                maximum_file_bytes=maximum_file_bytes,
            )

        async def __call__(self, request: Any) -> Any:
            if expected_token is not None:
                authorization = request.headers.get("authorization", "")
                supplied = (
                    authorization.removeprefix("Bearer ")
                    if authorization.startswith("Bearer ")
                    else ""
                )
                if not hmac.compare_digest(supplied, expected_token):
                    response = RemoteProtocolGateway._failure(
                        ErrorCode.AUTHENTICATION_FAILED,
                        "authentication failed",
                    )
                    return responses.JSONResponse(
                        response.model_dump(mode="json"),
                        status_code=401,
                    )
            try:
                maximum_request_bytes = (
                    maximum_file_bytes
                    + _MAXIMUM_MULTIPART_METADATA_BYTES
                    + _MULTIPART_FRAMING_ALLOWANCE_BYTES
                )
                body = await _read_request_body(request, maximum_request_bytes)
                try:
                    bounded_request = _request_from_body(
                        requests.Request,
                        request,
                        body,
                    )
                    form = await bounded_request.form(
                        max_files=1,
                        max_fields=1,
                        max_part_size=_MAXIMUM_MULTIPART_METADATA_BYTES,
                    )
                    try:
                        request_json = form.get("request")
                        if not isinstance(request_json, str):
                            raise ValueError
                        upload = form.get("file")
                        file_content = (
                            await _read_upload(upload, maximum_file_bytes)
                            if upload is not None
                            else None
                        )
                        response = await self.gateway.parse(
                            request_json,
                            file_content,
                            parent_trace_context=_trace_context_from_headers(
                                request.headers
                            ),
                        )
                    finally:
                        await form.close()
                finally:
                    body.close()
            except FileTooLargeError:
                response = RemoteProtocolGateway._failure(
                    ErrorCode.FILE_TOO_LARGE,
                    "source file exceeds the Ray Serve gateway limit",
                )
            except Exception:
                response = RemoteProtocolGateway._failure(
                    ErrorCode.VALIDATION_ERROR,
                    "multipart request is invalid",
                )
            status_code = (
                503
                if isinstance(response, RemoteParseFailed) and response.error.retryable
                else 200
            )
            return responses.JSONResponse(
                response.model_dump(mode="json"),
                status_code=status_code,
            )

    deployment = serve.deployment(
        num_replicas=deployment_config.num_replicas,
        max_ongoing_requests=deployment_config.max_ongoing_requests,
        max_queued_requests=deployment_config.max_queued_requests,
        ray_actor_options={
            "num_cpus": deployment_config.num_cpus,
            "num_gpus": deployment_config.num_gpus,
        },
    )(RemoteBackendIngress)
    return deployment.bind()


class FileTooLargeError(ValueError):
    pass


async def _read_request_body(request: Any, maximum_bytes: int) -> BinaryIO:
    raw_length = request.headers.get("content-length")
    if raw_length is not None:
        try:
            declared_length = int(raw_length)
        except ValueError as exc:
            raise ValueError("invalid Content-Length") from exc
        if declared_length < 0:
            raise ValueError("invalid Content-Length")
        if declared_length > maximum_bytes:
            raise FileTooLargeError
    content = tempfile.SpooledTemporaryFile(
        max_size=_MAXIMUM_MULTIPART_METADATA_BYTES,
        mode="w+b",
    )
    size = 0
    try:
        async for chunk in request.stream():
            size += len(chunk)
            if size > maximum_bytes:
                raise FileTooLargeError
            content.write(chunk)
        content.seek(0)
        return cast(BinaryIO, content)
    except BaseException:
        content.close()
        raise


def _request_from_body(request_type: Any, original: Any, body: BinaryIO) -> Any:
    async def receive() -> dict[str, object]:
        chunk = body.read(1024 * 1024)
        return {
            "type": "http.request",
            "body": chunk,
            "more_body": bool(chunk),
        }

    return request_type(original.scope, receive)


def _trace_context_from_headers(headers: Mapping[str, str]) -> TraceContext | None:
    traceparent = headers.get("traceparent")
    if traceparent is None:
        return None
    try:
        return TraceContext(
            traceparent=traceparent,
            tracestate=headers.get("tracestate"),
        )
    except ValidationError:
        return None


async def _read_upload(upload: Any, maximum_bytes: int) -> bytes:
    content = bytearray()
    try:
        while chunk := await upload.read(min(1024 * 1024, maximum_bytes + 1)):
            content.extend(chunk)
            if len(content) > maximum_bytes:
                raise FileTooLargeError
    finally:
        close = getattr(upload, "close", None)
        if close is not None:
            await close()
    return bytes(content)


__all__ = [
    "RayInferenceHandler",
    "RayServeDeploymentConfig",
    "RemoteProtocolGateway",
    "build_ray_serve_application",
]
