"""Public task submission and lifecycle endpoints."""

from __future__ import annotations

import base64
import json
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Annotated
from urllib.parse import quote

from fastapi import APIRouter, Depends, Header, Path, Query, Request, status
from pydantic import TypeAdapter, ValidationError
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from starlette.responses import StreamingResponse

from ...control import (
    TaskAlreadyRoutedError,
    TaskRoutingUnavailableError,
    TaskSourceUnresolvedError,
)
from ...persistence import ArtifactRepository, Database
from ...persistence.files import (
    UnsupportedFileTypeError,
    UploadedFileNotFoundError,
    artifact_detail,
)
from ...persistence.models import ArtifactRecord, TaskRecord
from ...persistence.tasks import (
    IdempotencyConflictError,
    PipelineNotFoundError,
    TaskNotCancellableError,
    TaskNotRetryableError,
    TaskRepository,
    task_detail,
)
from ...schema.artifact import (
    ArtifactDownload,
    ArtifactDownloadResponse,
    ArtifactListQuery,
    ArtifactListResponse,
    ArtifactSortField,
)
from ...schema.artifact import ArtifactType
from ...schema.common import (
    ArtifactId,
    MediaCategory,
    PageInfo,
    PipelineId,
    SortDirection,
    StageId,
    TaskId,
    UTCDateTime,
)
from ...storage import Storage
from ...schema.error import ErrorCode, ErrorResponse
from ...schema.hardware import DeviceRuntime
from ...schema.management import SettingKey
from ...schema.queue import QueueNoticeReason
from ...schema.result import ParseResult, ParseResultResponse
from ...schema.stage import (
    StageDetail,
    StageDetailResponse,
    StageListQuery,
    StageListResponse,
    StageSortField,
    StageStatus,
)
from ...schema.task import (
    CreateTaskData,
    CreateTaskRequest,
    CreateTaskResponse,
    TaskDetailResponse,
    TaskListQuery,
    TaskListResponse,
    TaskSortField,
    TaskStatus,
)
from ..authentication import require_api_key
from ..errors import ApiError
from ..dynamic_settings import effective_int_setting
from ..request_id import request_id_for
from ..responses import api_response


router = APIRouter(
    prefix="/api/v1/tasks",
    tags=["tasks"],
    dependencies=[Depends(require_api_key)],
)

_task_id_adapter = TypeAdapter(TaskId)
_stage_id_adapter = TypeAdapter(StageId)
_artifact_id_adapter = TypeAdapter(ArtifactId)
_utc_datetime_adapter = TypeAdapter(UTCDateTime)
_not_found_responses: dict[int | str, dict[str, object]] = {
    404: {"model": ErrorResponse}
}
_action_responses: dict[int | str, dict[str, object]] = {
    404: {"model": ErrorResponse},
    409: {"model": ErrorResponse},
}
_artifact_content_responses: dict[int | str, dict[str, object]] = {
    200: {
        "description": "Raw Artifact bytes",
        "content": {
            "application/octet-stream": {
                "schema": {"type": "string", "format": "binary"}
            }
        },
    },
    404: {"model": ErrorResponse},
}
_result_content_responses: dict[int | str, dict[str, object]] = {
    200: {
        "description": "Raw primary result bytes",
        "content": {
            "application/octet-stream": {
                "schema": {"type": "string", "format": "binary"}
            }
        },
    },
    404: {"model": ErrorResponse},
    409: {"model": ErrorResponse},
}


def _database(request: Request) -> Database:
    database: Database | None = request.app.state.database
    if database is None:
        raise _database_error("The task database is not configured")
    return database


def _repository(request: Request) -> TaskRepository:
    return request.app.state.task_repository


def _artifact_repository(request: Request) -> ArtifactRepository:
    return request.app.state.artifact_repository


def _storage(request: Request) -> Storage:
    return request.app.state.storage


def _database_error(message: str = "The task database is unavailable") -> ApiError:
    return ApiError(
        status_code=503,
        code=ErrorCode.DEPENDENCY_UNAVAILABLE,
        message=message,
        retryable=True,
    )


def _not_found() -> ApiError:
    return ApiError(
        status_code=404,
        code=ErrorCode.NOT_FOUND,
        message="The task does not exist",
    )


