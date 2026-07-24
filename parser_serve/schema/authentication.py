"""API key creation and management contracts."""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated

from pydantic import Field, StringConstraints, model_validator

from .base import StrictSchema
from .common import (
    ApiKeyId,
    ApiResponse,
    ListResponse,
    NonEmptyStr,
    SortDirection,
    StrictBool,
    UTCDateTime,
    WorkerId,
)


ApiKeyValue = Annotated[
    str,
    StringConstraints(pattern=r"^parser_[a-zA-Z0-9_-]{32,128}$", strict=True),
]
ApiKeyPrefix = Annotated[
    str,
    StringConstraints(pattern=r"^parser_[a-zA-Z0-9_-]{4,16}$", strict=True),
]


class ApiKeyStatus(StrEnum):
    ACTIVE = "active"
    DISABLED = "disabled"
    EXPIRED = "expired"


class ApiKeyKind(StrEnum):
    ORDINARY = "ordinary"
    WORKER = "worker"


class CreateApiKeyRequest(StrictSchema):
    name: NonEmptyStr
    kind: ApiKeyKind = ApiKeyKind.ORDINARY
    worker_id: WorkerId | None = None
    expires_at: UTCDateTime | None = None

    @model_validator(mode="after")
    def validate_worker_binding(self) -> CreateApiKeyRequest:
        if self.kind is ApiKeyKind.WORKER and self.worker_id is None:
            raise ValueError("worker API keys require worker_id")
        if self.kind is ApiKeyKind.ORDINARY and self.worker_id is not None:
            raise ValueError("ordinary API keys cannot bind worker_id")
        return self


class ApiKeySummary(StrictSchema):
    api_key_id: ApiKeyId
    name: NonEmptyStr
    kind: ApiKeyKind = ApiKeyKind.ORDINARY
    worker_id: WorkerId | None = None
    prefix: ApiKeyPrefix
    status: ApiKeyStatus
    created_at: UTCDateTime
    updated_at: UTCDateTime
    expires_at: UTCDateTime | None = None
    last_used_at: UTCDateTime | None = None

    @model_validator(mode="after")
    def validate_timestamps(self) -> ApiKeySummary:
        if self.kind is ApiKeyKind.WORKER and self.worker_id is None:
            raise ValueError("worker API key summaries require worker_id")
        if self.kind is ApiKeyKind.ORDINARY and self.worker_id is not None:
            raise ValueError("ordinary API key summaries cannot bind worker_id")
        if self.updated_at < self.created_at:
            raise ValueError("updated_at cannot be earlier than created_at")
        if self.expires_at is not None and self.expires_at <= self.created_at:
            raise ValueError("expires_at must be later than created_at")
        if self.last_used_at is not None and self.last_used_at < self.created_at:
            raise ValueError("last_used_at cannot be earlier than created_at")
        return self


class CreateApiKeyData(StrictSchema):
    api_key: ApiKeyValue
    summary: ApiKeySummary


CreateApiKeyResponse = ApiResponse[CreateApiKeyData]
ApiKeyResponse = ApiResponse[ApiKeySummary]
ApiKeyListResponse = ListResponse[ApiKeySummary]


class UpdateApiKeyRequest(StrictSchema):
    name: NonEmptyStr | None = None
    enabled: StrictBool | None = None
    expires_at: UTCDateTime | None = None

    @model_validator(mode="after")
    def require_change(self) -> UpdateApiKeyRequest:
        if self.name is None and self.enabled is None and self.expires_at is None:
            raise ValueError("at least one API key field must be updated")
        return self


class RotateApiKeyData(StrictSchema):
    api_key: ApiKeyValue
    summary: ApiKeySummary
    previous_key_valid_until: UTCDateTime | None = None


RotateApiKeyResponse = ApiResponse[RotateApiKeyData]


class DeleteApiKeyData(StrictSchema):
    api_key_id: ApiKeyId
    deleted: StrictBool


DeleteApiKeyResponse = ApiResponse[DeleteApiKeyData]


class ApiKeySortField(StrEnum):
    CREATED_AT = "created_at"
    UPDATED_AT = "updated_at"
    NAME = "name"


class ApiKeyListQuery(StrictSchema):
    kinds: list[ApiKeyKind] = Field(default_factory=list)
    statuses: list[ApiKeyStatus] = Field(default_factory=list)
    name_contains: (
        Annotated[
            str,
            Field(min_length=1, max_length=128, strict=True),
        ]
        | None
    ) = None
    limit: Annotated[int, Field(ge=1, le=200, strict=True)] = 50
    cursor: str | None = None
    sort_by: ApiKeySortField = ApiKeySortField.CREATED_AT
    sort_direction: SortDirection = SortDirection.DESC


__all__ = [
    "ApiKeyKind",
    "ApiKeyListQuery",
    "ApiKeyListResponse",
    "ApiKeyPrefix",
    "ApiKeyResponse",
    "ApiKeySortField",
    "ApiKeyStatus",
    "ApiKeySummary",
    "ApiKeyValue",
    "CreateApiKeyData",
    "CreateApiKeyRequest",
    "CreateApiKeyResponse",
    "DeleteApiKeyData",
    "DeleteApiKeyResponse",
    "RotateApiKeyData",
    "RotateApiKeyResponse",
    "UpdateApiKeyRequest",
]
