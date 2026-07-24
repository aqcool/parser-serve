"""Optional Ray Serve ingress for the Remote Backend 1.0 protocol."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
from collections.abc import Callable
from importlib import import_module
from typing import Annotated, Any, Protocol

from pydantic import Field, SecretStr, TypeAdapter, ValidationError

from ..schema.base import StrictSchema
from ..schema.error import ErrorCode, ErrorDetail
from ..schema.remote import (
    RemoteParseFailed,
    RemoteParseRequest,
    RemoteParseResponse,
    RemoteParseSucceeded,
)


_RESPONSE_ADAPTER = TypeAdapter(RemoteParseResponse)


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
                form = await request.form()
                request_json = form.get("request")
                if not isinstance(request_json, str):
                    raise ValueError
                upload = form.get("file")
                file_content = (
                    await _read_upload(upload, maximum_file_bytes)
                    if upload is not None
                    else None
                )
                response = await self.gateway.parse(request_json, file_content)
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