def _result_not_ready() -> ApiError:
    return ApiError(
        status_code=409,
        code=ErrorCode.CONFLICT,
        message="The task result is not ready",
        retryable=True,
    )


def task_list_query(
    statuses: Annotated[list[TaskStatus] | None, Query()] = None,
    media_category: Annotated[MediaCategory | None, Query()] = None,
    pipeline_id: Annotated[PipelineId | None, Query()] = None,
    backend_name: Annotated[
        str | None,
        Query(min_length=1, max_length=128),
    ] = None,
    runtime: Annotated[DeviceRuntime | None, Query()] = None,
    created_after: Annotated[datetime | None, Query()] = None,
    created_before: Annotated[datetime | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    cursor: Annotated[str | None, Query(min_length=1, max_length=1024)] = None,
    sort_by: Annotated[TaskSortField, Query()] = TaskSortField.CREATED_AT,
    sort_direction: Annotated[SortDirection, Query()] = SortDirection.DESC,
) -> TaskListQuery:
    return TaskListQuery(
        statuses=statuses or [],
        media_category=media_category,
        pipeline_id=pipeline_id,
        backend_name=backend_name,
        runtime=runtime,
        created_after=created_after,
        created_before=created_before,
        limit=limit,
        cursor=cursor,
        sort_by=sort_by,
        sort_direction=sort_direction,
    )


def stage_list_query(
    statuses: Annotated[list[StageStatus] | None, Query()] = None,
    backend_id: Annotated[str | None, Query(min_length=1, max_length=72)] = None,
    worker_id: Annotated[str | None, Query(min_length=1, max_length=72)] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    cursor: Annotated[str | None, Query(min_length=1, max_length=1024)] = None,
    sort_by: Annotated[StageSortField, Query()] = StageSortField.POSITION,
    sort_direction: Annotated[SortDirection, Query()] = SortDirection.ASC,
) -> StageListQuery:
    return StageListQuery(
        statuses=statuses or [],
        backend_id=backend_id,
        worker_id=worker_id,
        limit=limit,
        cursor=cursor,
        sort_by=sort_by,
        sort_direction=sort_direction,
    )


def artifact_list_query(
    types: Annotated[list[ArtifactType] | None, Query()] = None,
    mime_type: Annotated[str | None, Query(min_length=1, max_length=255)] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    cursor: Annotated[str | None, Query(min_length=1, max_length=1024)] = None,
    sort_by: Annotated[ArtifactSortField, Query()] = ArtifactSortField.CREATED_AT,
    sort_direction: Annotated[SortDirection, Query()] = SortDirection.ASC,
) -> ArtifactListQuery:
    return ArtifactListQuery(
        types=types or [],
        mime_type=mime_type,
        limit=limit,
        cursor=cursor,
        sort_by=sort_by,
        sort_direction=sort_direction,
    )


def _cursor_error(resource: str) -> ApiError:
    return ApiError(
        status_code=422,
        code=ErrorCode.VALIDATION_ERROR,
        message=f"The {resource} cursor is invalid for the requested ordering",
    )


def _encode_bound_cursor(
    resource: str,
    sort_by: StrEnum,
    sort_direction: SortDirection,
    value: datetime | int | str,
    item_id: str,
) -> str:
    serialized = _as_utc(value).isoformat() if isinstance(value, datetime) else value
    payload = json.dumps(
        [resource, sort_by.value, sort_direction.value, serialized, item_id],
        separators=(",", ":"),
    ).encode()
    return base64.urlsafe_b64encode(payload).decode().rstrip("=")


def _decode_bound_cursor(
    cursor: str | None,
    *,
    resource: str,
    sort_by: StrEnum,
    sort_direction: SortDirection,
) -> tuple[object | None, object | None]:
    if cursor is None:
        return None, None
    try:
        padding = "=" * (-len(cursor) % 4)
        payload = json.loads(base64.urlsafe_b64decode(cursor + padding).decode("utf-8"))
        if (
            not isinstance(payload, list)
            or len(payload) != 5
            or payload[:3] != [resource, sort_by.value, sort_direction.value]
        ):
            raise ValueError
        return payload[3], payload[4]
    except (
        ValueError,
        TypeError,
        UnicodeDecodeError,
        json.JSONDecodeError,
    ) as exc:
        raise _cursor_error(resource) from exc


def _stage_sort_value(
    stage: StageDetail,
    sort_by: StageSortField,
) -> datetime | int:
    return stage.position if sort_by is StageSortField.POSITION else stage.created_at


def _encode_stage_cursor(stage: StageDetail, query: StageListQuery) -> str:
    return _encode_bound_cursor(
        "stage",
        query.sort_by,
        query.sort_direction,
        _stage_sort_value(stage, query.sort_by),
        stage.stage_id,
    )


def _decode_stage_cursor(
    query: StageListQuery,
) -> tuple[datetime | int | None, str | None]:
    raw_value, raw_id = _decode_bound_cursor(
        query.cursor,
        resource="stage",
        sort_by=query.sort_by,
        sort_direction=query.sort_direction,
    )
    if raw_value is None:
        return None, None
    try:
        if query.sort_by is StageSortField.POSITION:
            if not isinstance(raw_value, int) or isinstance(raw_value, bool):
                raise ValueError
            value: datetime | int = raw_value
        else:
            value = _utc_datetime_adapter.validate_python(raw_value)
        stage_id = _stage_id_adapter.validate_python(raw_id)
    except (ValueError, TypeError, ValidationError) as exc:
        raise _cursor_error("stage") from exc
    return value, stage_id


def _artifact_sort_value(
    record: ArtifactRecord,
    sort_by: ArtifactSortField,
) -> datetime | int | str:
    if sort_by is ArtifactSortField.CREATED_AT:
        return record.created_at
    if sort_by is ArtifactSortField.FILENAME:
        return record.filename
    return record.size_bytes


def _encode_artifact_cursor(
    record: ArtifactRecord,
    query: ArtifactListQuery,
) -> str:
    return _encode_bound_cursor(
        "artifact",
        query.sort_by,
        query.sort_direction,
        _artifact_sort_value(record, query.sort_by),
        record.artifact_id,
    )


def _decode_artifact_cursor(
    query: ArtifactListQuery,
) -> tuple[datetime | int | str | None, str | None]:
    raw_value, raw_id = _decode_bound_cursor(
        query.cursor,
        resource="artifact",
        sort_by=query.sort_by,
        sort_direction=query.sort_direction,
    )
    if raw_value is None:
        return None, None
    try:
        if query.sort_by is ArtifactSortField.CREATED_AT:
            value: datetime | int | str = _utc_datetime_adapter.validate_python(
                raw_value
            )
        elif query.sort_by is ArtifactSortField.SIZE_BYTES:
            if not isinstance(raw_value, int) or isinstance(raw_value, bool):
                raise ValueError
            value = raw_value
        elif isinstance(raw_value, str):
            value = raw_value
        else:
            raise ValueError
        artifact_id = _artifact_id_adapter.validate_python(raw_id)
    except (ValueError, TypeError, ValidationError) as exc:
        raise _cursor_error("artifact") from exc
    return value, artifact_id


def _sort_value(record: TaskRecord, sort_by: TaskSortField) -> datetime | int:
    if sort_by is TaskSortField.CREATED_AT:
        return record.created_at
    if sort_by is TaskSortField.UPDATED_AT:
        return record.updated_at
    return record.priority


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _encode_cursor(
    record: TaskRecord,
    *,
    sort_by: TaskSortField,
    sort_direction: SortDirection,
) -> str:
    value = _sort_value(record, sort_by)
    serialized = _as_utc(value).isoformat() if isinstance(value, datetime) else value
    payload = json.dumps(
        [sort_by.value, sort_direction.value, serialized, record.task_id],
        separators=(",", ":"),
    ).encode()
    return base64.urlsafe_b64encode(payload).decode().rstrip("=")


def _decode_cursor(
    query: TaskListQuery,
) -> tuple[datetime | int | None, str | None]:
    if query.cursor is None:
        return None, None
    try:
        padding = "=" * (-len(query.cursor) % 4)
        payload = json.loads(
            base64.urlsafe_b64decode(query.cursor + padding).decode("utf-8")
        )
        if not isinstance(payload, list) or len(payload) != 4:
            raise ValueError
        if payload[0] != query.sort_by.value:
            raise ValueError
        if payload[1] != query.sort_direction.value:
            raise ValueError
        value = (
            int(payload[2])
            if query.sort_by is TaskSortField.PRIORITY
            else _utc_datetime_adapter.validate_python(payload[2])
        )
        task_id = _task_id_adapter.validate_python(payload[3])
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
            message="The task list cursor is invalid for this query",
        ) from exc
    return value, task_id


