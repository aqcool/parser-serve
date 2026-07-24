"""Callback outbox materialization and delivery state persistence."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from pydantic import HttpUrl
from sqlalchemy import Select, and_, exists, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..schema.callback import (
    CallbackAttempt,
    CallbackAttemptListQuery,
    CallbackAttemptSortField,
    CallbackConfig,
    CallbackDeliveryDetail,
    CallbackDeliveryStatus,
    CallbackEvent,
    CallbackEventType,
    CallbackListQuery,
    CallbackSortField,
    TaskCancelledCallback,
    TaskCreatedCallback,
    TaskFailedCallback,
    TaskProgressCallback,
    TaskRunningCallback,
    TaskSucceededCallback,
)
from ..schema.error import ErrorDetail
from ..schema.event import (
    CallbackDeliveryChangedEvent,
    TaskProgressUpdatedEvent,
    TaskStatusChangedEvent,
)
from ..schema.task import TaskStatus
from .events import DatabaseEventBus, TransactionalEventPublisher
from .models import (
    CallbackAttemptRecord,
    CallbackDeliveryRecord,
    EventRecord,
    TaskRecord,
)


class CallbackNotRetryableError(Exception):
    """A delivery is currently active or has not reached a retryable state."""


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def callback_delivery_detail(
    record: CallbackDeliveryRecord,
) -> CallbackDeliveryDetail:
    return CallbackDeliveryDetail(
        delivery_id=record.delivery_id,
        event=CallbackEvent.model_validate_json(json.dumps(record.event_payload)),
        target_url=HttpUrl(record.target_url),
        status=CallbackDeliveryStatus(record.status),
        attempt=record.attempt,
        total_attempts=record.attempt_sequence,
        maximum_attempts=record.maximum_attempts,
        response_status_code=record.response_status_code,
        response_summary=record.response_summary,
        next_attempt_at=(
            _utc(record.next_attempt_at) if record.next_attempt_at is not None else None
        ),
        created_at=_utc(record.created_at),
        updated_at=_utc(record.updated_at),
    )


def callback_attempt_detail(record: CallbackAttemptRecord) -> CallbackAttempt:
    return CallbackAttempt(
        attempt_id=record.attempt_id,
        delivery_id=record.delivery_id,
        sequence=record.sequence,
        attempt_number=record.attempt_number,
        delivered=record.delivered,
        response_status_code=record.response_status_code,
        response_summary=record.response_summary,
        duration_ms=record.duration_ms,
        error=(
            ErrorDetail.model_validate_json(json.dumps(record.error_payload))
            if record.error_payload is not None
            else None
        ),
        started_at=_utc(record.started_at),
        completed_at=_utc(record.completed_at),
    )


def _callback_event(
    event: EventRecord,
    task: TaskRecord,
    config: CallbackConfig,
) -> tuple[CallbackEventType, CallbackEvent] | None:
    occurred_at = _utc(event.occurred_at)
    payload_type = event.event_type
    callback_type: CallbackEventType
    payload: (
        TaskCreatedCallback
        | TaskRunningCallback
        | TaskProgressCallback
        | TaskSucceededCallback
        | TaskFailedCallback
        | TaskCancelledCallback
    )
    if payload_type == "task.created":
        callback_type = CallbackEventType.TASK_CREATED
        payload = TaskCreatedCallback(type="task.created", created_at=occurred_at)
    elif payload_type == "task.progress_updated":
        progress_event = TaskProgressUpdatedEvent.model_validate(event.payload)
        callback_type = CallbackEventType.TASK_PROGRESS
        payload = TaskProgressCallback(
            type="task.progress",
            progress_percent=progress_event.progress_percent,
            stage_id=progress_event.stage_id,
            updated_at=occurred_at,
        )
    elif payload_type == "task.status_changed":
        status_event = TaskStatusChangedEvent.model_validate(event.payload)
        current = status_event.current_status
        if current is TaskStatus.RUNNING:
            callback_type = CallbackEventType.TASK_RUNNING
            payload = TaskRunningCallback(
                type="task.running",
                started_at=_utc(task.started_at or occurred_at),
            )
        elif current is TaskStatus.SUCCEEDED:
            callback_type = CallbackEventType.TASK_SUCCEEDED
            payload = TaskSucceededCallback(
                type="task.succeeded",
                result_uri=task.result_uri,
                completed_at=_utc(task.completed_at or occurred_at),
            )
        elif current is TaskStatus.FAILED:
            if task.error_payload is None:
                return None
            callback_type = CallbackEventType.TASK_FAILED
            payload = TaskFailedCallback(
                type="task.failed",
                error=ErrorDetail.model_validate_json(json.dumps(task.error_payload)),
                failed_at=_utc(task.completed_at or occurred_at),
            )
        elif current is TaskStatus.CANCELLED:
            callback_type = CallbackEventType.TASK_CANCELLED
            payload = TaskCancelledCallback(
                type="task.cancelled",
                cancelled_at=_utc(task.completed_at or occurred_at),
            )
        else:
            return None
    else:
        return None
    if callback_type not in config.events:
        return None
    return (
        callback_type,
        CallbackEvent(
            schema_version="1.0",
            event_id=event.event_id,
            task_id=task.task_id,
            occurred_at=occurred_at,
            payload=payload,
        ),
    )


class CallbackRepository:
    def __init__(
        self,
        *,
        events: TransactionalEventPublisher | None = None,
    ) -> None:
        self.events = events or DatabaseEventBus()

    async def materialize(
        self,
        session: AsyncSession,
        *,
        now: datetime,
        maximum_attempts: int,
        limit: int = 500,
    ) -> list[CallbackDeliveryRecord]:
        statement = (
            select(EventRecord)
            .where(
                EventRecord.task_id.is_not(None),
                EventRecord.callback_processed.is_(False),
                EventRecord.event_type.in_(
                    [
                        "task.created",
                        "task.status_changed",
                        "task.progress_updated",
                    ]
                ),
                ~exists(
                    select(CallbackDeliveryRecord.delivery_id).where(
                        CallbackDeliveryRecord.event_id == EventRecord.event_id
                    )
                ),
            )
            .order_by(EventRecord.occurred_at, EventRecord.event_id)
            .limit(limit)
        )
        events = list(await session.scalars(statement))
        created: list[CallbackDeliveryRecord] = []
        task_cache: dict[str, TaskRecord | None] = {}
        for event in events:
            event.callback_processed = True
            if event.task_id is None:
                continue
            if event.task_id not in task_cache:
                task_cache[event.task_id] = await session.get(
                    TaskRecord,
                    event.task_id,
                )
            task = task_cache[event.task_id]
            if task is None or task.callback_payload is None:
                continue
            config = CallbackConfig.model_validate_json(
                json.dumps(task.callback_payload)
            )
            mapped = _callback_event(event, task, config)
            if mapped is None:
                continue
            callback_type, callback_event = mapped
            record = CallbackDeliveryRecord(
                delivery_id=f"delivery_{uuid4().hex}",
                event_id=event.event_id,
                event_type=callback_type.value,
                task_id=task.task_id,
                target_url=str(config.url),
                status=CallbackDeliveryStatus.PENDING.value,
                attempt=0,
                attempt_sequence=0,
                maximum_attempts=maximum_attempts,
                event_payload=callback_event.model_dump(mode="json"),
                created_at=now,
                updated_at=now,
            )
            session.add(record)
            self._status_event(session, record, now=now)
            created.append(record)
        await session.flush()
        return created

    async def get(
        self,
        session: AsyncSession,
        delivery_id: str,
    ) -> CallbackDeliveryRecord | None:
        return await session.get(CallbackDeliveryRecord, delivery_id)

    async def list(
        self,
        session: AsyncSession,
        *,
        query: CallbackListQuery,
        cursor_value: datetime | str | None = None,
        cursor_delivery_id: str | None = None,
    ) -> list[CallbackDeliveryRecord]:
        statement: Select[tuple[CallbackDeliveryRecord]] = select(
            CallbackDeliveryRecord
        )
        if query.statuses:
            statement = statement.where(
                CallbackDeliveryRecord.status.in_(
                    [status.value for status in query.statuses]
                )
            )
        if query.task_id is not None:
            statement = statement.where(CallbackDeliveryRecord.task_id == query.task_id)
        if query.event_types:
            statement = statement.where(
                CallbackDeliveryRecord.event_type.in_(
                    [event.value for event in query.event_types]
                )
            )
        if query.created_after is not None:
            statement = statement.where(
                CallbackDeliveryRecord.created_at >= query.created_after
            )
        if query.created_before is not None:
            statement = statement.where(
                CallbackDeliveryRecord.created_at <= query.created_before
            )
        sort_column = {
            CallbackSortField.CREATED_AT: CallbackDeliveryRecord.created_at,
            CallbackSortField.UPDATED_AT: CallbackDeliveryRecord.updated_at,
            CallbackSortField.STATUS: CallbackDeliveryRecord.status,
        }[query.sort_by]
        if cursor_value is not None and cursor_delivery_id is not None:
            comparison = (
                sort_column > cursor_value
                if query.sort_direction.value == "asc"
                else sort_column < cursor_value
            )
            id_comparison = (
                CallbackDeliveryRecord.delivery_id > cursor_delivery_id
                if query.sort_direction.value == "asc"
                else CallbackDeliveryRecord.delivery_id < cursor_delivery_id
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
            (sort_column.asc(), CallbackDeliveryRecord.delivery_id.asc())
            if query.sort_direction.value == "asc"
            else (sort_column.desc(), CallbackDeliveryRecord.delivery_id.desc())
        )
        return list(
            await session.scalars(statement.order_by(*ordering).limit(query.limit + 1))
        )

    async def list_attempts(
        self,
        session: AsyncSession,
        *,
        delivery_id: str,
        query: CallbackAttemptListQuery,
        cursor_value: datetime | int | None = None,
        cursor_sequence: int | None = None,
    ) -> list[CallbackAttemptRecord]:
        statement = select(CallbackAttemptRecord).where(
            CallbackAttemptRecord.delivery_id == delivery_id
        )
        if query.delivered is not None:
            statement = statement.where(
                CallbackAttemptRecord.delivered.is_(query.delivered)
            )
        sort_column = {
            CallbackAttemptSortField.SEQUENCE: CallbackAttemptRecord.sequence,
            CallbackAttemptSortField.STARTED_AT: CallbackAttemptRecord.started_at,
            CallbackAttemptSortField.DURATION_MS: CallbackAttemptRecord.duration_ms,
        }[query.sort_by]
        if cursor_value is not None and cursor_sequence is not None:
            comparison = (
                sort_column > cursor_value
                if query.sort_direction.value == "asc"
                else sort_column < cursor_value
            )
            sequence_comparison = (
                CallbackAttemptRecord.sequence > cursor_sequence
                if query.sort_direction.value == "asc"
                else CallbackAttemptRecord.sequence < cursor_sequence
            )
            statement = statement.where(
                or_(
                    comparison,
                    and_(
                        sort_column == cursor_value,
                        sequence_comparison,
                    ),
                )
            )
        ordering = (
            (sort_column.asc(), CallbackAttemptRecord.sequence.asc())
            if query.sort_direction.value == "asc"
            else (sort_column.desc(), CallbackAttemptRecord.sequence.desc())
        )
        return list(
            await session.scalars(statement.order_by(*ordering).limit(query.limit + 1))
        )

    async def claim_due(
        self,
        session: AsyncSession,
        *,
        now: datetime,
        claim_timeout_seconds: float,
    ) -> CallbackDeliveryRecord | None:
        stale_before = now - timedelta(seconds=claim_timeout_seconds)
        exhausted = await session.scalar(
            select(CallbackDeliveryRecord)
            .where(
                CallbackDeliveryRecord.status
                == CallbackDeliveryStatus.DELIVERING.value,
                CallbackDeliveryRecord.updated_at <= stale_before,
                CallbackDeliveryRecord.attempt
                >= CallbackDeliveryRecord.maximum_attempts,
            )
            .order_by(
                CallbackDeliveryRecord.created_at,
                CallbackDeliveryRecord.delivery_id,
            )
            .with_for_update(skip_locked=True)
        )
        if exhausted is not None:
            exhausted.status = CallbackDeliveryStatus.FAILED.value
            exhausted.response_summary = (
                exhausted.response_summary
                or "Callback claim expired after the final attempt"
            )
            exhausted.updated_at = now
            self._status_event(session, exhausted, now=now)
        record = await session.scalar(
            select(CallbackDeliveryRecord)
            .where(
                or_(
                    CallbackDeliveryRecord.status
                    == CallbackDeliveryStatus.PENDING.value,
                    and_(
                        CallbackDeliveryRecord.status
                        == CallbackDeliveryStatus.RETRY_WAIT.value,
                        CallbackDeliveryRecord.next_attempt_at <= now,
                    ),
                    and_(
                        CallbackDeliveryRecord.status
                        == CallbackDeliveryStatus.DELIVERING.value,
                        CallbackDeliveryRecord.updated_at <= stale_before,
                        CallbackDeliveryRecord.attempt
                        < CallbackDeliveryRecord.maximum_attempts,
                    ),
                )
            )
            .order_by(
                CallbackDeliveryRecord.created_at,
                CallbackDeliveryRecord.delivery_id,
            )
            .with_for_update(skip_locked=True)
        )
        if record is None:
            return None
        record.status = CallbackDeliveryStatus.DELIVERING.value
        record.attempt += 1
        record.attempt_sequence += 1
        record.next_attempt_at = None
        record.updated_at = now
        self._status_event(session, record, now=now)
        await session.flush()
        return record

    async def callback_config(
        self,
        session: AsyncSession,
        task_id: str,
    ) -> CallbackConfig | None:
        task = await session.get(TaskRecord, task_id)
        if task is None or task.callback_payload is None:
            return None
        return CallbackConfig.model_validate_json(json.dumps(task.callback_payload))

    async def record_result(
        self,
        session: AsyncSession,
        *,
        delivery_id: str,
        sequence: int,
        attempt_number: int,
        delivered: bool,
        retryable: bool,
        response_status_code: int | None,
        response_summary: str | None,
        duration_ms: int,
        error: ErrorDetail | None,
        now: datetime,
        initial_retry_seconds: float,
        maximum_retry_seconds: float,
    ) -> CallbackDeliveryRecord | None:
        record = await session.scalar(
            select(CallbackDeliveryRecord)
            .where(CallbackDeliveryRecord.delivery_id == delivery_id)
            .with_for_update()
        )
        if record is None:
            return None
        session.add(
            CallbackAttemptRecord(
                attempt_id=f"attempt_{uuid4().hex}",
                delivery_id=delivery_id,
                sequence=sequence,
                attempt_number=attempt_number,
                delivered=delivered,
                response_status_code=response_status_code,
                response_summary=response_summary,
                duration_ms=duration_ms,
                error_payload=error.model_dump(mode="json") if error else None,
                started_at=now,
                completed_at=now + timedelta(milliseconds=duration_ms),
            )
        )
        if record.attempt_sequence != sequence:
            await session.flush()
            return record
        record.response_status_code = response_status_code
        record.response_summary = response_summary
        if delivered:
            record.status = CallbackDeliveryStatus.SUCCEEDED.value
            record.next_attempt_at = None
        elif retryable and record.attempt < record.maximum_attempts:
            delay = min(
                initial_retry_seconds * (2 ** max(record.attempt - 1, 0)),
                maximum_retry_seconds,
            )
            record.status = CallbackDeliveryStatus.RETRY_WAIT.value
            record.next_attempt_at = now + timedelta(seconds=delay)
        else:
            record.status = CallbackDeliveryStatus.FAILED.value
            record.next_attempt_at = None
        record.updated_at = now
        self._status_event(session, record, now=now)
        await session.flush()
        return record

    async def retry(
        self,
        session: AsyncSession,
        *,
        delivery_id: str,
        now: datetime,
    ) -> CallbackDeliveryRecord | None:
        record = await session.scalar(
            select(CallbackDeliveryRecord)
            .where(CallbackDeliveryRecord.delivery_id == delivery_id)
            .with_for_update()
        )
        if record is None:
            return None
        if CallbackDeliveryStatus(record.status) not in {
            CallbackDeliveryStatus.FAILED,
            CallbackDeliveryStatus.CANCELLED,
            CallbackDeliveryStatus.SUCCEEDED,
        }:
            raise CallbackNotRetryableError
        record.status = CallbackDeliveryStatus.PENDING.value
        record.attempt = 0
        record.response_status_code = None
        record.response_summary = None
        record.next_attempt_at = None
        record.updated_at = now
        self._status_event(session, record, now=now)
        await session.flush()
        return record

    def _status_event(
        self,
        session: AsyncSession,
        record: CallbackDeliveryRecord,
        *,
        now: datetime,
    ) -> None:
        payload = CallbackDeliveryChangedEvent(
            type="callback.delivery_changed",
            delivery_id=record.delivery_id,
            task_id=record.task_id,
            status=CallbackDeliveryStatus(record.status),
        )
        self.events.publish(session, payload=payload, now=now)


__all__ = [
    "CallbackNotRetryableError",
    "CallbackRepository",
    "callback_attempt_detail",
    "callback_delivery_detail",
]
