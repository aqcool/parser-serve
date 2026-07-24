"""Parser backend capability and management contracts."""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated

from pydantic import AnyUrl, Field, model_validator

from .base import JsonValue, StrictSchema
from .common import (
    ApiResponse,
    BackendId,
    ListResponse,
    MediaCategory,
    MimePattern,
    NonEmptyStr,
    SortDirection,
    StrictBool,
    UTCDateTime,
)
from .hardware import DeviceRuntime


class BackendStatus(StrEnum):
    ENABLED = "enabled"
    DISABLED = "disabled"
    UNHEALTHY = "unhealthy"


class BackendExecutionMode(StrEnum):
    LOCAL = "local"
    REMOTE = "remote"


class BackendLoadTarget(StrictSchema):
    """An exact Worker-local Backend model selected for startup preloading."""

    name: NonEmptyStr
    version: NonEmptyStr


class BackendCapability(StrictSchema):
    name: NonEmptyStr
    version: NonEmptyStr
    media_categories: list[MediaCategory] = Field(default_factory=list)
    mime_types: list[MimePattern] = Field(default_factory=list)
    runtimes: Annotated[list[DeviceRuntime], Field(min_length=1)]
    maximum_concurrency: Annotated[int, Field(ge=1, strict=True)]

    @model_validator(mode="after")
    def validate_capability(self) -> BackendCapability:
        if not self.media_categories and not self.mime_types:
            raise ValueError(
                "a backend capability needs media_categories or mime_types"
            )
        if len(self.runtimes) != len(set(self.runtimes)):
            raise ValueError("runtimes must not contain duplicates")
        return self


class BackendDetail(StrictSchema):
    backend_id: BackendId
    capability: BackendCapability
    status: BackendStatus
    execution_mode: BackendExecutionMode
    default_timeout_seconds: Annotated[
        int,
        Field(ge=1, le=86_400, strict=True),
    ]
    maximum_attempts: Annotated[int, Field(ge=1, le=20, strict=True)] = 1
    scheduling_weight: Annotated[int, Field(ge=1, le=1000, strict=True)] = 100
    remote_url: AnyUrl | None = None
    configuration: dict[str, JsonValue] = Field(default_factory=dict)
    created_at: UTCDateTime
    updated_at: UTCDateTime

    @model_validator(mode="after")
    def validate_backend(self) -> BackendDetail:
        if self.updated_at < self.created_at:
            raise ValueError("updated_at cannot be earlier than created_at")
        if (
            self.execution_mode is BackendExecutionMode.REMOTE
            and self.remote_url is None
        ):
            raise ValueError("remote backends require remote_url")
        if (
            self.execution_mode is BackendExecutionMode.LOCAL
            and self.remote_url is not None
        ):
            raise ValueError("local backends cannot define remote_url")
        return self


BackendDetailResponse = ApiResponse[BackendDetail]
BackendListResponse = ListResponse[BackendDetail]


class CreateBackendRequest(StrictSchema):
    capability: BackendCapability
    execution_mode: BackendExecutionMode
    default_timeout_seconds: Annotated[
        int,
        Field(ge=1, le=86_400, strict=True),
    ]
    maximum_attempts: Annotated[int, Field(ge=1, le=20, strict=True)] = 1
    scheduling_weight: Annotated[int, Field(ge=1, le=1000, strict=True)] = 100
    remote_url: AnyUrl | None = None
    configuration: dict[str, JsonValue] = Field(default_factory=dict)
    enabled: StrictBool = True

    @model_validator(mode="after")
    def validate_execution(self) -> CreateBackendRequest:
        if (
            self.execution_mode is BackendExecutionMode.REMOTE
            and self.remote_url is None
        ):
            raise ValueError("remote backends require remote_url")
        if (
            self.execution_mode is BackendExecutionMode.LOCAL
            and self.remote_url is not None
        ):
            raise ValueError("local backends cannot define remote_url")
        return self


class UpdateBackendRequest(StrictSchema):
    enabled: StrictBool | None = None
    default_timeout_seconds: (
        Annotated[
            int,
            Field(ge=1, le=86_400, strict=True),
        ]
        | None
    ) = None
    maximum_attempts: (
        Annotated[
            int,
            Field(ge=1, le=20, strict=True),
        ]
        | None
    ) = None
    scheduling_weight: (
        Annotated[
            int,
            Field(ge=1, le=1000, strict=True),
        ]
        | None
    ) = None
    configuration: dict[str, JsonValue] | None = None

    @model_validator(mode="after")
    def require_change(self) -> UpdateBackendRequest:
        if all(
            value is None
            for value in (
                self.enabled,
                self.default_timeout_seconds,
                self.maximum_attempts,
                self.scheduling_weight,
                self.configuration,
            )
        ):
            raise ValueError("at least one backend field must be updated")
        return self


class BackendSortField(StrEnum):
    CREATED_AT = "created_at"
    UPDATED_AT = "updated_at"
    NAME = "name"


class BackendListQuery(StrictSchema):
    statuses: list[BackendStatus] = Field(default_factory=list)
    runtimes: list[DeviceRuntime] = Field(default_factory=list)
    media_category: MediaCategory | None = None
    execution_mode: BackendExecutionMode | None = None
    name_contains: (
        Annotated[
            str,
            Field(min_length=1, max_length=128, strict=True),
        ]
        | None
    ) = None
    limit: Annotated[int, Field(ge=1, le=200, strict=True)] = 50
    cursor: str | None = None
    sort_by: BackendSortField = BackendSortField.CREATED_AT
    sort_direction: SortDirection = SortDirection.DESC


__all__ = [
    "BackendCapability",
    "BackendDetail",
    "BackendDetailResponse",
    "BackendExecutionMode",
    "BackendLoadTarget",
    "BackendListQuery",
    "BackendListResponse",
    "BackendSortField",
    "BackendStatus",
    "CreateBackendRequest",
    "UpdateBackendRequest",
]
