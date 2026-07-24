"""Database-backed Stage leasing for heterogeneous pull-based Workers."""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta

from pydantic import TypeAdapter
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ..domain.task_state import require_stage_transition, require_task_transition
from ..persistence.models import (
    BackendRecord,
    StageRecord,
    TaskRecord,
    WorkerRecord,
)
from ..persistence.events import DatabaseEventBus, TransactionalEventPublisher
from ..persistence.registry import backend_detail, mime_patterns_overlap
from ..schema.backend import BackendCapability
from ..persistence.workers import WorkerRepository
from ..schema.error import ErrorCode, ErrorDetail
from ..schema.event import (
    TaskProgressUpdatedEvent,
    TaskStatusChangedEvent,
)
from ..schema.hardware import DeviceRuntime, DeviceUsage
from ..schema.pipeline import RetryPolicy
from ..schema.source import ParseSource, SourceMetadata
from ..schema.stage import StageStatus
from ..schema.task import TaskOptions, TaskStatus
from ..schema.trace import TraceContext
from ..schema.worker import (
    CompleteStageRequest,
    LeasedStage,
    RenewStageLeaseData,
    StageExecutionData,
    StageProgressRequest,
    WorkerLeaseRequest,
    WorkerStatus,
)


_source_adapter = TypeAdapter(ParseSource)


class WorkerUnavailableError(Exception):
    """Worker is missing, disabled, draining, offline, or unhealthy."""


class InvalidLeaseError(Exception):
    """Lease owner or token does not match."""


class LeaseExpiredError(Exception):
    """Lease is no longer valid."""


class StageExecutionConflictError(Exception):
    """Stage is not in the required execution state."""


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _lease_digest(token: str) -> bytes:
    return hashlib.sha256(token.encode("utf-8")).digest()