@router.post(
    "",
    operation_id="create_task",
    status_code=status.HTTP_201_CREATED,
    response_model=CreateTaskResponse,
    responses={409: {"model": ErrorResponse}},
)
async def create_task(
    request: Request,
    body: CreateTaskRequest,
    idempotency_key: Annotated[
        str | None,
        Header(
            alias="Idempotency-Key",
            min_length=1,
            max_length=256,
        ),
    ] = None,
) -> CreateTaskResponse:
    now = request.app.state.clock()
    repository = _repository(request)
    routed_task_id: str | None = None
    try:
        async with _database(request).session_factory() as session:
            try:
                record, created = await repository.create(
                    session,
                    request=body,
                    idempotency_key=idempotency_key,
                    now=now,
                )
                if created:
                    created_task_id = record.task_id
                    try:
                        async with session.begin_nested():
                            routed_record = await request.app.state.task_router.route(
                                session,
                                task_id=record.task_id,
                                now=now,
                            )
                            routed_task_id = routed_record.task_id
                    except (
                        TaskAlreadyRoutedError,
                        TaskRoutingUnavailableError,
                        TaskSourceUnresolvedError,
                    ):
                        refreshed = await repository.get(
                            session,
                            created_task_id,
                        )
                        if refreshed is None:  # pragma: no cover - same transaction
                            raise RuntimeError(
                                "new task disappeared after routing rollback"
                            )
                        record = refreshed
                await session.commit()
            except IntegrityError:
                await session.rollback()
                if idempotency_key is None:
                    raise
                record, _ = await repository.create(
                    session,
                    request=body,
                    idempotency_key=idempotency_key,
                    now=now,
                )
                await session.commit()
    except IdempotencyConflictError as exc:
        raise ApiError(
            status_code=409,
            code=ErrorCode.CONFLICT,
            message="Idempotency-Key was already used with a different request",
        ) from exc
    except PipelineNotFoundError as exc:
        raise ApiError(
            status_code=409,
            code=ErrorCode.CONFLICT,
            message="The requested published pipeline version is unavailable",
        ) from exc
    except UploadedFileNotFoundError as exc:
        raise ApiError(
            status_code=404,
            code=ErrorCode.NOT_FOUND,
            message="The uploaded file does not exist or has expired",
        ) from exc
    except UnsupportedFileTypeError as exc:
        raise ApiError(
            status_code=415,
            code=ErrorCode.UNSUPPORTED_MEDIA_TYPE,
            message="The Object Storage file type is unsupported",
        ) from exc
    except SQLAlchemyError as exc:
        raise _database_error() from exc
    if routed_task_id is not None:
        await request.app.state.task_queue_notifier.publish(
            reason=QueueNoticeReason.TASK_ROUTED,
            task_id=routed_task_id,
            occurred_at=now,
        )
    return api_response(
        request,
        CreateTaskData(
            task_id=record.task_id,
            status=TaskStatus(record.status),
            created_at=_as_utc(record.created_at),
        ),
    )


