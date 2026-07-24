"""Externally accessible callback delivery management APIs."""

from __future__ import annotations

import base64
import json
from datetime import UTC, datetime
from typing import Annotated
from uuid import uuid4

from fastapi import APIRouter, Depends, Path, Query, Request
from pydantic import TypeAdapter, ValidationError
from sqlalchemy.exc import SQLAlchemyError

from ...control.callbacks import CallbackTransport
from ...persistence import CallbackRepository, Database
from ...persistence.models import CallbackAttemptRecord, CallbackDeliveryRecord
from ...persistence.callbacks import (
    CallbackNotRetryableError,
    callback_attempt_detail,
    callback_delivery_detail,
)
from ...schema.callback import (
    CallbackAttemptListQuery,
    CallbackAttemptListResponse,
    CallbackAttemptSortField,
    CallbackDeliveryListResponse,
    CallbackDeliveryResponse,
    CallbackDeliveryStatus,
    CallbackEventType,
    CallbackListQuery,
    CallbackSortField,
    CallbackTestData,
    CallbackTestEvent,
    CallbackTestRequest,
    CallbackTestResponse,
)
from ...schema.common import (
    CallbackDeliveryId,
    PageInfo,
    SortDirection,
    TaskId,
    UTCDateTime,
)
from ...schema.error import ErrorCode, ErrorDetail, ErrorResponse
from ...schema.management import SettingKey
from ..authentication import require_api_key
from ..errors import ApiError
from ..request_id import request_id_for
from ..responses import api_response


router = APIRouter(
    prefix="/api/v1/management/callbacks",
    tags=["callbacks"],
    dependencies=[Depends(require_api_key)],
)

_utc_adapter = TypeAdapter(UTCDateTime)
_delivery_id_adapter = TypeAdapter(CallbackDeliveryId)
_not_found_responses: dict[int | str, dict[str, object]] = {
    404: {"model": ErrorResponse}
}


def _database(request: Request) -> Database:
    database: Database | None = request.app.state.database
    if database is None:
        raise ApiError(
            status_code=503,
            code=ErrorCode.DEPENDENCY_UNAVAILABLE,
            message="The callback database is not configured",
            retryable=True,
        )
    return database


def _repository(request: Request) -> CallbackRepository:
    return request.app.state.callback_repository


def callback_list_query(
    statuses: Annotated[list[CallbackDeliveryStatus] | None, Query()] = None,
    task_id: Annotated[TaskId | None, Query()] = None,
    event_types: Annotated[list[CallbackEventType] | None, Query()] = None,
    created_after: Annotated[datetime | None, Query()] = None,
    created_before: Annotated[datetime | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    cursor: Annotated[str | None, Query(min_length=1, max_length=1024)] = None,
    sort_by: Annotated[CallbackSortField, Query()] = CallbackSortField.CREATED_AT,
    sort_direction: Annotated[SortDirection, Query()] = SortDirection.DESC,
) -> CallbackListQuery:
    return CallbackListQuery(
        statuses=statuses or [],
        task_id=task_id,
        event_types=event_types or [],
        created_after=created_after,
        created_before=created_before,
        limit=limit,
        cursor=cursor,
        sort_by=sort_by,
        sort_direction=sort_direction,
    )


def _delivery_sort_value(
    record: CallbackDeliveryRecord,
    sort_by: CallbackSortField,
) -> datetime | str:
    if sort_by is CallbackSortField.CREATED_AT:
        return record.created_at
    if sort_by is CallbackSortField.UPDATED_AT:
        return record.updated_at
    return record.status


def _encode_cursor(record: CallbackDeliveryRecord, query: CallbackListQuery) -> str:
    value = _delivery_sort_value(record, query.sort_by)
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=UTC)
        serialized: str = value.astimezone(UTC).isoformat()
    else:
        serialized = value
    payload = json.dumps(
        [
            query.sort_by.value,
            query.sort_direction.value,
            serialized,
            record.delivery_id,
        ],
        separators=(",", ":"),
    ).encode()
    return base64.urlsafe_b64encode(payload).decode().rstrip("=")


def _decode_cursor(
    query: CallbackListQuery,
) -> tuple[datetime | str | None, str | None]:
    if query.cursor is None:
        return None, None
    try:
        padding = "=" * (-len(query.cursor) % 4)
        payload = json.loads(
            base64.urlsafe_b64decode(query.cursor + padding).decode("utf-8")
        )
        if (
            not isinstance(payload, list)
            or len(payload) != 4
            or payload[:2] != [query.sort_by.value, query.sort_direction.value]
        ):
            raise ValueError
        value: datetime | str
        if query.sort_by is CallbackSortField.STATUS:
            if not isinstance(payload[2], str):
                raise ValueError
            value = payload[2]
        else:
            value = _utc_adapter.validate_python(payload[2])
        delivery_id = _delivery_id_adapter.validate_python(payload[3])
    except (
        ValueError,
        TypeError,
        UnicodeDecodeError,
        json.JSONDecodeError,
        ValidationError,
    ) as exc:
        raise ApiError(
            status_code=422,
            code=ErrorCode.VALIDATION_ERROR,
            message="The callback list cursor is invalid",
        ) from exc
    return value, delivery_id


