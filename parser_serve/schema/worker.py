"""Worker registration, heartbeat, and capability contracts."""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Literal

from pydantic import Field, model_validator

from .backend import BackendCapability
from .base import JsonValue, StrictSchema
from .common import (
    ApiResponse,
    BackendId,
    ListResponse,
    NonEmptyStr,
    Percent,
    StageId,
    StrictBool,
    TaskId,
    UTCDateTime,
    WorkerId,
)
from .error import ErrorDetail
from .hardware import DeviceInfo, DeviceRuntime, DeviceUsage
from .source import ParseSource, SourceMetadata
from .stage import StageStatus
from .task import TaskOptions, TaskStatus
from .trace import TraceContext


class WorkerStatus(StrEnum):
    ONLINE = "online"
    BUSY = "busy"
    DRAINING = "draining"
    OFFLINE = "offline"
    UNHEALTHY = "unhealthy"


class WorkerRegistrationRequest(StrictSchema):
    worker_id: WorkerId
    name: NonEmptyStr
    version: NonEmptyStr
    hostname: NonEmptyStr
    devices: Annotated[list[DeviceInfo], Field(min_length=1)]
    # A hardware bring-up Worker may register before its first Backend adapter
    # is enabled. With no capabilities it remains observable but cannot lease
    # parsing stages.
    backends: list[BackendCapability] = Field(default_factory=list)
    labels: dict[NonEmptyStr, NonEmptyStr] = Field(default_factory=dict)
    maximum_concurrency: Annotated[int, Field(ge=1, strict=True)]

    @model_validator(mode="after")
    def validate_registration(self) -> WorkerRegistrationRequest:
        device_ids = [device.device_id for device in self.devices]
        if len(device_ids) != len(set(device_ids)):
            raise ValueError("device IDs must be unique")
        backend_keys = [(backend.name, backend.version) for backend in self.backends]
        if len(backend_keys) != len(set(backend_keys)):
            raise ValueError("backend name and version pairs must be unique")
        device_runtimes = {device.runtime for device in self.devices}
        unsupported = {
            runtime
            for backend in self.backends
            for runtime in backend.runtimes
            if runtime not in device_runtimes
        }
        if unsupported:
            names = ", ".join(sorted(runtime.value for runtime in unsupported))
            raise ValueError(f"backend runtimes need matching devices: {names}")
        return self


class WorkerRegistrationData(StrictSchema):
    worker_id: WorkerId
    accepted: StrictBool
    heartbeat_interval_seconds: Annotated[int, Field(ge=1, strict=True)]
    lease_duration_seconds: Annotated[int, Field(ge=1, strict=True)]
    registered_at: UTCDateTime


WorkerRegistrationResponse = ApiResponse[WorkerRegistrationData]


class WorkerHealthCheck(StrictSchema):
    name: NonEmptyStr
    healthy: StrictBool
    message: NonEmptyStr | None = None

    @model_validator(mode="after")
    def validate_message(self) -> WorkerHealthCheck:
        if self.healthy and self.message is not None:
            raise ValueError("healthy checks must not include an error message")
        if not self.healthy and self.message is None:
            raise ValueError("unhealthy checks require an error message")
        return self


class WorkerResourceUsage(StrictSchema):
    cpu_percent: Annotated[float, Field(ge=0.0, le=100.0, strict=True)]
    memory_used_bytes: Annotated[int, Field(ge=0, strict=True)]
    memory_total_bytes: Annotated[int, Field(ge=0, strict=True)]
    running_tasks: Annotated[int, Field(ge=0, strict=True)]
    leased_tasks: Annotated[int, Field(ge=0, strict=True)]
    health_checks: list[WorkerHealthCheck] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_memory(self) -> WorkerResourceUsage:
        if self.memory_used_bytes > self.memory_total_bytes:
            raise ValueError("memory_used_bytes cannot exceed memory_total_bytes")
        names = [check.name for check in self.health_checks]
        if len(names) != len(set(names)):
            raise ValueError("health check names must be unique")
        return self


class WorkerHeartbeatRequest(StrictSchema):
    worker_id: WorkerId
    sequence: Annotated[int, Field(ge=0, strict=True)]
    status: WorkerStatus
    resources: WorkerResourceUsage
    devices: list[DeviceUsage] = Field(default_factory=list)
    timestamp: UTCDateTime

    @model_validator(mode="after")
    def validate_device_usage(self) -> WorkerHeartbeatRequest:
        device_ids = [device.device_id for device in self.devices]
        if len(device_ids) != len(set(device_ids)):
            raise ValueError("heartbeat device usage IDs must be unique")
        if (
            any(not check.healthy for check in self.resources.health_checks)
            and self.status is not WorkerStatus.UNHEALTHY
        ):
            raise ValueError("failed health checks require unhealthy Worker status")
        return self


class WorkerHeartbeatData(StrictSchema):
    accepted: StrictBool
    next_heartbeat_seconds: Annotated[int, Field(ge=1, strict=True)]
    should_drain: StrictBool = False


WorkerHeartbeatResponse = ApiResponse[WorkerHeartbeatData]


