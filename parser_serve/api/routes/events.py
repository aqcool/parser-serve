"""Persistent JSON event queries and resumable SSE streams."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import APIRouter, Depends, Header, Path, Query, Request
from sqlalchemy.exc import SQLAlchemyError
from starlette.responses import StreamingResponse

from ...persistence import Database, DatabaseEventBus
from ...persistence.events import event_envelope
from ...schema.common import EventId, PageInfo, SortDirection, TaskId, WorkerId
from ...schema.error import ErrorCode, ErrorResponse
from ...schema.event import (
    EventEnvelope,
    EventListQuery,
    EventListResponse,
    EventSortField,
    EventStreamQuery,
)
from ..authentication import require_api_key
from ..errors import ApiError
from ..request_id import request_id_for


router = APIRouter(
    prefix="/api/v1",
    tags=["events"],
    dependencies=[Depends(require_api_key)],
)
logger = logging.getLogger(__name__)

_stream_responses: dict[int | str, dict[str, object]] = {
    200: {
        "description": "Server-Sent Events stream",
        "content": {"text/event-stream": {"schema": {"type": "string"}}},
    },
    404: {"model": ErrorResponse},
}


def _database(request: Request) -> Database:
    database: Database | None = request.app.state.database
    if database is None:
        raise ApiError(
            status_code=503,
            code=ErrorCode.DEPENDENCY_UNAVAILABLE,
            message="The event database is not configured",
            retryable=True,
        )
    return database


def _event_bus(request: Request) -> DatabaseEventBus:
    return request.app.state.event_bus


def event_list_query(
    types: Annotated[list[str] | None, Query()] = None,
    task_filter: Annotated[TaskId | None, Query(alias="task_id")] = None,
    worker_filter: Annotated[WorkerId | None, Query(alias="worker_id")] = None,
    last_event_id: Annotated[EventId | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    sort_by: Annotated[EventSortField, Query()] = EventSortField.OCCURRED_AT,
    sort_direction: Annotated[SortDirection, Query()] = SortDirection.ASC,
) -> EventListQuery:
    return EventListQuery(
        types=types or [],
        task_id=task_filter,
        worker_id=worker_filter,
        last_event_id=last_event_id,
        limit=limit,
        sort_by=sort_by,
        sort_direction=sort_direction,
    )


def event_stream_query(
    types: Annotated[list[str] | None, Query()] = None,
    task_filter: Annotated[TaskId | None, Query(alias="task_id")] = None,
    worker_filter: Annotated[WorkerId | None, Query(alias="worker_id")] = None,
    last_event_id: Annotated[EventId | None, Query()] = None,
) -> EventStreamQuery:
    return EventStreamQuery(
        types=types or [],
        task_id=task_filter,
        worker_id=worker_filter,
        last_event_id=last_event_id,
    )


async def _list_events(
    request: Request,
    query: EventListQuery,
) -> EventListResponse:
    try:
        async with _database(request).session_factory() as session:
            records = await _event_bus(request).consume(
                session,
                query=query,
                limit=query.limit + 1,
            )
    except SQLAlchemyError as exc:
        raise ApiError(
            status_code=503,
            code=ErrorCode.DEPENDENCY_UNAVAILABLE,
            message="The event database is unavailable",
            retryable=True,
        ) from exc
    has_more = len(records) > query.limit
    selected = records[: query.limit]
    return EventListResponse(
        request_id=request_id_for(request),
        items=[event_envelope(record) for record in selected],
        page=PageInfo(
            has_more=has_more,
            next_cursor=selected[-1].event_id if has_more and selected else None,
        ),
    )


@router.get(
    "/events",
    operation_id="list_events",
    response_model=EventListResponse,
)
async def list_events(
    request: Request,
    query: Annotated[EventListQuery, Depends(event_list_query)],
) -> EventListResponse:
    return await _list_events(request, query)


@router.get(
    "/tasks/{task_id}/events",
    operation_id="list_task_events",
    response_model=EventListResponse,
)
async def list_task_events(
    request: Request,
    task_id: Annotated[TaskId, Path()],
    query: Annotated[EventListQuery, Depends(event_list_query)],
) -> EventListResponse:
    return await _list_events(
        request,
        query.model_copy(update={"task_id": task_id}),
    )


async def _validate_last_event(
    request: Request,
    event_id: str | None,
) -> None:
    if event_id is None:
        return
    try:
        async with _database(request).session_factory() as session:
            record = await _event_bus(request).get(session, event_id)
    except SQLAlchemyError as exc:
        raise ApiError(
            status_code=503,
            code=ErrorCode.DEPENDENCY_UNAVAILABLE,
            message="The event database is unavailable",
            retryable=True,
        ) from exc
    if record is None:
        raise ApiError(
            status_code=404,
            code=ErrorCode.NOT_FOUND,
            message="Last-Event-ID does not exist or has expired",
        )


def _last_event_id(
    query_value: str | None,
    header_value: str | None,
) -> str | None:
    if (
        query_value is not None
        and header_value is not None
        and query_value != header_value
    ):
        raise ApiError(
            status_code=422,
            code=ErrorCode.VALIDATION_ERROR,
            message="Last-Event-ID header and query parameter do not match",
        )
    return header_value or query_value


async def _stream(
    request: Request,
    query: EventStreamQuery,
) -> AsyncIterator[str]:
    current = query.last_event_id
    last_activity = request.app.state.clock()
    send_started = request.app.state.clock()
    yield "retry: 3000\n\n"
    if (
        request.app.state.clock() - send_started
    ).total_seconds() > request.app.state.settings.sse_maximum_send_delay_seconds:
        logger.warning("sse_slow_consumer_closed", extra={"last_event_id": current})
        return
    while not await request.is_disconnected():
        poll_query = query.model_copy(update={"last_event_id": current})
        async with _database(request).session_factory() as session:
            records = await _event_bus(request).consume(
                session,
                query=poll_query,
                limit=100,
            )
        if records:
            for record in records:
                envelope = event_envelope(record)
                current = record.event_id
                send_started = request.app.state.clock()
                yield format_sse(envelope)
                if (request.app.state.clock() - send_started).total_seconds() > (
                    request.app.state.settings.sse_maximum_send_delay_seconds
                ):
                    logger.warning(
                        "sse_slow_consumer_closed",
                        extra={"last_event_id": current},
                    )
                    return
            last_activity = request.app.state.clock()
            continue
        elapsed = (request.app.state.clock() - last_activity).total_seconds()
        if elapsed >= request.app.state.settings.sse_heartbeat_seconds:
            send_started = request.app.state.clock()
            yield ": heartbeat\n\n"
            if (request.app.state.clock() - send_started).total_seconds() > (
                request.app.state.settings.sse_maximum_send_delay_seconds
            ):
                logger.warning(
                    "sse_slow_consumer_closed",
                    extra={"last_event_id": current},
                )
                return
            last_activity = request.app.state.clock()
        await asyncio.sleep(request.app.state.settings.sse_poll_interval_seconds)


def format_sse(envelope: EventEnvelope) -> str:
    return (
        f"id: {envelope.event_id}\n"
        f"event: {envelope.payload.type}\n"
        f"data: {envelope.model_dump_json()}\n\n"
    )


async def _stream_response(
    request: Request,
    query: EventStreamQuery,
    header_last_event_id: str | None,
) -> StreamingResponse:
    resolved = _last_event_id(query.last_event_id, header_last_event_id)
    await _validate_last_event(request, resolved)
    return StreamingResponse(
        _stream(request, query.model_copy(update={"last_event_id": resolved})),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@router.get(
    "/events/stream",
    operation_id="stream_events",
    response_class=StreamingResponse,
    responses=_stream_responses,
)
async def stream_events(
    request: Request,
    query: Annotated[EventStreamQuery, Depends(event_stream_query)],
    last_event_id: Annotated[
        EventId | None,
        Header(alias="Last-Event-ID"),
    ] = None,
) -> StreamingResponse:
    return await _stream_response(request, query, last_event_id)


@router.get(
    "/tasks/{task_id}/events/stream",
    operation_id="stream_task_events",
    response_class=StreamingResponse,
    responses=_stream_responses,
)
async def stream_task_events(
    request: Request,
    task_id: Annotated[TaskId, Path()],
    query: Annotated[EventStreamQuery, Depends(event_stream_query)],
    last_event_id: Annotated[
        EventId | None,
        Header(alias="Last-Event-ID"),
    ] = None,
) -> StreamingResponse:
    return await _stream_response(
        request,
        query.model_copy(update={"task_id": task_id}),
        last_event_id,
    )


__all__ = ["format_sse", "router"]
