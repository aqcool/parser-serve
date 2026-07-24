"""Externally accessible API key management endpoints."""

from __future__ import annotations

import base64
import json
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query, Request, status
from pydantic import TypeAdapter, ValidationError
from sqlalchemy.exc import SQLAlchemyError

from ...persistence import Database
from ...persistence.api_keys import (
    ApiKeyRepository,
    LastActiveApiKeyError,
    api_key_summary,
)
from ...schema.authentication import (
    ApiKeyListQuery,
    ApiKeyListResponse,
    ApiKeyResponse,
    ApiKeySortField,
    ApiKeyStatus,
    ApiKeyKind,
    ApiKeySummary,
    CreateApiKeyRequest,
    CreateApiKeyResponse,
    DeleteApiKeyData,
    DeleteApiKeyResponse,
    RotateApiKeyResponse,
    UpdateApiKeyRequest,
)
from ...schema.common import ApiKeyId, PageInfo, SortDirection, UTCDateTime
from ...schema.error import ErrorCode, ErrorResponse
from ..authentication import require_api_key
from ..errors import ApiError
from ..request_id import request_id_for
from ..responses import api_response


router = APIRouter(
    prefix="/api/v1/management/api-keys",
    tags=["api-keys"],
    dependencies=[Depends(require_api_key)],
)

_api_key_id_adapter = TypeAdapter(ApiKeyId)
_utc_datetime_adapter = TypeAdapter(UTCDateTime)
_not_found_response: dict[int | str, dict[str, object]] = {
    404: {"model": ErrorResponse}
}
_mutable_responses: dict[int | str, dict[str, object]] = {
    404: {"model": ErrorResponse},
    409: {"model": ErrorResponse},
}


def _database(request: Request) -> Database:
    database: Database | None = request.app.state.database
    if database is None:
        raise ApiError(
            status_code=503,
            code=ErrorCode.DEPENDENCY_UNAVAILABLE,
            message="The API key database is not configured",
            retryable=True,
        )
    return database


def _repository(request: Request) -> ApiKeyRepository:
    return request.app.state.api_key_repository


def _api_key_sort_value(
    item: ApiKeySummary,
    sort_by: ApiKeySortField,
) -> datetime | str:
    if sort_by is ApiKeySortField.CREATED_AT:
        return item.created_at
    if sort_by is ApiKeySortField.UPDATED_AT:
        return item.updated_at
    return item.name


def _encode_cursor(item: ApiKeySummary, query: ApiKeyListQuery) -> str:
    value = _api_key_sort_value(item, query.sort_by)
    serialized = value.isoformat() if isinstance(value, datetime) else value
    payload = json.dumps(
        [
            query.sort_by.value,
            query.sort_direction.value,
            serialized,
            item.api_key_id,
        ],
        separators=(",", ":"),
    ).encode()
    return base64.urlsafe_b64encode(payload).decode().rstrip("=")


