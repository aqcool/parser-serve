"""Callback configuration, event payload, and delivery contracts."""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Literal

from pydantic import Field, HttpUrl, StringConstraints, model_validator

from .base import JsonValue, StrictSchema
from .common import (
    ApiResponse,
    CallbackAttemptId,
    CallbackDeliveryId,
    EventId,
    ListResponse,
    NonEmptyStr,
    Percent,
    SchemaVersion,
    SortDirection,
    StrictBool,
    StageId,
    TaskId,
    UTCDateTime,
)
from .error import ErrorDetail


CallbackSecret = Annotated[
    str,
    StringConstraints(min_length=32, max_length=256, strict=True),
]


class CallbackEventType(StrEnum):
    TASK_CREATED = "task.created"
    TASK_RUNNING = "task.running"
    TASK_PROGRESS = "task.progress"
    TASK_SUCCEEDED = "task.succeeded"
    TASK_FAILED = "task.failed"
    TASK_CANCELLED = "task.cancelled"


class CallbackConfig(StrictSchema):
    url: HttpUrl
    events: Annotated[list[CallbackEventType], Field(min_length=1)]
    secret: CallbackSecret | None = None

    @model_validator(mode="after")
    def validate_events(self) -> CallbackConfig:
        if len(self.events) != len(set(self.events)):
            raise ValueError("callback events must be unique")
        return self


class TaskCreatedCallback(StrictSchema):
    type: Literal["task.created"]
    created_at: UTCDateTime


class TaskRunningCallback(StrictSchema):
    type: Literal["task.running"]
    started_at: UTCDateTime


class TaskProgressCallback(StrictSchema):
    type: Literal["task.progress"]
    progress_percent: Percent
    stage_id: StageId | None = None
    stage_name: NonEmptyStr | None = None
    updated_at: UTCDateTime


class TaskSucceededCallback(StrictSchema):
    type: Literal["task.succeeded"]
    result_uri: NonEmptyStr | None = None
    completed_at: UTCDateTime


class TaskFailedCallback(StrictSchema):
    type: Literal["task.failed"]
    error: ErrorDetail
    failed_at: UTCDateTime


class TaskCancelledCallback(StrictSchema):
    type: Literal["task.cancelled"]
    cancelled_at: UTCDateTime
    reason: str | None = None


CallbackPayload = Annotated[
    TaskCreatedCallback
    | TaskRunningCallback
    | TaskProgressCallback
    | TaskSucceededCallback
    | TaskFailedCallback
    | TaskCancelledCallback,
    Field(discriminator="type"),
]


class CallbackEvent(StrictSchema):
    schema_version: SchemaVersion
    event_id: EventId
    task_id: TaskId
    occurred_at: UTCDateTime
    payload: CallbackPayload


class CallbackDeliveryStatus(StrEnum):
    PENDING = "pending"
    DELIVERING = "delivering"
    SUCCEEDED = "succeeded"
    RETRY_WAIT = "retry_wait"
    FAILED = "failed"
    CANCELLED = "cancelled"


class CallbackDeliveryDetail(StrictSchema):
    delivery_id: CallbackDeliveryId
    event: CallbackEvent
    target_url: HttpUrl
    status: CallbackDeliveryStatus
    attempt: Annotated[int, Field(ge=0, strict=True)]
    total_attempts: Annotated[int, Field(ge=0, strict=True)]
    maximum_attempts: Annotated[int, Field(ge=1, le=20, strict=True)]
    response_status_code: (
        Annotated[
            int,
            Field(ge=100, le=599, strict=True),
        ]
        | None
    ) = None
    response_summary: str | None = None
    next_attempt_at: UTCDateTime | None = None
    created_at: UTCDateTime
    updated_at: UTCDateTime

    @model_validator(mode="after")
    def validate_delivery(self) -> CallbackDeliveryDetail:
        if self.attempt > self.maximum_attempts:
            raise ValueError("attempt cannot exceed maximum_attempts")
        if self.attempt > self.total_attempts:
            raise ValueError("attempt cannot exceed total_attempts")
        if self.updated_at < self.created_at:
            raise ValueError("updated_at cannot be earlier than created_at")
        if (
            self.status is CallbackDeliveryStatus.RETRY_WAIT
            and self.next_attempt_at is None
        ):
            raise ValueError("retry_wait deliveries require next_attempt_at")
        if (
            self.status is not CallbackDeliveryStatus.RETRY_WAIT
            and self.next_attempt_at is not None
        ):
            raise ValueError("only retry_wait deliveries may define next_attempt_at")
        return self


CallbackDeliveryResponse = ApiResponse[CallbackDeliveryDetail]
CallbackDeliveryListResponse = ListResponse[CallbackDeliveryDetail]