def callback_attempt_list_query(
    delivered: Annotated[bool | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
    cursor: Annotated[str | None, Query(min_length=1, max_length=1024)] = None,
    sort_by: Annotated[
        CallbackAttemptSortField,
        Query(),
    ] = CallbackAttemptSortField.SEQUENCE,
    sort_direction: Annotated[SortDirection, Query()] = SortDirection.DESC,
) -> CallbackAttemptListQuery:
    return CallbackAttemptListQuery(
        delivered=delivered,
        limit=limit,
        cursor=cursor,
        sort_by=sort_by,
        sort_direction=sort_direction,
    )


def _attempt_sort_value(
    record: CallbackAttemptRecord,
    sort_by: CallbackAttemptSortField,
) -> datetime | int:
    if sort_by is CallbackAttemptSortField.SEQUENCE:
        return record.sequence
    if sort_by is CallbackAttemptSortField.STARTED_AT:
        return record.started_at
    return record.duration_ms


def _encode_attempt_cursor(
    record: CallbackAttemptRecord,
    query: CallbackAttemptListQuery,
) -> str:
    value = _attempt_sort_value(record, query.sort_by)
    serialized = (
        value.astimezone(UTC).isoformat()
        if isinstance(value, datetime) and value.tzinfo is not None
        else (
            value.replace(tzinfo=UTC).isoformat()
            if isinstance(value, datetime)
            else value
        )
    )
    payload = json.dumps(
        [
            query.sort_by.value,
            query.sort_direction.value,
            serialized,
            record.sequence,
        ],
        separators=(",", ":"),
    ).encode()
    return base64.urlsafe_b64encode(payload).decode().rstrip("=")


def _decode_attempt_cursor(
    query: CallbackAttemptListQuery,
) -> tuple[datetime | int | None, int | None]:
    if query.cursor is None:
        return None, None
    try:
        padding = "=" * (-len(query.cursor) % 4)
        payload = json.loads(
            base64.urlsafe_b64decode(query.cursor + padding).decode("utf-8")
        )
        if (
            not isinstance(payload, list)
            or len(payload) != 4
            or payload[:2] != [query.sort_by.value, query.sort_direction.value]
        ):
            raise ValueError
        if query.sort_by is CallbackAttemptSortField.STARTED_AT:
            value: datetime | int = _utc_adapter.validate_python(payload[2])
        else:
            if isinstance(payload[2], bool) or not isinstance(payload[2], int):
                raise ValueError
            value = payload[2]
        if isinstance(payload[3], bool) or not isinstance(payload[3], int):
            raise ValueError
        sequence = payload[3]
        if sequence < 1:
            raise ValueError
    except (
        ValueError,
        TypeError,
        UnicodeDecodeError,
        json.JSONDecodeError,
        ValidationError,
    ) as exc:
        raise ApiError(
            status_code=422,
            code=ErrorCode.VALIDATION_ERROR,
            message="The callback attempt cursor is invalid",
        ) from exc
    return value, sequence


async def _materialize(request: Request) -> None:
    try:
        async with _database(request).session_factory() as session:
            maximum_attempts = (
                await request.app.state.system_setting_repository.get_int(
                    session,
                    key=SettingKey.CALLBACK_MAXIMUM_ATTEMPTS,
                    defaults=request.app.state.settings,
                )
            )
            await _repository(request).materialize(
                session,
                now=request.app.state.clock(),
                maximum_attempts=maximum_attempts,
            )
            await session.commit()
    except SQLAlchemyError as exc:
        raise ApiError(
            status_code=503,
            code=ErrorCode.DEPENDENCY_UNAVAILABLE,
            message="Callback deliveries could not be materialized",
            retryable=True,
        ) from exc


@router.get(
    "",
    operation_id="list_callback_deliveries",
    response_model=CallbackDeliveryListResponse,
)
async def list_callback_deliveries(
    request: Request,
    query: Annotated[CallbackListQuery, Depends(callback_list_query)],
) -> CallbackDeliveryListResponse:
    await _materialize(request)
    cursor_value, cursor_delivery_id = _decode_cursor(query)
    try:
        async with _database(request).session_factory() as session:
            records = await _repository(request).list(
                session,
                query=query,
                cursor_value=cursor_value,
                cursor_delivery_id=cursor_delivery_id,
            )
    except SQLAlchemyError as exc:
        raise ApiError(
            status_code=503,
            code=ErrorCode.DEPENDENCY_UNAVAILABLE,
            message="The callback database is unavailable",
            retryable=True,
        ) from exc
    has_more = len(records) > query.limit
    selected = records[: query.limit]
    return CallbackDeliveryListResponse(
        request_id=request_id_for(request),
        items=[callback_delivery_detail(record) for record in selected],
        page=PageInfo(
            has_more=has_more,
            next_cursor=(
                _encode_cursor(selected[-1], query) if has_more and selected else None
            ),
        ),
    )


@router.get(
    "/{delivery_id}",
    operation_id="get_callback_delivery",
    response_model=CallbackDeliveryResponse,
    responses=_not_found_responses,
)
async def get_callback_delivery(
    request: Request,
    delivery_id: Annotated[CallbackDeliveryId, Path()],
) -> CallbackDeliveryResponse:
    try:
        async with _database(request).session_factory() as session:
            record = await _repository(request).get(session, delivery_id)
    except SQLAlchemyError as exc:
        raise ApiError(
            status_code=503,
            code=ErrorCode.DEPENDENCY_UNAVAILABLE,
            message="The callback database is unavailable",
            retryable=True,
        ) from exc
    if record is None:
        raise ApiError(
            status_code=404,
            code=ErrorCode.NOT_FOUND,
            message="The callback delivery does not exist",
        )
    return api_response(request, callback_delivery_detail(record))


@router.get(
    "/{delivery_id}/attempts",
    operation_id="list_callback_attempts",
    response_model=CallbackAttemptListResponse,
    responses=_not_found_responses,
)
async def list_callback_attempts(
    request: Request,
    delivery_id: Annotated[CallbackDeliveryId, Path()],
    query: Annotated[
        CallbackAttemptListQuery,
        Depends(callback_attempt_list_query),
    ],
) -> CallbackAttemptListResponse:
    cursor_value, cursor_sequence = _decode_attempt_cursor(query)
    try:
        async with _database(request).session_factory() as session:
            delivery = await _repository(request).get(session, delivery_id)
            if delivery is None:
                raise ApiError(
                    status_code=404,
                    code=ErrorCode.NOT_FOUND,
                    message="The callback delivery does not exist",
                )
            records = await _repository(request).list_attempts(
                session,
                delivery_id=delivery_id,
                query=query,
                cursor_value=cursor_value,
                cursor_sequence=cursor_sequence,
            )
    except SQLAlchemyError as exc:
        raise ApiError(
            status_code=503,
            code=ErrorCode.DEPENDENCY_UNAVAILABLE,
            message="The callback database is unavailable",
            retryable=True,
        ) from exc
    has_more = len(records) > query.limit
    selected = records[: query.limit]
    return CallbackAttemptListResponse(
        request_id=request_id_for(request),
        items=[callback_attempt_detail(record) for record in selected],
        page=PageInfo(
            has_more=has_more,
            next_cursor=(
                _encode_attempt_cursor(selected[-1], query)
                if has_more and selected
                else None
            ),
        ),
    )


@router.post(
    "/{delivery_id}/retry",
    operation_id="retry_callback_delivery",
    response_model=CallbackDeliveryResponse,
    responses={
        404: {"model": ErrorResponse},
        409: {"model": ErrorResponse},
    },
)
async def retry_callback_delivery(
    request: Request,
    delivery_id: Annotated[CallbackDeliveryId, Path()],
) -> CallbackDeliveryResponse:
    try:
        async with _database(request).session_factory() as session:
            try:
                record = await _repository(request).retry(
                    session,
                    delivery_id=delivery_id,
                    now=request.app.state.clock(),
                )
            except CallbackNotRetryableError as exc:
                raise ApiError(
                    status_code=409,
                    code=ErrorCode.CONFLICT,
                    message="The callback delivery is not in a retryable state",
                ) from exc
            if record is None:
                raise ApiError(
                    status_code=404,
                    code=ErrorCode.NOT_FOUND,
                    message="The callback delivery does not exist",
                )
            await session.commit()
    except SQLAlchemyError as exc:
        raise ApiError(
            status_code=503,
            code=ErrorCode.DEPENDENCY_UNAVAILABLE,
            message="The callback database is unavailable",
            retryable=True,
        ) from exc
    return api_response(request, callback_delivery_detail(record))


@router.post(
    "/test",
    operation_id="test_callback",
    response_model=CallbackTestResponse,
)
async def test_callback(
    request: Request,
    body: CallbackTestRequest,
) -> CallbackTestResponse:
    now = request.app.state.clock()
    event = CallbackTestEvent(
        type="callback.test",
        schema_version=request.app.state.settings.result_schema_version,
        event_id=f"event_{uuid4().hex}",
        occurred_at=now,
        metadata=body.metadata,
    )
    transport: CallbackTransport = request.app.state.callback_transport
    result = await transport.deliver(
        event=event,
        target_url=body.url,
        secret=body.secret,
        now=now,
    )
    return api_response(
        request,
        CallbackTestData(
            delivered=result.delivered,
            response_status_code=result.status_code,
            duration_ms=result.duration_ms,
            error=(
                result.error
                if result.error is not None
                else (
                    None
                    if result.delivered
                    else ErrorDetail(
                        code=ErrorCode.DEPENDENCY_UNAVAILABLE,
                        message="Callback test failed",
                    )
                )
            ),
        ),
    )


__all__ = ["router"]