@router.get(
    "",
    operation_id="list_tasks",
    response_model=TaskListResponse,
)
async def list_tasks(
    request: Request,
    query: Annotated[TaskListQuery, Depends(task_list_query)],
) -> TaskListResponse:
    cursor_value, cursor_task_id = _decode_cursor(query)
    try:
        async with _database(request).session_factory() as session:
            records = await _repository(request).list(
                session,
                query=query,
                cursor_value=cursor_value,
                cursor_task_id=cursor_task_id,
            )
            details = [task_detail(record) for record in records[: query.limit]]
    except SQLAlchemyError as exc:
        raise _database_error() from exc
    has_more = len(records) > query.limit
    return TaskListResponse(
        request_id=request_id_for(request),
        items=details,
        page=PageInfo(
            has_more=has_more,
            next_cursor=(
                _encode_cursor(
                    records[query.limit - 1],
                    sort_by=query.sort_by,
                    sort_direction=query.sort_direction,
                )
                if has_more
                else None
            ),
        ),
    )


@router.get(
    "/{task_id}",
    operation_id="get_task",
    response_model=TaskDetailResponse,
    responses=_not_found_responses,
)
async def get_task(
    request: Request,
    task_id: Annotated[TaskId, Path()],
) -> TaskDetailResponse:
    try:
        async with _database(request).session_factory() as session:
            record = await _repository(request).get(session, task_id)
            if record is None:
                raise _not_found()
            detail = task_detail(record)
    except SQLAlchemyError as exc:
        raise _database_error() from exc
    return api_response(request, detail)