def _completion_digest(request: CompleteStageRequest) -> bytes:
    payload = json.dumps(
        request.model_dump(mode="json"),
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(payload).digest()


class StageScheduler:
    def __init__(
        self,
        *,
        lease_duration_seconds: int,
        maximum_device_memory_utilization_percent: float = 95.0,
        events: TransactionalEventPublisher | None = None,
    ) -> None:
        if lease_duration_seconds < 1:
            raise ValueError("lease_duration_seconds must be greater than zero")
        if not 0.0 < maximum_device_memory_utilization_percent <= 100.0:
            raise ValueError(
                "maximum_device_memory_utilization_percent must be in (0, 100]"
            )
        self.lease_duration_seconds = lease_duration_seconds
        self.maximum_device_memory_utilization_percent = (
            maximum_device_memory_utilization_percent
        )
        self.events = events or DatabaseEventBus()

    async def lease(
        self,
        session: AsyncSession,
        *,
        request: WorkerLeaseRequest,
        now: datetime,
    ) -> list[LeasedStage]:
        worker = await self._worker_for_update(session, request.worker_id)
        if worker is None or not self._worker_accepts_leases(worker):
            raise WorkerUnavailableError
        active_count = await self._active_stage_count(session, worker.worker_id)
        slots = min(
            request.available_slots,
            max(worker.maximum_concurrency - active_count, 0),
        )
        if slots == 0:
            return []

        worker_capabilities = {
            (capability.name, capability.version): capability
            for capability in WorkerRepository.backend_capabilities(worker)
        }
        candidate_workers = list(
            await session.scalars(
                select(WorkerRecord)
                .where(
                    WorkerRecord.enabled.is_(True),
                    WorkerRecord.status.in_(
                        [
                            WorkerStatus.ONLINE.value,
                            WorkerStatus.BUSY.value,
                        ]
                    ),
                )
                .order_by(WorkerRecord.worker_id)
            )
        )
        candidate_worker_ids = [record.worker_id for record in candidate_workers]
        active_counts = {
            str(worker_id): int(count)
            for worker_id, count in (
                await session.execute(
                    select(StageRecord.worker_id, func.count())
                    .where(
                        StageRecord.worker_id.in_(candidate_worker_ids),
                        StageRecord.status.in_(
                            [
                                StageStatus.LEASED.value,
                                StageStatus.RUNNING.value,
                            ]
                        ),
                    )
                    .group_by(StageRecord.worker_id)
                )
            ).all()
            if worker_id is not None
        }
        active_device_counts = {
            str(device_id): int(count)
            for device_id, count in (
                await session.execute(
                    select(StageRecord.device_id, func.count())
                    .where(
                        StageRecord.worker_id == worker.worker_id,
                        StageRecord.device_id.is_not(None),
                        StageRecord.status.in_(
                            [
                                StageStatus.LEASED.value,
                                StageStatus.RUNNING.value,
                            ]
                        ),
                    )
                    .group_by(StageRecord.device_id)
                )
            ).all()
            if device_id is not None
        }
        pending = list(
            (
                await session.scalars(
                    select(StageRecord)
                    .join(TaskRecord)
                    .where(
                        StageRecord.status == StageStatus.PENDING.value,
                        StageRecord.available_at <= now,
                        TaskRecord.status.in_(
                            [
                                TaskStatus.PENDING.value,
                                TaskStatus.LEASED.value,
                                TaskStatus.RUNNING.value,
                            ]
                        ),
                    )
                    .options(
                        selectinload(StageRecord.task).selectinload(TaskRecord.stages)
                    )
                    .order_by(
                        TaskRecord.priority.desc(),
                        TaskRecord.created_at.asc(),
                        StageRecord.position.asc(),
                    )
                    .with_for_update(skip_locked=True)
                )
            ).unique()
        )

        leases: list[LeasedStage] = []
        backend_cache: dict[str, BackendRecord | None] = {}
        for stage in pending:
            if len(leases) >= slots:
                break
            if not self._dependencies_satisfied(stage):
                continue
            task_options = TaskOptions.model_validate_json(
                json.dumps(stage.task.options_payload)
            )
            if any(
                worker.labels_payload.get(key) != value
                for key, value in task_options.device.worker_labels.items()
            ):
                continue
            worker_runtimes = self._available_worker_runtimes(
                worker,
                minimum_memory_bytes=task_options.device.minimum_memory_bytes,
            )
            selected = await self._select_backend(
                session,
                stage=stage,
                worker_capabilities=worker_capabilities,
                worker_runtimes=worker_runtimes,
                cache=backend_cache,
            )
            if selected is None:
                continue
            if not await self._requesting_worker_is_preferred(
                session,
                stage=stage,
                task_options=task_options,
                requesting_worker=worker,
                requesting_worker_active_count=active_count + len(leases),
                candidate_workers=candidate_workers,
                active_counts=active_counts,
                cache=backend_cache,
            ):
                continue
            backend, runtime = selected
            device_id = self._select_device_id(
                worker,
                runtime=runtime,
                minimum_memory_bytes=task_options.device.minimum_memory_bytes,
                active_counts=active_device_counts,
            )
            if device_id is None:
                continue
            task = stage.task
            if task.source_metadata_payload is None:
                continue

            token = f"lease_{secrets.token_urlsafe(32)}"
            expires_at = now + timedelta(seconds=self.lease_duration_seconds)
            require_stage_transition(StageStatus.PENDING, StageStatus.LEASED)
            stage.status = StageStatus.LEASED.value
            stage.backend_id = backend.backend_id
            stage.backend_version = backend.version
            stage.worker_id = worker.worker_id
            stage.runtime = runtime.value
            stage.device_id = device_id
            active_device_counts[device_id] = active_device_counts.get(device_id, 0) + 1
            stage.attempt += 1
            stage.lease_token_digest = _lease_digest(token)
            stage.completion_worker_id = None
            stage.completion_lease_token_digest = None
            stage.completion_request_digest = None
            stage.lease_expires_at = expires_at
            stage.updated_at = now
            previous_task_status = TaskStatus(task.status)
            if previous_task_status is TaskStatus.PENDING:
                require_task_transition(
                    previous_task_status,
                    TaskStatus.LEASED,
                )
                task.status = TaskStatus.LEASED.value
                task.updated_at = now
                self._task_status_event(
                    session,
                    task_id=task.task_id,
                    previous=previous_task_status,
                    current=TaskStatus.LEASED,
                    now=now,
                )

            detail = backend_detail(backend)
            leases.append(
                LeasedStage(
                    task_id=task.task_id,
                    stage_id=stage.stage_id,
                    stage_name=stage.name,
                    backend_id=backend.backend_id,
                    backend_name=detail.capability.name,
                    backend_version=detail.capability.version,
                    backend_candidates=[
                        str(item) for item in stage.backend_candidates_payload
                    ],
                    runtime=runtime,
                    device_id=device_id,
                    trace_context=(
                        TraceContext.model_validate(task.trace_context_payload)
                        if task.trace_context_payload is not None
                        else None
                    ),
                    source=_source_adapter.validate_json(
                        json.dumps(task.source_payload)
                    ),
                    source_metadata=SourceMetadata.model_validate_json(
                        json.dumps(task.source_metadata_payload)
                    ),
                    task_options=task_options,
                    parameters=stage.parameters,
                    timeout_seconds=stage.timeout_seconds,
                    attempt=stage.attempt,
                    maximum_attempts=stage.maximum_attempts,
                    lease_token=token,
                    lease_expires_at=expires_at,
                )
            )

        if active_count + len(leases) >= worker.maximum_concurrency:
            worker.status = WorkerStatus.BUSY.value
            worker.updated_at = now
        await session.flush()
        return leases

    async def renew(
        self,
        session: AsyncSession,
        *,
        stage_id: str,
        worker_id: str,
        lease_token: str,
        now: datetime,
    ) -> RenewStageLeaseData | None:
        stage = await self._stage_for_update(session, stage_id)
        if stage is None:
            return None
        self._require_valid_lease(
            stage,
            worker_id=worker_id,
            lease_token=lease_token,
            now=now,
        )
        if StageStatus(stage.status) not in {
            StageStatus.LEASED,
            StageStatus.RUNNING,
        }:
            raise StageExecutionConflictError
        expires_at = now + timedelta(seconds=self.lease_duration_seconds)
        stage.lease_expires_at = expires_at
        stage.updated_at = now
        await session.flush()
        return RenewStageLeaseData(
            stage_id=stage.stage_id,
            lease_expires_at=expires_at,
        )

    async def start(
        self,
        session: AsyncSession,
        *,
        stage_id: str,
        worker_id: str,
        lease_token: str,
        now: datetime,
    ) -> StageExecutionData | None:
        stage = await self._stage_for_update(session, stage_id)
        if stage is None:
            return None
        self._require_valid_lease(
            stage,
            worker_id=worker_id,
            lease_token=lease_token,
            now=now,
        )
        current = StageStatus(stage.status)
        if current is not StageStatus.LEASED:
            raise StageExecutionConflictError
        require_stage_transition(current, StageStatus.RUNNING)
        stage.status = StageStatus.RUNNING.value
        stage.started_at = stage.started_at or now
        stage.updated_at = now
        task = stage.task
        task_status = TaskStatus(task.status)
        if task_status is TaskStatus.LEASED:
            require_task_transition(task_status, TaskStatus.RUNNING)
            task.status = TaskStatus.RUNNING.value
            task.started_at = task.started_at or now
            task.updated_at = now
            self._task_status_event(
                session,
                task_id=task.task_id,
                previous=task_status,
                current=TaskStatus.RUNNING,
                now=now,
            )
        await session.flush()
        return self._execution_data(stage)

    async def progress(
        self,
        session: AsyncSession,
        *,
        stage_id: str,
        request: StageProgressRequest,
        now: datetime,
    ) -> StageExecutionData | None:
        stage = await self._stage_for_update(session, stage_id)
        if stage is None:
            return None
        self._require_valid_lease(
            stage,
            worker_id=request.worker_id,
            lease_token=request.lease_token,
            now=now,
        )
        if StageStatus(stage.status) is not StageStatus.RUNNING:
            raise StageExecutionConflictError
        stage.progress_percent = request.progress_percent
        stage.updated_at = now
        self._update_task_progress(stage.task, now=now)
        payload = TaskProgressUpdatedEvent(
            type="task.progress_updated",
            task_id=stage.task_id,
            progress_percent=stage.task.progress_percent,
            stage_id=stage.stage_id,
            stage_status=StageStatus.RUNNING,
        )
        self._add_event(
            session,
            payload=payload,
            now=now,
        )
        await session.flush()
        return self._execution_data(stage)

    async def complete(
        self,
        session: AsyncSession,
        *,
        stage_id: str,
        request: CompleteStageRequest,
        now: datetime,
    ) -> StageExecutionData | None:
        stage = await self._stage_for_update(session, stage_id)
        if stage is None:
            return None
        request_digest = _completion_digest(request)
        lease_digest = _lease_digest(request.lease_token)
        if stage.completion_request_digest is not None:
            if (
                stage.completion_worker_id != request.worker_id
                or stage.completion_lease_token_digest is None
                or not hmac.compare_digest(
                    stage.completion_lease_token_digest,
                    lease_digest,
                )
                or not hmac.compare_digest(
                    stage.completion_request_digest,
                    request_digest,
                )
            ):
                raise StageExecutionConflictError
            return self._execution_data(stage)
        self._require_valid_lease(
            stage,
            worker_id=request.worker_id,
            lease_token=request.lease_token,
            now=now,
        )
        if StageStatus(stage.status) is not StageStatus.RUNNING:
            raise StageExecutionConflictError
        stage.completion_worker_id = request.worker_id
        stage.completion_lease_token_digest = lease_digest
        stage.completion_request_digest = request_digest

        if request.status == "succeeded":
            self._succeed_stage(stage, result_uri=request.result_uri, now=now)
        else:
            self._fail_or_retry_stage(
                stage,
                error=request.error,
                now=now,
            )
        self._reconcile_task(stage.task, now=now, session=session)
        await self._release_worker_if_idle(
            session,
            worker_id=request.worker_id,
            now=now,
        )
        await session.flush()
        return self._execution_data(stage)

    async def authorize_artifact_upload(
        self,
        session: AsyncSession,
        *,
        stage_id: str,
        worker_id: str,
        lease_token: str,
        now: datetime,
    ) -> StageRecord | None:
        stage = await self._stage_for_update(session, stage_id)
        if stage is None:
            return None
        self._require_valid_lease(
            stage,
            worker_id=worker_id,
            lease_token=lease_token,
            now=now,
        )
        if StageStatus(stage.status) not in {
            StageStatus.LEASED,
            StageStatus.RUNNING,
        }:
            raise StageExecutionConflictError
        return stage

    async def requeue_expired(
        self,
        session: AsyncSession,
        *,
        now: datetime,
    ) -> list[str]:
        stages = list(
            (
                await session.scalars(
                    select(StageRecord)
                    .where(
                        StageRecord.status.in_(
                            [
                                StageStatus.LEASED.value,
                                StageStatus.RUNNING.value,
                            ]
                        ),
                        StageRecord.lease_expires_at <= now,
                    )
                    .options(
                        selectinload(StageRecord.task).selectinload(TaskRecord.stages)
                    )
                    .with_for_update(skip_locked=True)
                )
            ).unique()
        )
        affected_workers: set[str] = set()
        for stage in stages:
            if stage.worker_id is not None:
                affected_workers.add(stage.worker_id)
            timeout_error = ErrorDetail(
                code=ErrorCode.TIMEOUT,
                message="The Stage lease expired",
                retryable=stage.attempt < stage.maximum_attempts,
            )
            self._fail_or_retry_stage(stage, error=timeout_error, now=now)
            self._reconcile_task(stage.task, now=now, session=session)
        for worker_id in affected_workers:
            await self._release_worker_if_idle(
                session,
                worker_id=worker_id,
                now=now,
            )
        await session.flush()
        return [stage.stage_id for stage in stages]

    async def _select_backend(
        self,
        session: AsyncSession,
        *,
        stage: StageRecord,
        worker_capabilities: Mapping[tuple[str, str], BackendCapability],
        worker_runtimes: set[DeviceRuntime],
        cache: dict[str, BackendRecord | None],
    ) -> tuple[BackendRecord, DeviceRuntime] | None:
        stage_runtimes = {
            DeviceRuntime(str(item)) for item in stage.required_runtimes_payload
        }
        allowed_runtimes = worker_runtimes & stage_runtimes
        if not allowed_runtimes:
            return None
        for raw_backend_id in stage.backend_candidates_payload:
            backend_id = str(raw_backend_id)
            if backend_id not in cache:
                cache[backend_id] = await session.get(BackendRecord, backend_id)
            backend = cache[backend_id]
            if backend is None or backend.status != "enabled":
                continue
            detail = backend_detail(backend)
            worker_capability = worker_capabilities.get(
                (
                    detail.capability.name,
                    detail.capability.version,
                )
            )
            if worker_capability is None:
                continue
            if stage.task.source_metadata_payload is None:
                continue
            source_metadata = SourceMetadata.model_validate_json(
                json.dumps(stage.task.source_metadata_payload)
            )
            if worker_capability.mime_types:
                if not any(
                    mime_patterns_overlap(pattern, source_metadata.mime_type)
                    for pattern in worker_capability.mime_types
                ):
                    continue
            elif (
                source_metadata.media_category not in worker_capability.media_categories
            ):
                continue
            compatible = [
                DeviceRuntime(str(runtime))
                for runtime in stage.required_runtimes_payload
                if DeviceRuntime(str(runtime)) in detail.capability.runtimes
                and DeviceRuntime(str(runtime)) in allowed_runtimes
                and DeviceRuntime(str(runtime)) in worker_capability.runtimes
            ]
            if compatible:
                return backend, compatible[0]
        return None

    async def _requesting_worker_is_preferred(
        self,
        session: AsyncSession,
        *,
        stage: StageRecord,
        task_options: TaskOptions,
        requesting_worker: WorkerRecord,
        requesting_worker_active_count: int,
        candidate_workers: list[WorkerRecord],
        active_counts: Mapping[str, int],
        cache: dict[str, BackendRecord | None],
    ) -> bool:
        """Select the best currently available compatible pull Worker.

        The database Stage row remains the authority for the eventual claim.
        This ranking is an admission decision: lower-ranked polling Workers
        leave the Stage available for a higher-ranked healthy Worker.
        """

        runtime_order = [
            DeviceRuntime(str(runtime)) for runtime in stage.required_runtimes_payload
        ]
        ranked: list[tuple[int, float, int, int, str]] = []
        for candidate in candidate_workers:
            active_count = (
                requesting_worker_active_count
                if candidate.worker_id == requesting_worker.worker_id
                else active_counts.get(candidate.worker_id, 0)
            )
            if active_count >= candidate.maximum_concurrency:
                continue
            if any(
                candidate.labels_payload.get(key) != value
                for key, value in task_options.device.worker_labels.items()
            ):
                continue
            runtimes = self._available_worker_runtimes(
                candidate,
                minimum_memory_bytes=task_options.device.minimum_memory_bytes,
            )
            compatible_runtimes = runtimes & {
                DeviceRuntime(str(item)) for item in stage.required_runtimes_payload
            }
            capabilities = {
                (capability.name, capability.version): capability
                for capability in WorkerRepository.backend_capabilities(candidate)
            }
            if (
                await self._select_backend(
                    session,
                    stage=stage,
                    worker_capabilities=capabilities,
                    worker_runtimes=runtimes,
                    cache=cache,
                )
                is None
            ):
                continue
            ranked.append(
                (
                    -min(
                        runtime_order.index(runtime) for runtime in compatible_runtimes
                    ),
                    self._worker_scheduling_score(
                        candidate,
                        active_count=active_count,
                        compatible_runtimes=compatible_runtimes,
                        minimum_memory_bytes=task_options.device.minimum_memory_bytes,
                    ),
                    candidate.scheduling_weight,
                    -active_count,
                    candidate.worker_id,
                )
            )
        if not ranked:
            return False
        best_score = max(item[:4] for item in ranked)
        preferred_worker_id = min(item[4] for item in ranked if item[:4] == best_score)
        return preferred_worker_id == requesting_worker.worker_id

    @staticmethod
    def _worker_scheduling_score(
        worker: WorkerRecord,
        *,
        active_count: int,
        compatible_runtimes: set[DeviceRuntime],
        minimum_memory_bytes: int | None,
    ) -> float:
        """Combine configured weight with live capacity and utilization."""

        load_signals = [active_count / worker.maximum_concurrency]
        resources = worker.resource_payload
        if resources is not None:
            cpu_percent = resources.get("cpu_percent")
            if isinstance(cpu_percent, int | float) and not isinstance(
                cpu_percent, bool
            ):
                load_signals.append(float(cpu_percent) / 100.0)
            running = resources.get("running_tasks")
            leased = resources.get("leased_tasks")
            if (
                isinstance(running, int)
                and not isinstance(running, bool)
                and isinstance(leased, int)
                and not isinstance(leased, bool)
            ):
                load_signals.append(
                    min((running + leased) / worker.maximum_concurrency, 1.0)
                )

        devices = WorkerRepository.devices(worker)
        usage_by_device = {
            usage.device_id: usage
            for usage in (
                DeviceUsage.model_validate_json(json.dumps(raw_usage))
                for raw_usage in worker.device_usage_payload
            )
        }
        device_loads: list[float] = []
        for device in devices:
            if device.runtime not in compatible_runtimes:
                continue
            usage = usage_by_device.get(device.device_id)
            total_memory = (
                usage.memory_total_bytes
                if usage is not None and usage.memory_total_bytes is not None
                else device.total_memory_bytes
            )
            used_memory = (
                usage.memory_used_bytes
                if usage is not None and usage.memory_used_bytes is not None
                else 0
            )
            if minimum_memory_bytes is not None and (
                total_memory is None
                or total_memory - used_memory < minimum_memory_bytes
            ):
                continue
            signals = [0.0]
            if usage is None:
                device_loads.append(0.0)
                continue
            if usage.utilization_percent is not None:
                signals.append(usage.utilization_percent / 100.0)
            if total_memory is not None and total_memory > 0:
                signals.append(used_memory / total_memory)
            device_loads.append(max(signals))
        if device_loads:
            # One saturated accelerator must not hide an idle compatible
            # sibling device on the same Worker.
            load_signals.append(min(device_loads))

        load = min(max(load_signals), 1.0)
        capacity_factor = max(1.0 - load, 0.05)
        return worker.scheduling_weight * capacity_factor

    @staticmethod
    def _dependencies_satisfied(stage: StageRecord) -> bool:
        statuses = {item.name: StageStatus(item.status) for item in stage.task.stages}
        return all(
            statuses.get(str(dependency))
            in {StageStatus.SUCCEEDED, StageStatus.SKIPPED}
            for dependency in stage.depends_on_payload
        )

    def _available_worker_runtimes(
        self,
        worker: WorkerRecord,
        *,
        minimum_memory_bytes: int | None,
    ) -> set[DeviceRuntime]:
        devices = WorkerRepository.devices(worker)
        usage_by_id = {
            usage.device_id: usage
            for usage in (
                DeviceUsage.model_validate_json(json.dumps(item))
                for item in worker.device_usage_payload
            )
        }
        available: set[DeviceRuntime] = set()
        for device in devices:
            usage = usage_by_id.get(device.device_id)
            total = (
                usage.memory_total_bytes
                if usage is not None and usage.memory_total_bytes is not None
                else device.total_memory_bytes
            )
            used = (
                usage.memory_used_bytes
                if usage is not None and usage.memory_used_bytes is not None
                else 0
            )
            if (
                total is not None
                and total > 0
                and used / total * 100.0
                >= self.maximum_device_memory_utilization_percent
            ):
                continue
            if minimum_memory_bytes is not None and (
                total is None or total - used < minimum_memory_bytes
            ):
                continue
            available.add(device.runtime)
        return available

    def _select_device_id(
        self,
        worker: WorkerRecord,
        *,
        runtime: DeviceRuntime,
        minimum_memory_bytes: int | None,
        active_counts: Mapping[str, int],
    ) -> str | None:
        """Choose the least-reserved, least-loaded compatible physical device."""

        usage_by_id = {
            usage.device_id: usage
            for usage in (
                DeviceUsage.model_validate_json(json.dumps(item))
                for item in worker.device_usage_payload
            )
        }
        candidates: list[tuple[int, float, str]] = []
        for device in WorkerRepository.devices(worker):
            if device.runtime is not runtime:
                continue
            usage = usage_by_id.get(device.device_id)
            total = (
                usage.memory_total_bytes
                if usage is not None and usage.memory_total_bytes is not None
                else device.total_memory_bytes
            )
            used = (
                usage.memory_used_bytes
                if usage is not None and usage.memory_used_bytes is not None
                else 0
            )
            memory_load = used / total if total is not None and total > 0 else 0.0
            if memory_load * 100.0 >= self.maximum_device_memory_utilization_percent:
                continue
            if minimum_memory_bytes is not None and (
                total is None or total - used < minimum_memory_bytes
            ):
                continue
            utilization_load = (
                usage.utilization_percent / 100.0
                if usage is not None and usage.utilization_percent is not None
                else 0.0
            )
            candidates.append(
                (
                    active_counts.get(device.device_id, 0),
                    max(memory_load, utilization_load),
                    device.device_id,
                )
            )
        return min(candidates)[2] if candidates else None

    async def _worker_for_update(
        self,
        session: AsyncSession,
        worker_id: str,
    ) -> WorkerRecord | None:
        return await session.scalar(
            select(WorkerRecord)
            .where(WorkerRecord.worker_id == worker_id)
            .with_for_update()
        )

    @staticmethod
    def _worker_accepts_leases(worker: WorkerRecord) -> bool:
        return worker.enabled and WorkerStatus(worker.status) in {
            WorkerStatus.ONLINE,
            WorkerStatus.BUSY,
        }

    @staticmethod
    async def _active_stage_count(
        session: AsyncSession,
        worker_id: str,
    ) -> int:
        value = await session.scalar(
            select(func.count())
            .select_from(StageRecord)
            .where(
                StageRecord.worker_id == worker_id,
                StageRecord.status.in_(
                    [StageStatus.LEASED.value, StageStatus.RUNNING.value]
                ),
            )
        )
        return int(value or 0)

    @staticmethod
    async def _stage_for_update(
        session: AsyncSession,
        stage_id: str,
    ) -> StageRecord | None:
        return await session.scalar(
            select(StageRecord)
            .where(StageRecord.stage_id == stage_id)
            .options(selectinload(StageRecord.task).selectinload(TaskRecord.stages))
            .with_for_update()
        )

    @staticmethod
    def _require_valid_lease(
        stage: StageRecord,
        *,
        worker_id: str,
        lease_token: str,
        now: datetime,
    ) -> None:
        candidate = _lease_digest(lease_token)
        if (
            stage.worker_id != worker_id
            or stage.lease_token_digest is None
            or not hmac.compare_digest(stage.lease_token_digest, candidate)
        ):
            raise InvalidLeaseError
        expires_at = _as_utc(stage.lease_expires_at)
        if expires_at is None or expires_at <= now:
            raise LeaseExpiredError

    @staticmethod
    def _succeed_stage(
        stage: StageRecord,
        *,
        result_uri: str | None,
        now: datetime,
    ) -> None:
        require_stage_transition(StageStatus.RUNNING, StageStatus.SUCCEEDED)
        stage.status = StageStatus.SUCCEEDED.value
        stage.progress_percent = 100.0
        stage.result_uri = result_uri
        stage.completed_at = now
        stage.updated_at = now
        StageScheduler._clear_lease(stage)

    @staticmethod
    def _fail_or_retry_stage(
        stage: StageRecord,
        *,
        error: ErrorDetail | None,
        now: datetime,
    ) -> None:
        current = StageStatus(stage.status)
        if current not in {StageStatus.LEASED, StageStatus.RUNNING}:
            raise StageExecutionConflictError
        if stage.attempt < stage.maximum_attempts:
            if current is StageStatus.RUNNING:
                require_stage_transition(current, StageStatus.FAILED)
                require_stage_transition(StageStatus.FAILED, StageStatus.PENDING)
            else:
                require_stage_transition(current, StageStatus.PENDING)
            retry = RetryPolicy.model_validate_json(
                json.dumps(stage.retry_policy_payload)
            )
            delay = min(
                retry.initial_delay_seconds
                * (retry.multiplier ** max(stage.attempt - 1, 0)),
                retry.maximum_delay_seconds,
            )
            stage.status = StageStatus.PENDING.value
            stage.progress_percent = 0.0
            stage.error_payload = None
            stage.started_at = None
            stage.completed_at = None
            stage.available_at = now + timedelta(seconds=delay)
            stage.updated_at = now
            StageScheduler._clear_lease(stage)
            return
        if stage.optional:
            require_stage_transition(current, StageStatus.FAILED)
            require_stage_transition(StageStatus.FAILED, StageStatus.SKIPPED)
            stage.status = StageStatus.SKIPPED.value
            stage.error_payload = None
        else:
            require_stage_transition(current, StageStatus.FAILED)
            stage.status = StageStatus.FAILED.value
            stage.error_payload = (
                error.model_dump(mode="json")
                if error is not None
                else ErrorDetail(
                    code=ErrorCode.INTERNAL_ERROR,
                    message="The Stage failed without error details",
                ).model_dump(mode="json")
            )
        stage.completed_at = now
        stage.updated_at = now
        StageScheduler._clear_lease(stage)

    @staticmethod
    def _clear_lease(stage: StageRecord) -> None:
        stage.worker_id = None
        stage.device_id = None
        stage.lease_token_digest = None
        stage.lease_expires_at = None

    def _reconcile_task(
        self,
        task: TaskRecord,
        *,
        now: datetime,
        session: AsyncSession,
    ) -> None:
        statuses = [StageStatus(stage.status) for stage in task.stages]
        previous = TaskStatus(task.status)
        failed_stage = next(
            (
                stage
                for stage in task.stages
                if StageStatus(stage.status) is StageStatus.FAILED
            ),
            None,
        )
        if failed_stage is not None:
            require_task_transition(previous, TaskStatus.FAILED)
            task.status = TaskStatus.FAILED.value
            task.error_payload = failed_stage.error_payload
            task.completed_at = now
            for other in task.stages:
                if StageStatus(other.status) in {
                    StageStatus.PENDING,
                    StageStatus.LEASED,
                    StageStatus.RUNNING,
                }:
                    other.status = StageStatus.CANCELLED.value
                    other.completed_at = now
                    other.updated_at = now
                    self._clear_lease(other)
        elif statuses and all(
            status in {StageStatus.SUCCEEDED, StageStatus.SKIPPED}
            for status in statuses
        ):
            require_task_transition(previous, TaskStatus.SUCCEEDED)
            task.status = TaskStatus.SUCCEEDED.value
            task.progress_percent = 100.0
            task.completed_at = now
            task.result_uri = next(
                (
                    stage.result_uri
                    for stage in reversed(task.stages)
                    if stage.result_uri is not None
                ),
                None,
            )
        elif previous is TaskStatus.LEASED and all(
            status
            in {
                StageStatus.PENDING,
                StageStatus.SUCCEEDED,
                StageStatus.SKIPPED,
            }
            for status in statuses
        ):
            require_task_transition(previous, TaskStatus.PENDING)
            task.status = TaskStatus.PENDING.value
        self._update_task_progress(task, now=now)
        current = TaskStatus(task.status)
        if current is not previous:
            self._task_status_event(
                session,
                task_id=task.task_id,
                previous=previous,
                current=current,
                now=now,
            )

    @staticmethod
    def _update_task_progress(task: TaskRecord, *, now: datetime) -> None:
        if not task.stages:
            task.progress_percent = 0.0
        else:
            task.progress_percent = sum(
                100.0
                if StageStatus(stage.status)
                in {StageStatus.SUCCEEDED, StageStatus.SKIPPED}
                else stage.progress_percent
                for stage in task.stages
            ) / len(task.stages)
        task.updated_at = now

    async def _release_worker_if_idle(
        self,
        session: AsyncSession,
        *,
        worker_id: str,
        now: datetime,
    ) -> None:
        worker = await self._worker_for_update(session, worker_id)
        if (
            worker is not None
            and worker.enabled
            and WorkerStatus(worker.status) is WorkerStatus.BUSY
            and await self._active_stage_count(session, worker_id) == 0
        ):
            worker.status = WorkerStatus.ONLINE.value
            worker.updated_at = now

    @staticmethod
    def _execution_data(stage: StageRecord) -> StageExecutionData:
        return StageExecutionData(
            task_id=stage.task_id,
            stage_id=stage.stage_id,
            stage_status=StageStatus(stage.status),
            task_status=TaskStatus(stage.task.status),
            progress_percent=stage.task.progress_percent,
            lease_expires_at=_as_utc(stage.lease_expires_at),
        )

    def _task_status_event(
        self,
        session: AsyncSession,
        *,
        task_id: str,
        previous: TaskStatus,
        current: TaskStatus,
        now: datetime,
    ) -> None:
        payload = TaskStatusChangedEvent(
            type="task.status_changed",
            task_id=task_id,
            previous_status=previous,
            current_status=current,
        )
        self._add_event(
            session,
            payload=payload,
            now=now,
        )

    def _add_event(
        self,
        session: AsyncSession,
        *,
        payload: TaskProgressUpdatedEvent | TaskStatusChangedEvent,
        now: datetime,
    ) -> None:
        self.events.publish(session, payload=payload, now=now)


__all__ = [
    "InvalidLeaseError",
    "LeaseExpiredError",
    "StageExecutionConflictError",
    "StageScheduler",
    "WorkerUnavailableError",
]
