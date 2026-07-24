"""Prometheus process and persistent control-plane metrics."""

from __future__ import annotations

from prometheus_client import (
    CollectorRegistry,
    Counter,
    Gauge,
    Histogram,
    generate_latest,
)
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..persistence.models import (
    ArtifactRecord,
    CallbackAttemptRecord,
    CallbackDeliveryRecord,
    StageRecord,
    TaskRecord,
    UploadedFileRecord,
    WorkerRecord,
)
from ..schema.worker import WorkerResourceUsage


class ParserMetrics:
    def __init__(self) -> None:
        self.registry = CollectorRegistry()
        self.http_requests = Counter(
            "parser_http_requests_total",
            "HTTP requests completed by this control-plane process.",
            ("method", "route", "status_code"),
            registry=self.registry,
        )
        self.http_duration = Histogram(
            "parser_http_request_duration_seconds",
            "HTTP request duration observed by this control-plane process.",
            ("method", "route"),
            registry=self.registry,
            buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10),
        )
        self.tasks = Gauge(
            "parser_task_records",
            "Persistent Task records by current status.",
            ("status",),
            registry=self.registry,
        )
        self.stages = Gauge(
            "parser_stage_records",
            "Persistent Stage records by current status.",
            ("status",),
            registry=self.registry,
        )
        self.workers = Gauge(
            "parser_worker_records",
            "Persistent Worker records by current status.",
            ("status",),
            registry=self.registry,
        )
        self.callbacks = Gauge(
            "parser_callback_deliveries",
            "Persistent callback deliveries by current status.",
            ("status",),
            registry=self.registry,
        )
        self.callback_attempts = Gauge(
            "parser_callback_attempt_records",
            "Persistent callback delivery attempts.",
            registry=self.registry,
        )
        self.backend_attempts = Gauge(
            "parser_backend_stage_attempts",
            "Accumulated Stage attempts by Backend ID.",
            ("backend_id",),
            registry=self.registry,
        )
        self.storage_bytes = Gauge(
            "parser_storage_bytes",
            "Persistent object bytes represented in metadata.",
            ("kind",),
            registry=self.registry,
        )
        self.worker_concurrency = Gauge(
            "parser_worker_concurrency",
            "Worker concurrency slots.",
            ("kind",),
            registry=self.registry,
        )

    def observe_http(
        self,
        *,
        method: str,
        route: str,
        status_code: int,
        duration_seconds: float,
    ) -> None:
        labels = (method, route)
        self.http_requests.labels(*labels, str(status_code)).inc()
        self.http_duration.labels(*labels).observe(max(duration_seconds, 0.0))

    async def update_persistent(self, session: AsyncSession) -> None:
        await self._status_gauge(session, TaskRecord, self.tasks)
        await self._status_gauge(session, StageRecord, self.stages)
        await self._status_gauge(session, WorkerRecord, self.workers)
        await self._status_gauge(session, CallbackDeliveryRecord, self.callbacks)

        attempts = await session.scalar(
            select(func.count()).select_from(CallbackAttemptRecord)
        )
        self.callback_attempts.set(attempts or 0)

        self.backend_attempts.clear()
        backend_rows = await session.execute(
            select(
                StageRecord.backend_id,
                func.sum(StageRecord.attempt),
            )
            .where(StageRecord.backend_id.is_not(None))
            .group_by(StageRecord.backend_id)
        )
        for backend_id, attempt_count in backend_rows:
            if backend_id is not None:
                self.backend_attempts.labels(backend_id).set(attempt_count or 0)

        upload_bytes = await session.scalar(
            select(func.coalesce(func.sum(UploadedFileRecord.size_bytes), 0))
        )
        artifact_bytes = await session.scalar(
            select(func.coalesce(func.sum(ArtifactRecord.size_bytes), 0))
        )
        self.storage_bytes.labels("upload").set(upload_bytes or 0)
        self.storage_bytes.labels("artifact").set(artifact_bytes or 0)

        workers = list(await session.scalars(select(WorkerRecord)))
        total_slots = sum(worker.maximum_concurrency for worker in workers)
        used_slots = sum(_used_slots(worker) for worker in workers)
        self.worker_concurrency.labels("total").set(total_slots)
        self.worker_concurrency.labels("used").set(min(used_slots, total_slots))

    @staticmethod
    async def _status_gauge(
        session: AsyncSession,
        model: type[TaskRecord]
        | type[StageRecord]
        | type[WorkerRecord]
        | type[CallbackDeliveryRecord],
        gauge: Gauge,
    ) -> None:
        gauge.clear()
        rows = await session.execute(
            select(model.status, func.count()).group_by(model.status)
        )
        for status, count in rows.tuples():
            gauge.labels(status).set(count)

    def render(self) -> bytes:
        return generate_latest(self.registry)


def _used_slots(worker: WorkerRecord) -> int:
    if worker.resource_payload is None:
        return 0
    return WorkerResourceUsage.model_validate(worker.resource_payload).running_tasks


__all__ = ["ParserMetrics"]