@router.get(
    "/{task_id}/stages",
    operation_id="list_task_stages",
    response_model=StageListResponse,
    responses=_not_found_responses,
)
async def list_task_stages(
    request: Request,
    task_id: Annotated[TaskId, Path()],
    query: Annotated[StageListQuery, Depends(stage_list_query)],
) -> StageListResponse:
    cursor_value, cursor_stage_id = _decode_stage_cursor(query)
    try:
        async with _database(request).session_factory() as session:
            record = await _repository(request).get(session, task_id)
            if record is None:
                raise _not_found()
            stages = task_detail(record).stages
    except SQLAlchemyError as exc:
        raise _database_error() from exc
    if query.statuses:
        stages = [stage for stage in stages if stage.status in query.statuses]
    if query.backend_id is not None:
        stages = [stage for stage in stages if stage.backend_id == query.backend_id]
    if query.worker_id is not None:
        stages = [stage for stage in stages if stage.worker_id == query.worker_id]
    stages.sort(
        key=lambda stage: (
            _stage_sort_value(stage, query.sort_by),
            stage.stage_id,
        ),
        reverse=query.sort_direction is SortDirection.DESC,
    )
    if cursor_value is not None and cursor_stage_id is not None:
        cursor_key = (cursor_value, cursor_stage_id)
        stages = [
            stage
            for stage in stages
            if (
                (_stage_sort_value(stage, query.sort_by), stage.stage_id) > cursor_key
                if query.sort_direction is SortDirection.ASC
                else (_stage_sort_value(stage, query.sort_by), stage.stage_id)
                < cursor_key
            )
        ]
    has_more = len(stages) > query.limit
    selected = stages[: query.limit]
    return StageListResponse(
        request_id=request_id_for(request),
        items=selected,
        page=PageInfo(
            has_more=has_more,
            next_cursor=(
                _encode_stage_cursor(selected[-1], query)
                if has_more and selected
                else None
            ),
        ),
    )


@router.get(
    "/{task_id}/stages/{stage_id}",
    operation_id="get_task_stage",
    response_model=StageDetailResponse,
    responses=_not_found_responses,
)
async def get_task_stage(
    request: Request,
    task_id: Annotated[TaskId, Path()],
    stage_id: Annotated[StageId, Path()],
) -> StageDetailResponse:
    try:
        async with _database(request).session_factory() as session:
            record = await _repository(request).get(session, task_id)
            if record is None:
                raise _not_found()
            stage = next(
                (
                    item
                    for item in task_detail(record).stages
                    if item.stage_id == stage_id
                ),
                None,
            )
    except SQLAlchemyError as exc:
        raise _database_error() from exc
    if stage is None:
        raise ApiError(
            status_code=404,
            code=ErrorCode.NOT_FOUND,
            message="The Stage does not exist for this task",
        )
    return api_response(request, stage)


async def _primary_result_artifact(
    request: Request,
    task_id: str,
) -> ArtifactRecord:
    try:
        async with _database(request).session_factory() as session:
            task = await _repository(request).get(session, task_id)
            if task is None:
                raise _not_found()
            if task.status != TaskStatus.SUCCEEDED.value or task.result_uri is None:
                raise _result_not_ready()
            artifact = await _artifact_repository(request).get_by_storage_uri(
                session,
                task_id=task_id,
                storage_uri=task.result_uri,
                now=request.app.state.clock(),
            )
    except SQLAlchemyError as exc:
        raise _database_error() from exc
    if artifact is None or not await _storage(request).exists(artifact.storage_key):
        raise ApiError(
            status_code=404,
            code=ErrorCode.NOT_FOUND,
            message="The primary result Artifact does not exist or has expired",
        )
    return artifact


