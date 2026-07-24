"""Portable dashboard aggregation over control-plane persistence."""

from __future__ import annotations

import json
import math
from collections import Counter, defaultdict
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..persistence.models import (
    ArtifactRecord,
    CallbackDeliveryRecord,
    StageRecord,
    TaskRecord,
    UploadedFileRecord,
    WorkerRecord,
)
from ..schema.artifact import ArtifactType
from ..schema.callback import CallbackDeliveryStatus
from ..schema.dashboard import (
    BackendMetric,
    CallbackDashboardSummary,
    DashboardData,
    DashboardQuery,
    MetricInterval,
    NamedTimeSeries,
    RuntimeMetric,
    StorageDashboardSummary,
    TaskDashboardSummary,
    TimeSeriesPoint,
    WorkerDashboardSummary,
)
from ..schema.hardware import DeviceInfo, DeviceRuntime, DeviceUsage
from ..schema.stage import StageStatus
from ..schema.task import TaskStatus
from ..schema.worker import WorkerResourceUsage, WorkerStatus


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _duration_ms(start: datetime | None, end: datetime | None) -> float | None:
    if start is None or end is None:
        return None
    return max((_utc(end) - _utc(start)).total_seconds() * 1000.0, 0.0)


def _average(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _percentile(values: list[float], percentile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    position = (len(ordered) - 1) * percentile
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def _interval_seconds(interval: MetricInterval) -> int:
    return {
        MetricInterval.MINUTE: 60,
        MetricInterval.FIVE_MINUTES: 300,
        MetricInterval.HOUR: 3600,
        MetricInterval.DAY: 86_400,
    }[interval]


def _bucket(value: datetime, *, origin: datetime, seconds: int) -> datetime:
    offset = max((_utc(value) - origin).total_seconds(), 0.0)
    return origin + timedelta(seconds=math.floor(offset / seconds) * seconds)


class DashboardService:
    async def summary(
        self,
        session: AsyncSession,
        *,
        query: DashboardQuery,
        generated_at: datetime,
    ) -> DashboardData:
        tasks = await self._tasks(session, query)
        stages = await self._stages(session, query)
        workers = await self._workers(session, query)
        callbacks = await self._callbacks(session, query)
        artifacts = await self._artifacts(session, query)
        uploaded_files = list(
            await session.scalars(
                select(UploadedFileRecord).where(
                    UploadedFileRecord.created_at >= query.start_time,
                    UploadedFileRecord.created_at < query.end_time,
                )
            )
        )
        return DashboardData(
            generated_at=generated_at,
            tasks=self._task_summary(tasks),
            workers=self._worker_summary(workers),
            callbacks=self._callback_summary(callbacks),
            storage=self._storage_summary(uploaded_files, artifacts),
            backends=self._backend_metrics(stages),
            runtimes=self._runtime_metrics(workers),
            series=self._task_series(tasks, query),
        )

    @staticmethod
    async def _tasks(
        session: AsyncSession,
        query: DashboardQuery,
    ) -> list[TaskRecord]:
        statement = select(TaskRecord).where(
            TaskRecord.created_at >= query.start_time,
            TaskRecord.created_at < query.end_time,
            TaskRecord.task_id.in_(_filtered_task_ids(query)),
        )
        return list(await session.scalars(statement))

    @staticmethod
    async def _stages(
        session: AsyncSession,
        query: DashboardQuery,
    ) -> list[StageRecord]:
        occurred_at = func.coalesce(StageRecord.started_at, StageRecord.created_at)
        statement = select(StageRecord).where(
            StageRecord.task_id.in_(_filtered_task_ids(query)),
            occurred_at >= query.start_time,
            occurred_at < query.end_time,
        )
        if query.backend_id is not None:
            statement = statement.where(StageRecord.backend_id == query.backend_id)
        if query.worker_id is not None:
            statement = statement.where(StageRecord.worker_id == query.worker_id)
        if query.runtime is not None:
            statement = statement.where(StageRecord.runtime == query.runtime.value)
        return list(await session.scalars(statement))

    @staticmethod
    async def _workers(
        session: AsyncSession,
        query: DashboardQuery,
    ) -> list[WorkerRecord]:
        statement = select(WorkerRecord)
        if query.worker_id is not None:
            statement = statement.where(WorkerRecord.worker_id == query.worker_id)
        workers = list(await session.scalars(statement))
        if query.runtime is None:
            return workers
        return [
            worker
            for worker in workers
            if query.runtime in {device.runtime for device in _worker_devices(worker)}
        ]

    @staticmethod
    async def _callbacks(
        session: AsyncSession,
        query: DashboardQuery,
    ) -> list[CallbackDeliveryRecord]:
        return list(
            await session.scalars(
                select(CallbackDeliveryRecord).where(
                    CallbackDeliveryRecord.task_id.in_(_filtered_task_ids(query)),
                    CallbackDeliveryRecord.created_at >= query.start_time,
                    CallbackDeliveryRecord.created_at < query.end_time,
                )
            )
        )

    @staticmethod
    async def _artifacts(
        session: AsyncSession,
        query: DashboardQuery,
    ) -> list[ArtifactRecord]:
        return list(
            await session.scalars(
                select(ArtifactRecord).where(
                    ArtifactRecord.task_id.in_(_filtered_task_ids(query)),
                    ArtifactRecord.created_at >= query.start_time,
                    ArtifactRecord.created_at < query.end_time,
                )
            )
        )

    @staticmethod
    def _task_summary(tasks: list[TaskRecord]) -> TaskDashboardSummary:
        counts = Counter(task.status for task in tasks)
        waits = [
            value
            for task in tasks
            if (value := _duration_ms(task.created_at, task.started_at)) is not None
        ]
        executions = [
            value
            for task in tasks
            if (value := _duration_ms(task.started_at, task.completed_at)) is not None
        ]
        succeeded = counts[TaskStatus.SUCCEEDED.value]
        return TaskDashboardSummary(
            total_tasks=len(tasks),
            pending_tasks=counts[TaskStatus.PENDING.value],
            running_tasks=(
                counts[TaskStatus.LEASED.value] + counts[TaskStatus.RUNNING.value]
            ),
            succeeded_tasks=succeeded,
            failed_tasks=counts[TaskStatus.FAILED.value],
            cancelled_tasks=counts[TaskStatus.CANCELLED.value],
            success_rate=succeeded / len(tasks) if tasks else 0.0,
            average_wait_ms=_average(waits),
            average_execution_ms=_average(executions),
            p50_execution_ms=_percentile(executions, 0.50),
            p95_execution_ms=_percentile(executions, 0.95),
            p99_execution_ms=_percentile(executions, 0.99),
        )

    @staticmethod
    def _worker_summary(workers: list[WorkerRecord]) -> WorkerDashboardSummary:
        counts = Counter(worker.status for worker in workers)
        total_concurrency = sum(worker.maximum_concurrency for worker in workers)
        used = 0
        for worker in workers:
            if worker.resource_payload is None:
                continue
            resources = WorkerResourceUsage.model_validate(worker.resource_payload)
            used += resources.running_tasks
        return WorkerDashboardSummary(
            total_workers=len(workers),
            online_workers=counts[WorkerStatus.ONLINE.value],
            busy_workers=counts[WorkerStatus.BUSY.value],
            draining_workers=counts[WorkerStatus.DRAINING.value],
            offline_workers=counts[WorkerStatus.OFFLINE.value],
            unhealthy_workers=counts[WorkerStatus.UNHEALTHY.value],
            total_concurrency=total_concurrency,
            used_concurrency=min(used, total_concurrency),
        )

    @staticmethod
    def _callback_summary(
        deliveries: list[CallbackDeliveryRecord],
    ) -> CallbackDashboardSummary:
        counts = Counter(delivery.status for delivery in deliveries)
        succeeded = counts[CallbackDeliveryStatus.SUCCEEDED.value]
        return CallbackDashboardSummary(
            total_deliveries=len(deliveries),
            successful_deliveries=succeeded,
            failed_deliveries=counts[CallbackDeliveryStatus.FAILED.value],
            pending_retries=sum(
                counts[status.value]
                for status in (
                    CallbackDeliveryStatus.PENDING,
                    CallbackDeliveryStatus.DELIVERING,
                    CallbackDeliveryStatus.RETRY_WAIT,
                )
            ),
            success_rate=succeeded / len(deliveries) if deliveries else 0.0,
        )

    @staticmethod
    def _storage_summary(
        uploads: list[UploadedFileRecord],
        artifacts: list[ArtifactRecord],
    ) -> StorageDashboardSummary:
        result_types = {
            ArtifactType.RESULT_JSON.value,
            ArtifactType.RESULT_TEXT.value,
            ArtifactType.RESULT_MARKDOWN.value,
        }
        return StorageDashboardSummary(
            objects=len(uploads) + len(artifacts),
            original_bytes=sum(item.size_bytes for item in uploads),
            artifact_bytes=sum(
                item.size_bytes
                for item in artifacts
                if item.artifact_type not in result_types
            ),
            result_bytes=sum(
                item.size_bytes
                for item in artifacts
                if item.artifact_type in result_types
            ),
        )

    @staticmethod
    def _backend_metrics(stages: list[StageRecord]) -> list[BackendMetric]:
        grouped: dict[str, list[StageRecord]] = defaultdict(list)
        for stage in stages:
            if stage.backend_id is not None and stage.attempt > 0:
                grouped[stage.backend_id].append(stage)
        metrics = []
        for backend_id, records in sorted(grouped.items()):
            durations = [
                value
                for stage in records
                if (value := _duration_ms(stage.started_at, stage.completed_at))
                is not None
            ]
            metrics.append(
                BackendMetric(
                    backend_id=backend_id,
                    calls=sum(stage.attempt for stage in records),
                    failures=sum(
                        stage.status == StageStatus.FAILED.value for stage in records
                    ),
                    timeouts=sum(
                        isinstance(stage.error_payload, dict)
                        and stage.error_payload.get("code") == "TIMEOUT"
                        for stage in records
                    ),
                    fallbacks=sum(
                        bool(stage.backend_candidates_payload)
                        and str(stage.backend_candidates_payload[0]) != backend_id
                        for stage in records
                    ),
                    average_duration_ms=_average(durations),
                )
            )
        return metrics

    @staticmethod
    def _runtime_metrics(workers: list[WorkerRecord]) -> list[RuntimeMetric]:
        worker_ids: dict[DeviceRuntime, set[str]] = defaultdict(set)
        device_counts: Counter[DeviceRuntime] = Counter()
        utilizations: dict[DeviceRuntime, list[float]] = defaultdict(list)
        memory_used: Counter[DeviceRuntime] = Counter()
        memory_total: Counter[DeviceRuntime] = Counter()
        has_memory: set[DeviceRuntime] = set()
        for worker in workers:
            devices = {device.device_id: device for device in _worker_devices(worker)}
            usage = {
                item.device_id: item
                for item in (
                    DeviceUsage.model_validate(payload)
                    for payload in worker.device_usage_payload
                )
            }
            for device_id, device in devices.items():
                worker_ids[device.runtime].add(worker.worker_id)
                device_counts[device.runtime] += 1
                current = usage.get(device_id)
                if current is not None and current.utilization_percent is not None:
                    utilizations[device.runtime].append(current.utilization_percent)
                used = current.memory_used_bytes if current is not None else None
                total = (
                    current.memory_total_bytes if current is not None else None
                ) or device.total_memory_bytes
                if used is not None and total is not None:
                    memory_used[device.runtime] += used
                    memory_total[device.runtime] += total
                    has_memory.add(device.runtime)
        return [
            RuntimeMetric(
                runtime=runtime,
                workers=len(worker_ids[runtime]),
                devices=device_counts[runtime],
                average_utilization_percent=(
                    _average(utilizations[runtime]) if utilizations[runtime] else None
                ),
                memory_used_bytes=(
                    memory_used[runtime] if runtime in has_memory else None
                ),
                memory_total_bytes=(
                    memory_total[runtime] if runtime in has_memory else None
                ),
            )
            for runtime in sorted(worker_ids, key=lambda item: item.value)
        ]

    @staticmethod
    def _task_series(
        tasks: list[TaskRecord],
        query: DashboardQuery,
    ) -> list[NamedTimeSeries]:
        seconds = _interval_seconds(query.interval)
        start = _utc(query.start_time)
        end = _utc(query.end_time)
        bucket_count = math.ceil((end - start).total_seconds() / seconds)
        timestamps = [
            start + timedelta(seconds=index * seconds) for index in range(bucket_count)
        ]
        submitted: Counter[datetime] = Counter()
        succeeded: Counter[datetime] = Counter()
        failed: Counter[datetime] = Counter()
        for task in tasks:
            submitted[_bucket(task.created_at, origin=start, seconds=seconds)] += 1
            if task.status is not None and task.completed_at is not None:
                target = (
                    succeeded
                    if task.status == TaskStatus.SUCCEEDED.value
                    else failed
                    if task.status == TaskStatus.FAILED.value
                    else None
                )
                if target is not None and _utc(task.completed_at) < end:
                    target[
                        _bucket(task.completed_at, origin=start, seconds=seconds)
                    ] += 1
        return [
            NamedTimeSeries(
                name=name,
                unit="tasks",
                points=[
                    TimeSeriesPoint(timestamp=timestamp, value=float(values[timestamp]))
                    for timestamp in timestamps
                ],
            )
            for name, values in (
                ("submitted", submitted),
                ("succeeded", succeeded),
                ("failed", failed),
            )
        ]


def _worker_devices(worker: WorkerRecord) -> list[DeviceInfo]:
    return [
        DeviceInfo.model_validate_json(json.dumps(payload))
        for payload in worker.devices_payload
    ]


def _filtered_task_ids(query: DashboardQuery):
    statement = select(TaskRecord.task_id)
    if query.pipeline_id is not None:
        statement = statement.where(TaskRecord.pipeline_id == query.pipeline_id)
    if query.media_category is not None:
        statement = statement.where(
            TaskRecord.media_category == query.media_category.value
        )
    stage_filters = []
    if query.backend_id is not None:
        stage_filters.append(StageRecord.backend_id == query.backend_id)
    if query.worker_id is not None:
        stage_filters.append(StageRecord.worker_id == query.worker_id)
    if query.runtime is not None:
        stage_filters.append(StageRecord.runtime == query.runtime.value)
    if stage_filters:
        statement = statement.where(
            TaskRecord.task_id.in_(select(StageRecord.task_id).where(*stage_filters))
        )
    return statement


__all__ = ["DashboardService"]
