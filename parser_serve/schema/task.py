"""Task creation, status, and query contracts."""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated

from pydantic import Field, model_validator

from .base import StrictSchema
from .callback import CallbackConfig
from .common import (
    ApiResponse,
    Cursor,
    MediaCategory,
    ListResponse,
    NonEmptyStr,
    Percent,
    PipelineId,
    PositiveVersion,
    Priority,
    SortDirection,
    StrictBool,
    TaskId,
    UTCDateTime,
)
from .error import ErrorDetail
from .hardware import DeviceRequirement, DeviceRuntime
from .source import ParseSource, SourceMetadata
from .stage import StageDetail


class TaskStatus(StrEnum):
    PENDING = "pending"
    LEASED = "leased"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ParseFeatures(StrictSchema):
    extract_text: StrictBool = True
    extract_tables: StrictBool = True
    extract_images: StrictBool = False
    run_ocr: StrictBool = False
    generate_captions: StrictBool = False
    transcribe_audio: StrictBool = False
    extract_keyframes: StrictBool = False


class TaskOptions(StrictSchema):
    pipeline_id: PipelineId | None = None
    pipeline_version: PositiveVersion | None = None
    backend_name: NonEmptyStr | None = None
    priority: Priority = 0
    timeout_seconds: Annotated[int, Field(ge=1, le=86_400, strict=True)] | None = None
    device: DeviceRequirement = Field(default_factory=DeviceRequirement)
    features: ParseFeatures = Field(default_factory=ParseFeatures)

    @model_validator(mode="after")
    def validate_pipeline_version(self) -> TaskOptions:
        if self.pipeline_version is not None and self.pipeline_id is None:
            raise ValueError("pipeline_version requires pipeline_id")
        return self


class CreateTaskRequest(StrictSchema):
    source: ParseSource
    options: TaskOptions = Field(default_factory=TaskOptions)
    callback: CallbackConfig | None = None
    client_reference: (
        Annotated[
            str,
            Field(min_length=1, max_length=256, strict=True),
        ]
        | None
    ) = None


class CreateTaskData(StrictSchema):
    task_id: TaskId
    status: TaskStatus
    created_at: UTCDateTime
    estimated_wait_seconds: Annotated[int, Field(ge=0, strict=True)] | None = None


CreateTaskResponse = ApiResponse[CreateTaskData]


class TaskDetail(StrictSchema):
    task_id: TaskId
    status: TaskStatus
    progress_percent: Percent = 0.0
    source: ParseSource
    source_metadata: SourceMetadata | None = None
    options: TaskOptions
    pipeline_id: PipelineId | None = None
    pipeline_version: PositiveVersion | None = None
    stages: list[StageDetail] = Field(default_factory=list)
    client_reference: str | None = None
    created_at: UTCDateTime
    started_at: UTCDateTime | None = None
    completed_at: UTCDateTime | None = None
    result_uri: NonEmptyStr | None = None
    error: ErrorDetail | None = None

    @model_validator(mode="after")
    def validate_state(self) -> TaskDetail:
        if (self.pipeline_id is None) != (self.pipeline_version is None):
            raise ValueError(
                "pipeline_id and pipeline_version must be defined together"
            )
        requires_pipeline = {
            TaskStatus.LEASED,
            TaskStatus.RUNNING,
            TaskStatus.SUCCEEDED,
            TaskStatus.FAILED,
        }
        if self.status in requires_pipeline and self.pipeline_id is None:
            raise ValueError("executable tasks require a bound pipeline version")
        terminal = {
            TaskStatus.SUCCEEDED,
            TaskStatus.FAILED,
            TaskStatus.CANCELLED,
        }
        if self.status in terminal and self.completed_at is None:
            raise ValueError("terminal tasks require completed_at")
        if self.status is TaskStatus.FAILED and self.error is None:
            raise ValueError("failed tasks require error details")
        if self.status is not TaskStatus.FAILED and self.error is not None:
            raise ValueError("only failed tasks may contain error details")
        if self.status is not TaskStatus.SUCCEEDED and self.result_uri is not None:
            raise ValueError("only succeeded tasks may contain result_uri")
        if self.status is TaskStatus.RUNNING and self.started_at is None:
            raise ValueError("running tasks require started_at")
        if self.started_at is not None and self.started_at < self.created_at:
            raise ValueError("started_at cannot be earlier than created_at")
        if (
            self.started_at is not None
            and self.completed_at is not None
            and self.completed_at < self.started_at
        ):
            raise ValueError("completed_at cannot be earlier than started_at")
        return self


TaskDetailResponse = ApiResponse[TaskDetail]
TaskListResponse = ListResponse[TaskDetail]


class TaskSortField(StrEnum):
    CREATED_AT = "created_at"
    UPDATED_AT = "updated_at"
    PRIORITY = "priority"


class TaskListQuery(StrictSchema):
    statuses: list[TaskStatus] = Field(default_factory=list)
    media_category: MediaCategory | None = None
    pipeline_id: PipelineId | None = None
    backend_name: NonEmptyStr | None = None
    runtime: DeviceRuntime | None = None
    created_after: UTCDateTime | None = None
    created_before: UTCDateTime | None = None
    limit: Annotated[int, Field(ge=1, le=200, strict=True)] = 50
    cursor: Cursor | None = None
    sort_by: TaskSortField = TaskSortField.CREATED_AT
    sort_direction: SortDirection = SortDirection.DESC

    @model_validator(mode="after")
    def validate_time_range(self) -> TaskListQuery:
        if (
            self.created_after is not None
            and self.created_before is not None
            and self.created_before < self.created_after
        ):
            raise ValueError("created_before cannot be earlier than created_after")
        return self


__all__ = [
    "CreateTaskData",
    "CreateTaskRequest",
    "CreateTaskResponse",
    "ParseFeatures",
    "TaskDetail",
    "TaskDetailResponse",
    "TaskListQuery",
    "TaskListResponse",
    "TaskOptions",
    "TaskSortField",
    "TaskStatus",
]