class CallbackAttempt(StrictSchema):
    attempt_id: CallbackAttemptId
    delivery_id: CallbackDeliveryId
    sequence: Annotated[int, Field(ge=1, strict=True)]
    attempt_number: Annotated[int, Field(ge=1, strict=True)]
    delivered: StrictBool
    response_status_code: (
        Annotated[
            int,
            Field(ge=100, le=599, strict=True),
        ]
        | None
    ) = None
    response_summary: str | None = None
    duration_ms: Annotated[int, Field(ge=0, strict=True)]
    error: ErrorDetail | None = None
    started_at: UTCDateTime
    completed_at: UTCDateTime

    @model_validator(mode="after")
    def validate_attempt(self) -> CallbackAttempt:
        if self.completed_at < self.started_at:
            raise ValueError("completed_at cannot be earlier than started_at")
        if self.delivered and self.error is not None:
            raise ValueError("successful callback attempts cannot contain an error")
        if not self.delivered and self.error is None:
            raise ValueError("failed callback attempts require an error")
        return self


CallbackAttemptListResponse = ListResponse[CallbackAttempt]


class CallbackSortField(StrEnum):
    CREATED_AT = "created_at"
    UPDATED_AT = "updated_at"
    STATUS = "status"


class CallbackListQuery(StrictSchema):
    statuses: list[CallbackDeliveryStatus] = Field(default_factory=list)
    task_id: TaskId | None = None
    event_types: list[CallbackEventType] = Field(default_factory=list)
    created_after: UTCDateTime | None = None
    created_before: UTCDateTime | None = None
    limit: Annotated[int, Field(ge=1, le=200, strict=True)] = 50
    cursor: str | None = None
    sort_by: CallbackSortField = CallbackSortField.CREATED_AT
    sort_direction: SortDirection = SortDirection.DESC

    @model_validator(mode="after")
    def validate_time_range(self) -> CallbackListQuery:
        if (
            self.created_after is not None
            and self.created_before is not None
            and self.created_before < self.created_after
        ):
            raise ValueError("created_before cannot be earlier than created_after")
        return self


class CallbackAttemptSortField(StrEnum):
    SEQUENCE = "sequence"
    STARTED_AT = "started_at"
    DURATION_MS = "duration_ms"


class CallbackAttemptListQuery(StrictSchema):
    delivered: StrictBool | None = None
    limit: Annotated[int, Field(ge=1, le=200, strict=True)] = 100
    cursor: str | None = None
    sort_by: CallbackAttemptSortField = CallbackAttemptSortField.SEQUENCE
    sort_direction: SortDirection = SortDirection.DESC


class CallbackTestRequest(StrictSchema):
    url: HttpUrl
    secret: CallbackSecret | None = None
    metadata: dict[str, JsonValue] = Field(default_factory=dict)


class CallbackTestEvent(StrictSchema):
    type: Literal["callback.test"]
    schema_version: SchemaVersion
    event_id: EventId
    occurred_at: UTCDateTime
    metadata: dict[str, JsonValue] = Field(default_factory=dict)


class CallbackTestData(StrictSchema):
    delivered: StrictBool
    response_status_code: (
        Annotated[
            int,
            Field(ge=100, le=599, strict=True),
        ]
        | None
    ) = None
    duration_ms: Annotated[int, Field(ge=0, strict=True)]
    error: ErrorDetail | None = None

    @model_validator(mode="after")
    def validate_result(self) -> CallbackTestData:
        if self.delivered and self.error is not None:
            raise ValueError("successful callback tests cannot contain an error")
        if not self.delivered and self.error is None:
            raise ValueError("failed callback tests require an error")
        return self


CallbackTestResponse = ApiResponse[CallbackTestData]


__all__ = [
    "CallbackAttempt",
    "CallbackAttemptListQuery",
    "CallbackAttemptListResponse",
    "CallbackAttemptSortField",
    "CallbackConfig",
    "CallbackDeliveryDetail",
    "CallbackDeliveryListResponse",
    "CallbackDeliveryResponse",
    "CallbackDeliveryStatus",
    "CallbackEvent",
    "CallbackEventType",
    "CallbackListQuery",
    "CallbackSortField",
    "CallbackPayload",
    "CallbackSecret",
    "CallbackTestData",
    "CallbackTestEvent",
    "CallbackTestRequest",
    "CallbackTestResponse",
    "TaskCancelledCallback",
    "TaskCreatedCallback",
    "TaskFailedCallback",
    "TaskProgressCallback",
    "TaskRunningCallback",
    "TaskSucceededCallback",
]
