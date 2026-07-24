"""Persistent event querying and SSE cursor support."""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Protocol
from uuid import uuid4

from pydantic import TypeAdapter
from sqlalchemy import Select, and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..schema.event import (
    EventEnvelope,
    EventListQuery,
    EventPayload,
    EventSortField,
    EventStreamQuery,
)
from .models import EventRecord


_payload_adapter = TypeAdapter(EventPayload)


def event_envelope(record: EventRecord) -> EventEnvelope:
    occurred_at = record.occurred_at
    if occurred_at.tzinfo is None:
        occurred_at = occurred_at.replace(tzinfo=UTC)
    return EventEnvelope(
        schema_version="1.0",
        event_id=record.event_id,
        occurred_at=occurred_at,
        payload=_payload_adapter.validate_json(json.dumps(record.payload)),
    )


class EventRepository:
    """Backward-compatible database event consumer."""

    async def get(
        self,
        session: AsyncSession,
        event_id: str,
    ) -> EventRecord | None:
        return await session.get(EventRecord, event_id)

    async def list(
        self,
        session: AsyncSession,
        *,
        query: EventListQuery | EventStreamQuery,
        limit: int | None = None,
    ) -> list[EventRecord]:
        statement: Select[tuple[EventRecord]] = select(EventRecord)
        if query.types:
            statement = statement.where(EventRecord.event_type.in_(query.types))
        if query.task_id is not None:
            statement = statement.where(EventRecord.task_id == query.task_id)
        if query.worker_id is not None:
            statement = statement.where(EventRecord.worker_id == query.worker_id)
        sort_column = EventRecord.occurred_at
        ascending = True
        if isinstance(query, EventListQuery):
            sort_column = {
                EventSortField.OCCURRED_AT: EventRecord.occurred_at,
                EventSortField.TYPE: EventRecord.event_type,
            }[query.sort_by]
            ascending = query.sort_direction.value == "asc"
        if query.last_event_id is not None:
            cursor = await self.get(session, query.last_event_id)
            if cursor is None:
                return []
            cursor_value = (
                cursor.occurred_at
                if not isinstance(query, EventListQuery)
                or query.sort_by is EventSortField.OCCURRED_AT
                else cursor.event_type
            )
            comparison = (
                sort_column > cursor_value if ascending else sort_column < cursor_value
            )
            id_comparison = (
                EventRecord.event_id > cursor.event_id
                if ascending
                else EventRecord.event_id < cursor.event_id
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
        resolved_limit = limit
        if resolved_limit is None and isinstance(query, EventListQuery):
            resolved_limit = query.limit
        if resolved_limit is not None:
            statement = statement.limit(resolved_limit)
        ordering = (
            (sort_column.asc(), EventRecord.event_id.asc())
            if ascending
            else (sort_column.desc(), EventRecord.event_id.desc())
        )
        return list(await session.scalars(statement.order_by(*ordering)))

    async def consume(
        self,
        session: AsyncSession,
        *,
        query: EventListQuery | EventStreamQuery,
        limit: int | None = None,
    ) -> list[EventRecord]:
        return await self.list(session, query=query, limit=limit)


class TransactionalEventPublisher(Protocol):
    def publish(
        self,
        session: AsyncSession,
        *,
        payload: EventPayload,
        now: datetime,
    ) -> EventRecord: ...


class EventConsumer(Protocol):
    async def consume(
        self,
        session: AsyncSession,
        *,
        query: EventListQuery | EventStreamQuery,
        limit: int | None = None,
    ) -> list[EventRecord]: ...


class DatabaseEventBus(EventRepository):
    """Transactional outbox publisher and cursor-based database consumer."""

    def __init__(
        self,
        *,
        event_id_factory: Callable[[], str] | None = None,
    ) -> None:
        self.event_id_factory = event_id_factory or (lambda: f"event_{uuid4().hex}")

    def publish(
        self,
        session: AsyncSession,
        *,
        payload: EventPayload,
        now: datetime,
    ) -> EventRecord:
        record = EventRecord(
            event_id=self.event_id_factory(),
            event_type=payload.type,
            task_id=getattr(payload, "task_id", None),
            worker_id=getattr(payload, "worker_id", None),
            payload=payload.model_dump(mode="json"),
            occurred_at=now,
        )
        session.add(record)
        return record


__all__ = [
    "DatabaseEventBus",
    "EventConsumer",
    "EventRepository",
    "TransactionalEventPublisher",
    "event_envelope",
]