@router.get(
    "/{task_id}/result",
    operation_id="get_task_result",
    response_model=ParseResultResponse,
    responses={
        404: {"model": ErrorResponse},
        409: {"model": ErrorResponse},
        500: {"model": ErrorResponse},
    },
)
async def get_task_result(
    request: Request,
    task_id: Annotated[TaskId, Path()],
) -> ParseResultResponse:
    artifact = await _primary_result_artifact(request, task_id)
    if (
        artifact.artifact_type != ArtifactType.RESULT_JSON.value
        or artifact.mime_type != "application/json"
    ):
        raise ApiError(
            status_code=409,
            code=ErrorCode.CONFLICT,
            message="The primary result is not a typed JSON result",
        )
    maximum_result_bytes = await effective_int_setting(
        request,
        SettingKey.MAXIMUM_RESULT_JSON_BYTES,
    )
    content = bytearray()
    async for chunk in _storage(request).read(artifact.storage_key):
        content.extend(chunk)
        if len(content) > maximum_result_bytes:
            raise ApiError(
                status_code=500,
                code=ErrorCode.INTERNAL_ERROR,
                message="The primary result exceeds the configured JSON limit",
            )
    try:
        result = ParseResult.model_validate_json(content)
    except ValidationError as exc:
        raise ApiError(
            status_code=500,
            code=ErrorCode.INTERNAL_ERROR,
            message="The primary result does not match the ParseResult schema",
        ) from exc
    if result.task_id != task_id:
        raise ApiError(
            status_code=500,
            code=ErrorCode.INTERNAL_ERROR,
            message="The primary result belongs to a different task",
        )
    return api_response(request, result)


@router.get(
    "/{task_id}/result/content",
    operation_id="download_task_result",
    response_class=StreamingResponse,
    responses=_result_content_responses,
)
async def download_task_result(
    request: Request,
    task_id: Annotated[TaskId, Path()],
) -> StreamingResponse:
    artifact = await _primary_result_artifact(request, task_id)
    return StreamingResponse(
        _storage(request).read(artifact.storage_key),
        media_type=artifact.mime_type,
        headers={
            "Content-Disposition": (
                f"attachment; filename*=UTF-8''{quote(artifact.filename, safe='')}"
            ),
            "Content-Length": str(artifact.size_bytes),
            "X-Content-SHA256": artifact.sha256,
        },
    )


@router.get(
    "/{task_id}/artifacts",
    operation_id="list_task_artifacts",
    response_model=ArtifactListResponse,
    responses=_not_found_responses,
)
async def list_task_artifacts(
    request: Request,
    task_id: Annotated[TaskId, Path()],
    query: Annotated[ArtifactListQuery, Depends(artifact_list_query)],
) -> ArtifactListResponse:
    cursor_value, cursor_artifact_id = _decode_artifact_cursor(query)
    try:
        async with _database(request).session_factory() as session:
            task = await _repository(request).get(session, task_id)
            if task is None:
                raise _not_found()
            records = await _artifact_repository(request).list_for_task(
                session,
                task_id,
                query=query,
                cursor_value=cursor_value,
                cursor_artifact_id=cursor_artifact_id,
                now=request.app.state.clock(),
            )
    except SQLAlchemyError as exc:
        raise _database_error() from exc
    has_more = len(records) > query.limit
    selected = records[: query.limit]
    return ArtifactListResponse(
        request_id=request_id_for(request),
        items=[artifact_detail(record) for record in selected],
        page=PageInfo(
            has_more=has_more,
            next_cursor=(
                _encode_artifact_cursor(selected[-1], query)
                if has_more and selected
                else None
            ),
        ),
    )