def _decode_cursor(
    query: ApiKeyListQuery,
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
        if query.sort_by is ApiKeySortField.NAME:
            if not isinstance(payload[2], str):
                raise ValueError
            value = payload[2]
        else:
            value = _utc_datetime_adapter.validate_python(payload[2])
        api_key_id = _api_key_id_adapter.validate_python(payload[3])
    except (
        ValueError,
        UnicodeDecodeError,
        json.JSONDecodeError,
        ValidationError,
    ) as exc:
        raise ApiError(
            status_code=422,
            code=ErrorCode.VALIDATION_ERROR,
            message="The API key list cursor is invalid",
        ) from exc
    return value, api_key_id


def _validate_expiration(expires_at: datetime | None, *, now: datetime) -> None:
    if expires_at is not None and expires_at <= now:
        raise ApiError(
            status_code=422,
            code=ErrorCode.VALIDATION_ERROR,
            message="expires_at must be later than the current time",
        )


def _not_found() -> ApiError:
    return ApiError(
        status_code=404,
        code=ErrorCode.NOT_FOUND,
        message="The API key does not exist",
    )


def _last_active_conflict() -> ApiError:
    return ApiError(
        status_code=409,
        code=ErrorCode.CONFLICT,
        message="The final active database API key cannot be disabled or deleted",
    )


def api_key_list_query(
    kinds: Annotated[list[ApiKeyKind] | None, Query()] = None,
    statuses: Annotated[list[ApiKeyStatus] | None, Query()] = None,
    name_contains: Annotated[
        str | None,
        Query(min_length=1, max_length=128),
    ] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    cursor: Annotated[str | None, Query(min_length=1, max_length=1024)] = None,
    sort_by: Annotated[ApiKeySortField, Query()] = ApiKeySortField.CREATED_AT,
    sort_direction: Annotated[SortDirection, Query()] = SortDirection.DESC,
) -> ApiKeyListQuery:
    return ApiKeyListQuery(
        kinds=kinds or [],
        statuses=statuses or [],
        name_contains=name_contains,
        limit=limit,
        cursor=cursor,
        sort_by=sort_by,
        sort_direction=sort_direction,
    )


@router.post(
    "",
    operation_id="create_api_key",
    status_code=status.HTTP_201_CREATED,
    response_model=CreateApiKeyResponse,
)
async def create_api_key(
    request: Request,
    body: CreateApiKeyRequest,
) -> CreateApiKeyResponse:
    now = request.app.state.clock()
    _validate_expiration(body.expires_at, now=now)
    try:
        async with _database(request).session_factory() as session:
            data = await _repository(request).create(
                session,
                name=body.name,
                kind=body.kind,
                worker_id=body.worker_id,
                expires_at=body.expires_at,
                now=now,
            )
            await session.commit()
    except SQLAlchemyError as exc:
        raise _database_error() from exc
    return api_response(request, data)


@router.get(
    "",
    operation_id="list_api_keys",
    response_model=ApiKeyListResponse,
)
async def list_api_keys(
    request: Request,
    query: Annotated[ApiKeyListQuery, Depends(api_key_list_query)],
) -> ApiKeyListResponse:
    now = request.app.state.clock()
    cursor_value, cursor_api_key_id = _decode_cursor(query)
    try:
        async with _database(request).session_factory() as session:
            summaries = await _repository(request).list(
                session,
                query=query,
                now=now,
                cursor_value=cursor_value,
                cursor_api_key_id=cursor_api_key_id,
            )
    except SQLAlchemyError as exc:
        raise _database_error() from exc
    has_more = len(summaries) > query.limit
    items = summaries[: query.limit]
    return ApiKeyListResponse(
        request_id=request_id_for(request),
        items=items,
        page=PageInfo(
            has_more=has_more,
            next_cursor=(
                _encode_cursor(items[-1], query) if has_more and items else None
            ),
        ),
    )


@router.get(
    "/{api_key_id}",
    operation_id="get_api_key",
    response_model=ApiKeyResponse,
    responses=_not_found_response,
)
async def get_api_key(
    request: Request,
    api_key_id: Annotated[ApiKeyId, Path()],
) -> ApiKeyResponse:
    now = request.app.state.clock()
    try:
        async with _database(request).session_factory() as session:
            record = await _repository(request).get(session, api_key_id)
            if record is None:
                raise _not_found()
            summary = api_key_summary(record, now=now)
    except SQLAlchemyError as exc:
        raise _database_error() from exc
    return api_response(request, summary)


@router.patch(
    "/{api_key_id}",
    operation_id="update_api_key",
    response_model=ApiKeyResponse,
    responses=_mutable_responses,
)
async def update_api_key(
    request: Request,
    body: UpdateApiKeyRequest,
    api_key_id: Annotated[ApiKeyId, Path()],
) -> ApiKeyResponse:
    now = request.app.state.clock()
    _validate_expiration(body.expires_at, now=now)
    try:
        async with _database(request).session_factory() as session:
            try:
                record = await _repository(request).update(
                    session,
                    api_key_id=api_key_id,
                    update=body,
                    now=now,
                )
            except LastActiveApiKeyError as exc:
                raise _last_active_conflict() from exc
            if record is None:
                raise _not_found()
            summary = api_key_summary(record, now=now)
            await session.commit()
    except SQLAlchemyError as exc:
        raise _database_error() from exc
    return api_response(request, summary)


@router.post(
    "/{api_key_id}/rotate",
    operation_id="rotate_api_key",
    response_model=RotateApiKeyResponse,
    responses=_not_found_response,
)
async def rotate_api_key(
    request: Request,
    api_key_id: Annotated[ApiKeyId, Path()],
) -> RotateApiKeyResponse:
    now = request.app.state.clock()
    try:
        async with _database(request).session_factory() as session:
            data = await _repository(request).rotate(
                session,
                api_key_id=api_key_id,
                now=now,
            )
            if data is None:
                raise _not_found()
            await session.commit()
    except SQLAlchemyError as exc:
        raise _database_error() from exc
    return api_response(request, data)


@router.delete(
    "/{api_key_id}",
    operation_id="delete_api_key",
    response_model=DeleteApiKeyResponse,
    responses=_mutable_responses,
)
async def delete_api_key(
    request: Request,
    api_key_id: Annotated[ApiKeyId, Path()],
) -> DeleteApiKeyResponse:
    try:
        async with _database(request).session_factory() as session:
            try:
                deleted = await _repository(request).delete(
                    session,
                    api_key_id=api_key_id,
                    now=request.app.state.clock(),
                )
            except LastActiveApiKeyError as exc:
                raise _last_active_conflict() from exc
            if not deleted:
                raise _not_found()
            await session.commit()
    except SQLAlchemyError as exc:
        raise _database_error() from exc
    return api_response(
        request,
        DeleteApiKeyData(api_key_id=api_key_id, deleted=True),
    )


def _database_error() -> ApiError:
    return ApiError(
        status_code=503,
        code=ErrorCode.DEPENDENCY_UNAVAILABLE,
        message="The API key database is unavailable",
        retryable=True,
    )


__all__ = ["router"]