class WorkerDetail(StrictSchema):
    worker_id: WorkerId
    name: NonEmptyStr
    version: NonEmptyStr
    hostname: NonEmptyStr
    status: WorkerStatus
    enabled: StrictBool
    maximum_concurrency: Annotated[int, Field(ge=1, strict=True)]
    scheduling_weight: Annotated[int, Field(ge=1, le=1000, strict=True)]
    devices: list[DeviceInfo]
    device_usage: list[DeviceUsage] = Field(default_factory=list)
    backends: list[BackendCapability]
    labels: dict[NonEmptyStr, NonEmptyStr] = Field(default_factory=dict)
    resources: WorkerResourceUsage | None = None
    last_heartbeat_at: UTCDateTime | None = None
    created_at: UTCDateTime
    updated_at: UTCDateTime

    @model_validator(mode="after")
    def validate_timestamps(self) -> WorkerDetail:
        if self.updated_at < self.created_at:
            raise ValueError("updated_at cannot be earlier than created_at")
        if (
            self.last_heartbeat_at is not None
            and self.last_heartbeat_at < self.created_at
        ):
            raise ValueError("last_heartbeat_at cannot be earlier than created_at")
        return self


WorkerDetailResponse = ApiResponse[WorkerDetail]
WorkerListResponse = ListResponse[WorkerDetail]


LeaseToken = Annotated[
    str,
    Field(
        pattern=r"^lease_[a-zA-Z0-9_-]{32,128}$",
        strict=True,
    ),
]


class WorkerLeaseRequest(StrictSchema):
    worker_id: WorkerId
    available_slots: Annotated[int, Field(ge=1, le=100, strict=True)]
    wait_seconds: Annotated[float, Field(ge=0.0, le=30.0, strict=True)] = 0.0


class LeasedStage(StrictSchema):
    task_id: TaskId
    stage_id: StageId
    stage_name: NonEmptyStr
    backend_id: BackendId
    backend_name: NonEmptyStr
    backend_version: NonEmptyStr
    backend_candidates: list[BackendId]
    runtime: DeviceRuntime
    device_id: NonEmptyStr | None = None
    trace_context: TraceContext | None = None
    source: ParseSource
    source_metadata: SourceMetadata
    task_options: TaskOptions
    parameters: dict[str, JsonValue] = Field(default_factory=dict)
    timeout_seconds: Annotated[int, Field(ge=1, le=86_400, strict=True)]
    attempt: Annotated[int, Field(ge=1, strict=True)]
    maximum_attempts: Annotated[int, Field(ge=1, le=20, strict=True)]
    lease_token: LeaseToken
    lease_expires_at: UTCDateTime


class WorkerLeaseData(StrictSchema):
    leases: list[LeasedStage] = Field(default_factory=list)


WorkerLeaseResponse = ApiResponse[WorkerLeaseData]


class RenewStageLeaseRequest(StrictSchema):
    worker_id: WorkerId
    lease_token: LeaseToken


class RenewStageLeaseData(StrictSchema):
    stage_id: StageId
    lease_expires_at: UTCDateTime


RenewStageLeaseResponse = ApiResponse[RenewStageLeaseData]


class StartStageRequest(StrictSchema):
    worker_id: WorkerId
    lease_token: LeaseToken


class StageProgressRequest(StrictSchema):
    worker_id: WorkerId
    lease_token: LeaseToken
    progress_percent: Percent


class CompleteStageRequest(StrictSchema):
    worker_id: WorkerId
    lease_token: LeaseToken
    status: Literal["succeeded", "failed"]
    result_uri: NonEmptyStr | None = None
    error: ErrorDetail | None = None

    @model_validator(mode="after")
    def validate_completion(self) -> CompleteStageRequest:
        if self.status == "failed" and self.error is None:
            raise ValueError("failed stage completion requires error")
        if self.status == "succeeded" and self.error is not None:
            raise ValueError("successful stage completion cannot contain error")
        return self


class StageExecutionData(StrictSchema):
    task_id: TaskId
    stage_id: StageId
    stage_status: StageStatus
    task_status: TaskStatus
    progress_percent: Percent
    lease_expires_at: UTCDateTime | None = None


StageExecutionResponse = ApiResponse[StageExecutionData]


class WorkerReconcileData(StrictSchema):
    offline_worker_ids: list[WorkerId] = Field(default_factory=list)
    requeued_stage_ids: list[StageId] = Field(default_factory=list)


WorkerReconcileResponse = ApiResponse[WorkerReconcileData]


__all__ = [
    "BackendCapability",
    "WorkerHeartbeatData",
    "WorkerHeartbeatRequest",
    "WorkerHeartbeatResponse",
    "WorkerHealthCheck",
    "WorkerDetail",
    "WorkerDetailResponse",
    "WorkerLeaseData",
    "WorkerLeaseRequest",
    "WorkerLeaseResponse",
    "WorkerListResponse",
    "WorkerReconcileData",
    "WorkerReconcileResponse",
    "LeasedStage",
    "LeaseToken",
    "RenewStageLeaseData",
    "RenewStageLeaseRequest",
    "RenewStageLeaseResponse",
    "StartStageRequest",
    "StageExecutionData",
    "StageExecutionResponse",
    "StageProgressRequest",
    "CompleteStageRequest",
    "WorkerRegistrationData",
    "WorkerRegistrationRequest",
    "WorkerRegistrationResponse",
    "WorkerResourceUsage",
    "WorkerStatus",
]
