"""System capabilities, settings, and management query contracts."""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated

from pydantic import Field, model_validator

from .backend import BackendStatus
from .base import JsonValue, StrictSchema
from .common import (
    ApiResponse,
    MediaCategory,
    MimePattern,
    NonEmptyStr,
    SchemaVersion,
    SortDirection,
    StrictBool,
    UTCDateTime,
    WorkerId,
)
from .hardware import DeviceRuntime, HardwareVendor
from .worker import WorkerStatus


class RuntimeCapability(StrictSchema):
    runtime: DeviceRuntime
    vendor: HardwareVendor
    available_workers: Annotated[int, Field(ge=0, strict=True)]
    available_devices: Annotated[int, Field(ge=0, strict=True)]


class ParserCapabilitiesData(StrictSchema):
    schema_version: SchemaVersion
    media_categories: list[MediaCategory]
    mime_types: list[MimePattern]
    runtimes: list[RuntimeCapability]
    pipelines: list[NonEmptyStr]
    backends: list[NonEmptyStr]
    maximum_upload_bytes: Annotated[int, Field(ge=1, strict=True)]


class SystemInfoData(StrictSchema):
    name: NonEmptyStr
    version: NonEmptyStr
    api_version: SchemaVersion
    result_schema_version: SchemaVersion
    build_commit: NonEmptyStr | None = None
    build_time: UTCDateTime | None = None


class SettingKey(StrEnum):
    MAXIMUM_UPLOAD_BYTES = "maximum_upload_bytes"
    MAXIMUM_RESULT_JSON_BYTES = "maximum_result_json_bytes"
    CALLBACK_MAXIMUM_ATTEMPTS = "callback_maximum_attempts"


class SettingSource(StrEnum):
    DEPLOYMENT = "deployment"
    DATABASE = "database"


class SystemSetting(StrictSchema):
    key: SettingKey
    value: JsonValue
    source: SettingSource
    updated_at: UTCDateTime | None = None

    @model_validator(mode="after")
    def validate_setting(self) -> SystemSetting:
        _validate_setting_value(self.key, self.value)
        if self.source is SettingSource.DATABASE and self.updated_at is None:
            raise ValueError("database settings require updated_at")
        if self.source is SettingSource.DEPLOYMENT and self.updated_at is not None:
            raise ValueError("deployment settings cannot define updated_at")
        return self


class UpdateSetting(StrictSchema):
    key: SettingKey
    value: JsonValue

    @model_validator(mode="after")
    def validate_value(self) -> UpdateSetting:
        _validate_setting_value(self.key, self.value)
        return self


def _validate_setting_value(key: SettingKey, value: JsonValue) -> None:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{key.value} must be an integer")
    if key is SettingKey.CALLBACK_MAXIMUM_ATTEMPTS:
        if not 1 <= value <= 20:
            raise ValueError("callback_maximum_attempts must be between 1 and 20")
    elif not 1 <= value <= 1024 * 1024 * 1024:
        raise ValueError(f"{key.value} must be between 1 byte and 1 GiB")


class UpdateSettingsRequest(StrictSchema):
    settings: Annotated[list[UpdateSetting], Field(min_length=1)]

    @model_validator(mode="after")
    def validate_keys(self) -> UpdateSettingsRequest:
        keys = [setting.key for setting in self.settings]
        if len(keys) != len(set(keys)):
            raise ValueError("setting keys must be unique")
        return self


class SystemSettingsData(StrictSchema):
    settings: Annotated[list[SystemSetting], Field(min_length=1)]


SystemSettingsResponse = ApiResponse[SystemSettingsData]


class WorkerSortField(StrEnum):
    CREATED_AT = "created_at"
    UPDATED_AT = "updated_at"
    NAME = "name"


class WorkerListQuery(StrictSchema):
    statuses: list[WorkerStatus] = Field(default_factory=list)
    runtimes: list[DeviceRuntime] = Field(default_factory=list)
    labels: dict[NonEmptyStr, NonEmptyStr] = Field(default_factory=dict)
    name_contains: (
        Annotated[
            str,
            Field(min_length=1, max_length=128, strict=True),
        ]
        | None
    ) = None
    limit: Annotated[int, Field(ge=1, le=200, strict=True)] = 50
    cursor: str | None = None
    sort_by: WorkerSortField = WorkerSortField.CREATED_AT
    sort_direction: SortDirection = SortDirection.DESC


class UpdateWorkerRequest(StrictSchema):
    enabled: StrictBool | None = None
    draining: StrictBool | None = None
    maximum_concurrency: (
        Annotated[
            int,
            Field(ge=1, strict=True),
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
    labels: dict[NonEmptyStr, NonEmptyStr] | None = None

    @model_validator(mode="after")
    def require_change(self) -> UpdateWorkerRequest:
        if all(
            value is None
            for value in (
                self.enabled,
                self.draining,
                self.maximum_concurrency,
                self.scheduling_weight,
                self.labels,
            )
        ):
            raise ValueError("at least one worker field must be updated")
        return self


class ComponentHealth(StrictSchema):
    name: NonEmptyStr
    healthy: StrictBool
    message: str | None = None
    checked_at: UTCDateTime


class SystemHealthData(StrictSchema):
    healthy: StrictBool
    components: list[ComponentHealth]

    @model_validator(mode="after")
    def validate_health(self) -> SystemHealthData:
        expected = all(component.healthy for component in self.components)
        if self.healthy is not expected:
            raise ValueError("system health must match component health")
        return self


class ManagementSummaryQuery(StrictSchema):
    worker_id: WorkerId | None = None
    worker_status: WorkerStatus | None = None
    backend_status: BackendStatus | None = None


__all__ = [
    "ComponentHealth",
    "ManagementSummaryQuery",
    "ParserCapabilitiesData",
    "RuntimeCapability",
    "SettingKey",
    "SettingSource",
    "SystemSetting",
    "SystemSettingsData",
    "SystemSettingsResponse",
    "SystemHealthData",
    "SystemInfoData",
    "UpdateSetting",
    "UpdateSettingsRequest",
    "UpdateWorkerRequest",
    "WorkerListQuery",
    "WorkerSortField",
]
