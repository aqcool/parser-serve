"""Pipeline stage state and execution records."""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated

from pydantic import Field, model_validator

from .base import StrictSchema
from .common import (
    ApiResponse,
    BackendId,
    Cursor,
    ListResponse,
    NonEmptyStr,
    Percent,
    SortDirection,
    StageId,
    StrictBool,
    UTCDateTime,
    WorkerId,
)
from .error import ErrorDetail
from .hardware import DeviceRuntime


class StageStatus(StrEnum):
    PENDING = "pending"
    LEASED = "leased"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"
    SKIPPED = "skipped"


class StageSortField(StrEnum):
    POSITION = "position"
    CREATED_AT = "created_at"


class StageListQuery(StrictSchema):
    statuses: list[StageStatus] = Field(default_factory=list)
    backend_id: BackendId | None = None
    worker_id: WorkerId | None = None
    limit: Annotated[int, Field(ge=1, le=200, strict=True)] = 50
    cursor: Cursor | None = None
    sort_by: StageSortField = StageSortField.POSITION
    sort_direction: SortDirection = SortDirection.ASC


class StageDetail(StrictSchema):
    stage_id: StageId
    name: NonEmptyStr
    position: Annotated[int, Field(ge=0, strict=True)] = 0
    depends_on: list[NonEmptyStr] = Field(default_factory=list)
    optional: StrictBool = False
    timeout_seconds: Annotated[int, Field(ge=1, le=86_400, strict=True)] | None = None
    status: StageStatus
    progress_percent: Percent = 0.0
    backend_id: BackendId | None = None
    backend_version: NonEmptyStr | None = None
    backend_candidates: list[BackendId] = Field(default_factory=list)
    worker_id: WorkerId | None = None
    runtime: DeviceRuntime | None = None
    device_id: NonEmptyStr | None = None
    completion_worker_id: WorkerId | None = None
    completion_device_id: NonEmptyStr | None = None
    required_runtimes: list[DeviceRuntime] = Field(default_factory=list)
    attempt: Annotated[int, Field(ge=0, strict=True)] = 0
    maximum_attempts: Annotated[int, Field(ge=1, strict=True)] = 1
    created_at: UTCDateTime
    started_at: UTCDateTime | None = None
    completed_at: UTCDateTime | None = None
    result_uri: NonEmptyStr | None = None
    error: ErrorDetail | None = None

    @model_validator(mode="after")
    def validate_state(self) -> StageDetail:
        if len(self.depends_on) != len(set(self.depends_on)):
            raise ValueError("depends_on must not contain duplicates")
        if len(self.backend_candidates) != len(set(self.backend_candidates)):
            raise ValueError("backend_candidates must not contain duplicates")
        if len(self.required_runtimes) != len(set(self.required_runtimes)):
            raise ValueError("required_runtimes must not contain duplicates")
        terminal = {
            StageStatus.SUCCEEDED,
            StageStatus.FAILED,
            StageStatus.CANCELLED,
            StageStatus.SKIPPED,
        }
        if self.status in terminal and self.completed_at is None:
            raise ValueError("terminal stages require completed_at")
        if self.status is StageStatus.FAILED and self.error is None:
            raise ValueError("failed stages require error details")
        if self.status is not StageStatus.FAILED and self.error is not None:
            raise ValueError("only failed stages may contain error details")
        if self.status is not StageStatus.SUCCEEDED and self.result_uri is not None:
            raise ValueError("only succeeded stages may contain result_uri")
        if self.attempt > self.maximum_attempts:
            raise ValueError("attempt cannot exceed maximum_attempts")
        if self.status is StageStatus.RUNNING and self.started_at is None:
            raise ValueError("running stages require started_at")
        if self.completion_device_id is not None and self.completion_worker_id is None:
            raise ValueError("completion_device_id requires completion_worker_id")
        if self.started_at is not None and self.started_at < self.created_at:
            raise ValueError("started_at cannot be earlier than created_at")
        if (
            self.started_at is not None
            and self.completed_at is not None
            and self.completed_at < self.started_at
        ):
            raise ValueError("completed_at cannot be earlier than started_at")
        return self


StageDetailResponse = ApiResponse[StageDetail]
StageListResponse = ListResponse[StageDetail]


__all__ = [
    "StageDetail",
    "StageDetailResponse",
    "StageListQuery",
    "StageListResponse",
    "StageSortField",
    "StageStatus",
]