@router.get(
    "/{task_id}/artifacts/{artifact_id}/content",
    operation_id="download_task_artifact",
    response_class=StreamingResponse,
    responses=_artifact_content_responses,
)
async def download_task_artifact(
    request: Request,
    task_id: Annotated[TaskId, Path()],
    artifact_id: Annotated[ArtifactId, Path()],
) -> StreamingResponse:
    try:
        async with _database(request).session_factory() as session:
            record = await _artifact_repository(request).get(
                session,
                task_id=task_id,
                artifact_id=artifact_id,
                now=request.app.state.clock(),
            )
    except SQLAlchemyError as exc:
        raise _database_error() from exc
    if record is None or not await _storage(request).exists(record.storage_key):
        raise ApiError(
            status_code=404,
            code=ErrorCode.NOT_FOUND,
            message="The Artifact does not exist or has expired",
        )
    return StreamingResponse(
        _storage(request).read(record.storage_key),
        media_type=record.mime_type,
        headers={
            "Content-Disposition": (
                f"attachment; filename*=UTF-8''{quote(record.filename, safe='')}"
            ),
            "Content-Length": str(record.size_bytes),
            "X-Content-SHA256": record.sha256,
        },
    )


@router.get(
    "/{task_id}/artifacts/{artifact_id}/download-url",
    operation_id="create_task_artifact_download_url",
    response_model=ArtifactDownloadResponse,
    responses={
        404: {"model": ErrorResponse},
        409: {"model": ErrorResponse},
    },
)
async def create_task_artifact_download_url(
    request: Request,
    task_id: Annotated[TaskId, Path()],
    artifact_id: Annotated[ArtifactId, Path()],
) -> ArtifactDownloadResponse:
    try:
        async with _database(request).session_factory() as session:
            record = await _artifact_repository(request).get(
                session,
                task_id=task_id,
                artifact_id=artifact_id,
                now=request.app.state.clock(),
            )
    except SQLAlchemyError as exc:
        raise _database_error() from exc
    if record is None or not await _storage(request).exists(record.storage_key):
        raise ApiError(
            status_code=404,
            code=ErrorCode.NOT_FOUND,
            message="The Artifact does not exist or has expired",
        )
    expires_seconds = request.app.state.settings.artifact_download_url_expires_seconds
    url = await _storage(request).presign_get(
        record.storage_key,
        expires_seconds=expires_seconds,
    )
    if url is None:
        raise ApiError(
            status_code=409,
            code=ErrorCode.CONFLICT,
            message="The configured Storage does not support signed download URLs",
        )
    return api_response(
        request,
        ArtifactDownload.model_validate(
            {
                "url": url,
                "expires_at": request.app.state.clock()
                + timedelta(seconds=expires_seconds),
            }
        ),
    )


@router.post(
    "/{task_id}/cancel",
    operation_id="cancel_task",
    response_model=TaskDetailResponse,
    responses=_action_responses,
)
async def cancel_task(
    request: Request,
    task_id: Annotated[TaskId, Path()],
) -> TaskDetailResponse:
    try:
        async with _database(request).session_factory() as session:
            try:
                record = await _repository(request).cancel(
                    session,
                    task_id=task_id,
                    now=request.app.state.clock(),
                )
            except TaskNotCancellableError as exc:
                raise ApiError(
                    status_code=409,
                    code=ErrorCode.TASK_NOT_CANCELLABLE,
                    message="The task is already terminal and cannot be cancelled",
                ) from exc
            if record is None:
                raise _not_found()
            detail = task_detail(record)
            await session.commit()
    except SQLAlchemyError as exc:
        raise _database_error() from exc
    return api_response(request, detail)


@router.post(
    "/{task_id}/retry",
    operation_id="retry_task",
    response_model=TaskDetailResponse,
    responses=_action_responses,
)
async def retry_task(
    request: Request,
    task_id: Annotated[TaskId, Path()],
) -> TaskDetailResponse:
    now = request.app.state.clock()
    try:
        async with _database(request).session_factory() as session:
            try:
                record = await _repository(request).retry(
                    session,
                    task_id=task_id,
                    now=now,
                )
            except TaskNotRetryableError as exc:
                raise ApiError(
                    status_code=409,
                    code=ErrorCode.CONFLICT,
                    message="Only failed or cancelled tasks can be retried",
                ) from exc
            if record is None:
                raise _not_found()
            detail = task_detail(record)
            await session.commit()
    except SQLAlchemyError as exc:
        raise _database_error() from exc
    await request.app.state.task_queue_notifier.publish(
        reason=QueueNoticeReason.TASK_RETRIED,
        task_id=record.task_id,
        occurred_at=now,
    )
    return api_response(request, detail)


__all__ = ["router"]
