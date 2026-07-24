"""Worker registration, heartbeat, health, and management persistence."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..schema.event import WorkerStatusChangedEvent
from ..schema.hardware import DeviceInfo
from ..schema.management import (
    UpdateWorkerRequest,
    WorkerListQuery,
    WorkerSortField,
)
from ..schema.worker import (
    BackendCapability,
    WorkerDetail,
    WorkerHeartbeatRequest,
    WorkerRegistrationRequest,
    WorkerStatus,
)
from .events import DatabaseEventBus, TransactionalEventPublisher
from .models import WorkerRecord


class StaleHeartbeatError(Exception):
    """Heartbeat sequence is not newer than the stored sequence."""


class UnknownHeartbeatDeviceError(Exception):
    """Heartbeat usage references a device not declared at registration."""


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _required_utc(value: datetime) -> datetime:
    return _as_utc(value) or value.replace(tzinfo=UTC)


def worker_detail(record: WorkerRecord) -> WorkerDetail:
    return WorkerDetail.model_validate_json(
        json.dumps(
            {
                "worker_id": record.worker_id,
                "name": record.name,
                "version": record.version,
                "hostname": record.hostname,
                "status": record.status,
                "enabled": record.enabled,
                "maximum_concurrency": record.maximum_concurrency,
                "scheduling_weight": record.scheduling_weight,
                "devices": record.devices_payload,
                "device_usage": record.device_usage_payload,
                "backends": record.backends_payload,
                "labels": record.labels_payload,
                "resources": record.resource_payload,
                "last_heartbeat_at": (
                    _required_utc(record.last_heartbeat_at).isoformat()
                    if record.last_heartbeat_at is not None
                    else None
                ),
                "created_at": _required_utc(record.created_at).isoformat(),
                "updated_at": _required_utc(record.updated_at).isoformat(),
            }
        )
    )


class WorkerRepository:
    def __init__(
        self,
        *,
        events: TransactionalEventPublisher | None = None,
    ) -> None:
        self.events = events or DatabaseEventBus()

    async def register(
        self,
        session: AsyncSession,
        *,
        request: WorkerRegistrationRequest,
        now: datetime,
    ) -> WorkerRecord:
        record = await session.scalar(
            select(WorkerRecord)
            .where(WorkerRecord.worker_id == request.worker_id)
            .with_for_update()
        )
        previous_status: WorkerStatus | None = None
        if record is None:
            record = WorkerRecord(
                worker_id=request.worker_id,
                name=request.name,
                version=request.version,
                hostname=request.hostname,
                status=WorkerStatus.ONLINE.value,
                enabled=True,
                maximum_concurrency=request.maximum_concurrency,
                scheduling_weight=100,
                devices_payload=[
                    item.model_dump(mode="json") for item in request.devices
                ],
                device_usage_payload=[],
                backends_payload=[
                    item.model_dump(mode="json") for item in request.backends
                ],
                labels_payload=dict(request.labels),
                heartbeat_sequence=-1,
                last_heartbeat_at=now,
                created_at=now,
                updated_at=now,
            )
            session.add(record)
        else:
            previous_status = WorkerStatus(record.status)
            record.name = request.name
            record.version = request.version
            record.hostname = request.hostname
            record.status = (
                WorkerStatus.ONLINE.value
                if record.enabled
                else WorkerStatus.OFFLINE.value
            )
            record.maximum_concurrency = request.maximum_concurrency
            record.devices_payload = [
                item.model_dump(mode="json") for item in request.devices
            ]
            record.device_usage_payload = []
            record.backends_payload = [
                item.model_dump(mode="json") for item in request.backends
            ]
            record.labels_payload = dict(request.labels)
            record.heartbeat_sequence = -1
            record.last_heartbeat_at = now
            record.updated_at = now
        current_status = WorkerStatus(record.status)
        if previous_status is not current_status:
            self._status_event(
                session,
                worker_id=record.worker_id,
                previous=previous_status,
                current=current_status,
                now=now,
            )
        await session.flush()
        return record

    async def heartbeat(
        self,
        session: AsyncSession,
        *,
        request: WorkerHeartbeatRequest,
        now: datetime,
    ) -> WorkerRecord | None:
        record = await session.scalar(
            select(WorkerRecord)
            .where(WorkerRecord.worker_id == request.worker_id)
            .with_for_update()
        )
        if record is None:
            return None
        if request.sequence <= record.heartbeat_sequence:
            raise StaleHeartbeatError
        registered_device_ids = {
            str(item["device_id"])
            for item in record.devices_payload
            if isinstance(item, dict) and "device_id" in item
        }
        if any(
            usage.device_id not in registered_device_ids for usage in request.devices
        ):
            raise UnknownHeartbeatDeviceError
        previous = WorkerStatus(record.status)
        current = request.status if record.enabled else WorkerStatus.OFFLINE
        record.status = current.value
        record.heartbeat_sequence = request.sequence
        record.resource_payload = request.resources.model_dump(mode="json")
        record.device_usage_payload = [
            usage.model_dump(mode="json") for usage in request.devices
        ]
        record.last_heartbeat_at = now
        record.updated_at = now
        if previous is not current:
            self._status_event(
                session,
                worker_id=record.worker_id,
                previous=previous,
                current=current,
                now=now,
            )
        await session.flush()
        return record

    async def get(
        self,
        session: AsyncSession,
        worker_id: str,
    ) -> WorkerRecord | None:
        return await session.get(WorkerRecord, worker_id)

    async def list(
        self,
        session: AsyncSession,
        *,
        query: WorkerListQuery,
        cursor_value: datetime | str | None = None,
        cursor_worker_id: str | None = None,
    ) -> list[WorkerRecord]:
        statement = select(WorkerRecord)
        if query.statuses:
            statement = statement.where(
                WorkerRecord.status.in_([status.value for status in query.statuses])
            )
        if query.name_contains is not None:
            escaped = (
                query.name_contains.replace("\\", "\\\\")
                .replace("%", "\\%")
                .replace("_", "\\_")
            )
            statement = statement.where(
                WorkerRecord.name.ilike(f"%{escaped}%", escape="\\")
            )
        sort_column = {
            WorkerSortField.CREATED_AT: WorkerRecord.created_at,
            WorkerSortField.UPDATED_AT: WorkerRecord.updated_at,
            WorkerSortField.NAME: WorkerRecord.name,
        }[query.sort_by]
        if cursor_value is not None and cursor_worker_id is not None:
            comparison = (
                sort_column > cursor_value
                if query.sort_direction.value == "asc"
                else sort_column < cursor_value
            )
            id_comparison = (
                WorkerRecord.worker_id > cursor_worker_id
                if query.sort_direction.value == "asc"
                else WorkerRecord.worker_id < cursor_worker_id
            )
            statement = statement.where(
                or_(
                    comparison,
                    and_(
                        sort_column == cursor_value,
                        id_comparison,
                    ),
                )
            )
        ordering = (
            (sort_column.asc(), WorkerRecord.worker_id.asc())
            if query.sort_direction.value == "asc"
            else (sort_column.desc(), WorkerRecord.worker_id.desc())
        )
        records = list((await session.scalars(statement.order_by(*ordering))).all())
        filtered = [
            record for record in records if self._matches_worker(record, query=query)
        ]
        return filtered[: query.limit + 1]

    async def update(
        self,
        session: AsyncSession,
        *,
        worker_id: str,
        update: UpdateWorkerRequest,
        now: datetime,
    ) -> WorkerRecord | None:
        record = await session.scalar(
            select(WorkerRecord)
            .where(WorkerRecord.worker_id == worker_id)
            .with_for_update()
        )
        if record is None:
            return None
        previous = WorkerStatus(record.status)
        if update.enabled is not None:
            record.enabled = update.enabled
            if not update.enabled:
                record.status = WorkerStatus.OFFLINE.value
            elif previous is WorkerStatus.OFFLINE:
                record.status = WorkerStatus.ONLINE.value
        if update.draining is not None:
            if update.draining:
                record.status = WorkerStatus.DRAINING.value
            elif record.enabled and record.status == WorkerStatus.DRAINING.value:
                record.status = WorkerStatus.ONLINE.value
        if update.maximum_concurrency is not None:
            record.maximum_concurrency = update.maximum_concurrency
        if update.scheduling_weight is not None:
            record.scheduling_weight = update.scheduling_weight
        if update.labels is not None:
            record.labels_payload = dict(update.labels)
        record.updated_at = now
        current = WorkerStatus(record.status)
        if current is not previous:
            self._status_event(
                session,
                worker_id=worker_id,
                previous=previous,
                current=current,
                now=now,
            )
        await session.flush()
        return record

    async def mark_offline(
        self,
        session: AsyncSession,
        *,
        now: datetime,
        offline_after_seconds: int,
    ) -> list[str]:
        cutoff = now - timedelta(seconds=offline_after_seconds)
        records = list(
            (
                await session.scalars(
                    select(WorkerRecord)
                    .where(
                        WorkerRecord.status.in_(
                            [
                                WorkerStatus.ONLINE.value,
                                WorkerStatus.BUSY.value,
                            ]
                        ),
                        WorkerRecord.last_heartbeat_at < cutoff,
                    )
                    .with_for_update(skip_locked=True)
                )
            ).all()
        )
        for record in records:
            previous = WorkerStatus(record.status)
            record.status = WorkerStatus.OFFLINE.value
            record.updated_at = now
            self._status_event(
                session,
                worker_id=record.worker_id,
                previous=previous,
                current=WorkerStatus.OFFLINE,
                now=now,
            )
        await session.flush()
        return [record.worker_id for record in records]

    @staticmethod
    def _matches_worker(
        record: WorkerRecord,
        *,
        query: WorkerListQuery,
    ) -> bool:
        if query.labels and any(
            record.labels_payload.get(key) != value
            for key, value in query.labels.items()
        ):
            return False
        if query.runtimes:
            devices = [
                DeviceInfo.model_validate_json(json.dumps(item))
                for item in record.devices_payload
            ]
            if not set(query.runtimes) & {device.runtime for device in devices}:
                return False
        return True

    @staticmethod
    def backend_capabilities(record: WorkerRecord) -> list[BackendCapability]:
        return [
            BackendCapability.model_validate_json(json.dumps(item))
            for item in record.backends_payload
        ]

    @staticmethod
    def devices(record: WorkerRecord) -> list[DeviceInfo]:
        return [
            DeviceInfo.model_validate_json(json.dumps(item))
            for item in record.devices_payload
        ]

    def _status_event(
        self,
        session: AsyncSession,
        *,
        worker_id: str,
        previous: WorkerStatus | None,
        current: WorkerStatus,
        now: datetime,
    ) -> None:
        payload = WorkerStatusChangedEvent(
            type="worker.status_changed",
            worker_id=worker_id,
            previous_status=previous,
            current_status=current,
        )
        self.events.publish(session, payload=payload, now=now)


__all__ = [
    "StaleHeartbeatError",
    "UnknownHeartbeatDeviceError",
    "WorkerRepository",
    "worker_detail",
]
