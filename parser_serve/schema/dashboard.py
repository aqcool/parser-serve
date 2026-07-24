"""Typed dashboard queries and metric series."""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated

from pydantic import Field, model_validator

from .base import StrictSchema
from .common import (
    ApiResponse,
    BackendId,
    MediaCategory,
    NonEmptyStr,
    PipelineId,
    UTCDateTime,
    WorkerId,
)
from .hardware import DeviceRuntime


class MetricInterval(StrEnum):
    MINUTE = "1m"
    FIVE_MINUTES = "5m"
    HOUR = "1h"
    DAY = "1d"


class DashboardQuery(StrictSchema):
    start_time: UTCDateTime
    end_time: UTCDateTime
    interval: MetricInterval = MetricInterval.HOUR
    pipeline_id: PipelineId | None = None
    backend_id: BackendId | None = None
    worker_id: WorkerId | None = None
    runtime: DeviceRuntime | None = None
    media_category: MediaCategory | None = None

    @model_validator(mode="after")
    def validate_range(self) -> DashboardQuery:
        if self.end_time <= self.start_time:
            raise ValueError("end_time must be later than start_time")
        interval_seconds = {
            MetricInterval.MINUTE: 60,
            MetricInterval.FIVE_MINUTES: 300,
            MetricInterval.HOUR: 3600,
            MetricInterval.DAY: 86_400,
        }[self.interval]
        if (
            self.end_time - self.start_time
        ).total_seconds() / interval_seconds > 10_000:
            raise ValueError("dashboard range contains more than 10000 intervals")
        return self


class TimeSeriesPoint(StrictSchema):
    timestamp: UTCDateTime
    value: Annotated[float, Field(strict=True)]


class NamedTimeSeries(StrictSchema):
    name: NonEmptyStr
    unit: NonEmptyStr
    points: list[TimeSeriesPoint] = Field(default_factory=list)


class TaskDashboardSummary(StrictSchema):
    total_tasks: Annotated[int, Field(ge=0, strict=True)]
    pending_tasks: Annotated[int, Field(ge=0, strict=True)]
    running_tasks: Annotated[int, Field(ge=0, strict=True)]
    succeeded_tasks: Annotated[int, Field(ge=0, strict=True)]
    failed_tasks: Annotated[int, Field(ge=0, strict=True)]
    cancelled_tasks: Annotated[int, Field(ge=0, strict=True)]
    success_rate: Annotated[float, Field(ge=0.0, le=1.0, strict=True)]
    average_wait_ms: Annotated[float, Field(ge=0.0, strict=True)]
    average_execution_ms: Annotated[float, Field(ge=0.0, strict=True)]
    p50_execution_ms: Annotated[float, Field(ge=0.0, strict=True)]
    p95_execution_ms: Annotated[float, Field(ge=0.0, strict=True)]
    p99_execution_ms: Annotated[float, Field(ge=0.0, strict=True)]

    @model_validator(mode="after")
    def validate_counts(self) -> TaskDashboardSummary:
        statuses = (
            self.pending_tasks
            + self.running_tasks
            + self.succeeded_tasks
            + self.failed_tasks
            + self.cancelled_tasks
        )
        if statuses != self.total_tasks:
            raise ValueError("task status counts must equal total_tasks")
        return self


class WorkerDashboardSummary(StrictSchema):
    total_workers: Annotated[int, Field(ge=0, strict=True)]
    online_workers: Annotated[int, Field(ge=0, strict=True)]
    busy_workers: Annotated[int, Field(ge=0, strict=True)]
    draining_workers: Annotated[int, Field(ge=0, strict=True)]
    offline_workers: Annotated[int, Field(ge=0, strict=True)]
    unhealthy_workers: Annotated[int, Field(ge=0, strict=True)]
    total_concurrency: Annotated[int, Field(ge=0, strict=True)]
    used_concurrency: Annotated[int, Field(ge=0, strict=True)]

    @model_validator(mode="after")
    def validate_counts(self) -> WorkerDashboardSummary:
        statuses = (
            self.online_workers
            + self.busy_workers
            + self.draining_workers
            + self.offline_workers
            + self.unhealthy_workers
        )
        if statuses != self.total_workers:
            raise ValueError("worker status counts must equal total_workers")
        if self.used_concurrency > self.total_concurrency:
            raise ValueError("used_concurrency cannot exceed total_concurrency")
        return self


class BackendMetric(StrictSchema):
    backend_id: BackendId
    calls: Annotated[int, Field(ge=0, strict=True)]
    failures: Annotated[int, Field(ge=0, strict=True)]
    timeouts: Annotated[int, Field(ge=0, strict=True)]
    fallbacks: Annotated[int, Field(ge=0, strict=True)]
    average_duration_ms: Annotated[float, Field(ge=0.0, strict=True)]


class RuntimeMetric(StrictSchema):
    runtime: DeviceRuntime
    workers: Annotated[int, Field(ge=0, strict=True)]
    devices: Annotated[int, Field(ge=0, strict=True)]
    average_utilization_percent: (
        Annotated[
            float,
            Field(ge=0.0, le=100.0, strict=True),
        ]
        | None
    ) = None
    memory_used_bytes: Annotated[int, Field(ge=0, strict=True)] | None = None
    memory_total_bytes: Annotated[int, Field(ge=0, strict=True)] | None = None


class CallbackDashboardSummary(StrictSchema):
    total_deliveries: Annotated[int, Field(ge=0, strict=True)]
    successful_deliveries: Annotated[int, Field(ge=0, strict=True)]
    failed_deliveries: Annotated[int, Field(ge=0, strict=True)]
    pending_retries: Annotated[int, Field(ge=0, strict=True)]
    success_rate: Annotated[float, Field(ge=0.0, le=1.0, strict=True)]


class StorageDashboardSummary(StrictSchema):
    objects: Annotated[int, Field(ge=0, strict=True)]
    original_bytes: Annotated[int, Field(ge=0, strict=True)]
    artifact_bytes: Annotated[int, Field(ge=0, strict=True)]
    result_bytes: Annotated[int, Field(ge=0, strict=True)]


class DashboardData(StrictSchema):
    generated_at: UTCDateTime
    tasks: TaskDashboardSummary
    workers: WorkerDashboardSummary
    callbacks: CallbackDashboardSummary
    storage: StorageDashboardSummary
    backends: list[BackendMetric] = Field(default_factory=list)
    runtimes: list[RuntimeMetric] = Field(default_factory=list)
    series: list[NamedTimeSeries] = Field(default_factory=list)


DashboardResponse = ApiResponse[DashboardData]


__all__ = [
    "BackendMetric",
    "CallbackDashboardSummary",
    "DashboardData",
    "DashboardQuery",
    "DashboardResponse",
    "MetricInterval",
    "NamedTimeSeries",
    "RuntimeMetric",
    "StorageDashboardSummary",
    "TaskDashboardSummary",
    "TimeSeriesPoint",
    "WorkerDashboardSummary",
]
