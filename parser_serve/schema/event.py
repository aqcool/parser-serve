"""Internal event bus and external SSE event contracts."""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Literal

from pydantic import Field

from .base import StrictSchema
from .callback import CallbackDeliveryStatus
from .common import (
    CallbackDeliveryId,
    EventId,
    ListResponse,
    NonEmptyStr,
    Percent,
    PipelineId,
    PositiveVersion,
    SchemaVersion,
    SortDirection,
    StageId,
    TaskId,
    UTCDateTime,
    WorkerId,
)
from .error import ErrorDetail
from .stage import StageStatus
from .task import TaskStatus
from .worker import WorkerStatus


class TaskCreatedEvent(StrictSchema):
    type: Literal["task.created"]
    task_id: TaskId


class TaskStatusChangedEvent(StrictSchema):
    type: Literal["task.status_changed"]
    task_id: TaskId
    previous_status: TaskStatus
    current_status: TaskStatus


class TaskRoutedEvent(StrictSchema):
    type: Literal["task.routed"]
    task_id: TaskId
    pipeline_id: PipelineId
    pipeline_version: PositiveVersion
    stage_ids: list[StageId]


class TaskProgressUpdatedEvent(StrictSchema):
    type: Literal["task.progress_updated"]
    task_id: TaskId
    progress_percent: Percent
    stage_id: StageId | None = None
    stage_status: StageStatus | None = None


class WorkerStatusChangedEvent(StrictSchema):
    type: Literal["worker.status_changed"]
    worker_id: WorkerId
    previous_status: WorkerStatus | None = None
    current_status: WorkerStatus


class CallbackDeliveryChangedEvent(StrictSchema):
    type: Literal["callback.delivery_changed"]
    delivery_id: CallbackDeliveryId
    task_id: TaskId
    status: CallbackDeliveryStatus


class SystemAlertEvent(StrictSchema):
    type: Literal["system.alert"]
    severity: Literal["info", "warning", "critical"]
    code: NonEmptyStr
    message: NonEmptyStr
    error: ErrorDetail | None = None


EventPayload = Annotated[
    TaskCreatedEvent
    | TaskRoutedEvent
    | TaskStatusChangedEvent
    | TaskProgressUpdatedEvent
    | WorkerStatusChangedEvent
    | CallbackDeliveryChangedEvent
    | SystemAlertEvent,
    Field(discriminator="type"),
]


class EventEnvelope(StrictSchema):
    schema_version: SchemaVersion
    event_id: EventId
    occurred_at: UTCDateTime
    payload: EventPayload


class EventStreamQuery(StrictSchema):
    types: list[NonEmptyStr] = Field(default_factory=list)
    task_id: TaskId | None = None
    worker_id: WorkerId | None = None
    last_event_id: EventId | None = None


class EventSortField(StrEnum):
    OCCURRED_AT = "occurred_at"
    TYPE = "type"


class EventListQuery(EventStreamQuery):
    limit: Annotated[int, Field(ge=1, le=200, strict=True)] = 50
    sort_by: EventSortField = EventSortField.OCCURRED_AT
    sort_direction: SortDirection = SortDirection.ASC


EventListResponse = ListResponse[EventEnvelope]


__all__ = [
    "CallbackDeliveryChangedEvent",
    "EventEnvelope",
    "EventListQuery",
    "EventListResponse",
    "EventSortField",
    "EventPayload",
    "EventStreamQuery",
    "SystemAlertEvent",
    "TaskCreatedEvent",
    "TaskProgressUpdatedEvent",
    "TaskRoutedEvent",
    "TaskStatusChangedEvent",
    "WorkerStatusChangedEvent",
]
