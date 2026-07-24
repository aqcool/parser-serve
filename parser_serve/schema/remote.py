"""Versioned protocol and configuration for remote parser Backends."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import (
    AnyHttpUrl,
    Base64Bytes,
    Field,
    SecretStr,
    model_validator,
)

from .artifact import ArtifactType
from .base import JsonValue, StrictSchema
from .common import (
    MediaCategory,
    MimePattern,
    MimeType,
    NonEmptyStr,
    SchemaVersion,
    Sha256,
    StageId,
    TaskId,
)
from .error import ErrorDetail
from .hardware import DeviceRuntime
from .result import ParseResult
from .source import SourceMetadata
from .trace import TraceContext


class RemoteBackendAuthentication(StrictSchema):
    type: Literal["none", "bearer", "x_api_key"] = "none"
    token: SecretStr | None = None

    @model_validator(mode="after")
    def validate_token(self) -> RemoteBackendAuthentication:
        if self.type == "none" and self.token is not None:
            raise ValueError("authentication type none cannot define a token")
        if self.type != "none" and self.token is None:
            raise ValueError(f"authentication type {self.type} requires a token")
        return self


class RemoteBackendConfig(StrictSchema):
    name: NonEmptyStr
    version: NonEmptyStr = "1.0"
    endpoint: AnyHttpUrl
    authentication: RemoteBackendAuthentication = Field(
        default_factory=RemoteBackendAuthentication
    )
    media_categories: list[MediaCategory] = Field(default_factory=list)
    mime_types: list[MimePattern] = Field(default_factory=list)
    maximum_concurrency: Annotated[int, Field(ge=1, le=1000, strict=True)] = 1
    timeout_seconds: Annotated[float, Field(gt=0.0, le=86_400.0, strict=True)] = 600.0
    maximum_response_bytes: Annotated[
        int,
        Field(ge=1, le=1024 * 1024 * 1024, strict=True),
    ] = 64 * 1024 * 1024
    maximum_artifacts: Annotated[int, Field(ge=0, le=1000, strict=True)] = 100
    maximum_artifact_bytes: Annotated[
        int,
        Field(ge=1, le=1024 * 1024 * 1024, strict=True),
    ] = 32 * 1024 * 1024

    @model_validator(mode="after")
    def validate_capability(self) -> RemoteBackendConfig:
        if (
            self.endpoint.username is not None
            or self.endpoint.password is not None
            or self.endpoint.fragment is not None
        ):
            raise ValueError(
                "remote Backend endpoint cannot contain credentials or a fragment"
            )
        if not self.media_categories and not self.mime_types:
            raise ValueError("a remote Backend needs media_categories or mime_types")
        if len(self.media_categories) != len(set(self.media_categories)):
            raise ValueError("media_categories must be unique")
        if len(self.mime_types) != len(set(self.mime_types)):
            raise ValueError("mime_types must be unique")
        return self


class RemoteSourceFile(StrictSchema):
    filename: NonEmptyStr
    mime_type: MimeType
    size_bytes: Annotated[int, Field(ge=0, strict=True)]
    sha256: Sha256


class RemoteParseRequest(StrictSchema):
    protocol_version: SchemaVersion = "1.0"
    task_id: TaskId
    stage_id: StageId
    backend_name: NonEmptyStr
    backend_version: NonEmptyStr
    runtime: DeviceRuntime
    device_id: NonEmptyStr | None = None
    trace_context: TraceContext | None = None
    source: SourceMetadata
    source_text: str | None = None
    source_file: RemoteSourceFile | None = None
    parameters: dict[str, JsonValue] = Field(default_factory=dict)
    timeout_seconds: Annotated[int, Field(ge=1, le=86_400, strict=True)]

    @model_validator(mode="after")
    def validate_source_payload(self) -> RemoteParseRequest:
        if (self.source_text is None) == (self.source_file is None):
            raise ValueError("exactly one of source_text or source_file is required")
        return self


class RemoteArtifactPayload(StrictSchema):
    type: ArtifactType
    filename: NonEmptyStr
    mime_type: MimeType
    content_base64: Base64Bytes
    metadata: dict[str, JsonValue] = Field(default_factory=dict)


class RemoteParseSucceeded(StrictSchema):
    status: Literal["succeeded"]
    result: ParseResult
    artifacts: list[RemoteArtifactPayload] = Field(default_factory=list)


class RemoteParseFailed(StrictSchema):
    status: Literal["failed"]
    error: ErrorDetail


RemoteParseResponse = Annotated[
    RemoteParseSucceeded | RemoteParseFailed,
    Field(discriminator="status"),
]


__all__ = [
    "RemoteArtifactPayload",
    "RemoteBackendAuthentication",
    "RemoteBackendConfig",
    "RemoteParseFailed",
    "RemoteParseRequest",
    "RemoteParseResponse",
    "RemoteParseSucceeded",
    "RemoteSourceFile",
]
