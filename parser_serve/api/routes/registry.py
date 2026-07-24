"""Backend Registry, Pipeline versioning, and task routing management APIs."""

from __future__ import annotations

import base64
import json
from datetime import UTC, datetime
from enum import StrEnum
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Path, Query, Request, status
from pydantic import TypeAdapter, ValidationError
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from ...control import (
    DefaultCatalogInstaller,
    TaskAlreadyRoutedError,
    TaskRouter,
    TaskRoutingUnavailableError,
    TaskSourceUnresolvedError,
)
from ...persistence import Database
from ...persistence.models import BackendRecord, PipelineRecord
from ...persistence.files import (
    UnsupportedFileTypeError,
    UploadedFileNotFoundError,
)
from ...persistence.registry import (
    BackendRepository,
    PipelinePublishError,
    PipelineRepository,
    RegistryConflictError,
    backend_detail,
    pipeline_definition,
)
from ...persistence.tasks import (
    PipelineNotFoundError,
    TaskRepository,
    task_detail,
)
from ...schema.backend import (
    BackendDetailResponse,
    BackendExecutionMode,
    BackendListQuery,
    BackendListResponse,
    BackendSortField,
    BackendStatus,
    CreateBackendRequest,
    UpdateBackendRequest,
)
from ...schema.common import (
    BackendId,
    MediaCategory,
    PageInfo,
    PipelineId,
    SortDirection,
    TaskId,
    UTCDateTime,
)
from ...schema.error import ErrorCode, ErrorResponse
from ...schema.defaults import (
    DefaultCatalogInitializationResponse,
    InitializeDefaultsRequest,
)
from ...schema.hardware import DeviceRuntime
from ...schema.pipeline import (
    CreatePipelineRequest,
    PipelineDetailResponse,
    PipelineListQuery,
    PipelineListResponse,
    PipelineSortField,
    PipelineStatus,
    PipelineTestRequest,
    PipelineValidationResponse,
)
from ...schema.queue import QueueNoticeReason
from ...schema.task import CreateTaskRequest, TaskDetailResponse, TaskOptions
from ..authentication import require_api_key
from ..errors import ApiError
from ..request_id import request_id_for
from ..responses import api_response


router = APIRouter(
    prefix="/api/v1/management",
    tags=["registry"],
    dependencies=[Depends(require_api_key)],
)

_backend_id_adapter = TypeAdapter(BackendId)
_utc_datetime_adapter = TypeAdapter(UTCDateTime)
_not_found_responses: dict[int | str, dict[str, object]] = {
    404: {"model": ErrorResponse}
}
_mutation_responses: dict[int | str, dict[str, object]] = {
    404: {"model": ErrorResponse},
    409: {"model": ErrorResponse},
}


def _database(request: Request) -> Database:
    database: Database | None = request.app.state.database
    if database is None:
        raise _database_error("The registry database is not configured")
    return database


def _database_error(message: str = "The registry database is unavailable") -> ApiError:
    return ApiError(
        status_code=503,
        code=ErrorCode.DEPENDENCY_UNAVAILABLE,
        message=message,
        retryable=True,
    )


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _encode_cursor(
    sort_by: StrEnum,
    sort_direction: SortDirection,
    value: datetime | str | int,
    identity: str | int,
) -> str:
    serialized = _as_utc(value).isoformat() if isinstance(value, datetime) else value
    payload = json.dumps(
        [sort_by.value, sort_direction.value, serialized, identity],
        separators=(",", ":"),
    ).encode()
    return base64.urlsafe_b64encode(payload).decode().rstrip("=")


def _decode_cursor(
    cursor: str | None,
    *,
    identity: str,
    sort_by: StrEnum,
    sort_direction: SortDirection,
    value_kind: Literal["datetime", "string", "integer"],
) -> tuple[datetime | str | int | None, str | int | None]:
    if cursor is None:
        return None, None
    try:
        padding = "=" * (-len(cursor) % 4)
        payload = json.loads(base64.urlsafe_b64decode(cursor + padding).decode("utf-8"))
        if (
            not isinstance(payload, list)
            or len(payload) != 4
            or payload[:2] != [sort_by.value, sort_direction.value]
        ):
            raise ValueError
        value: datetime | str | int
        if value_kind == "datetime":
            value = _utc_datetime_adapter.validate_python(payload[2])
        elif value_kind == "string":
            if not isinstance(payload[2], str):
                raise ValueError
            value = payload[2]
        else:
            if isinstance(payload[2], bool) or not isinstance(payload[2], int):
                raise ValueError
            value = payload[2]
        resolved_identity: str | int
        if identity == "backend":
            resolved_identity = _backend_id_adapter.validate_python(payload[3])
        else:
            if isinstance(payload[3], bool) or not isinstance(payload[3], int):
                raise ValueError
            resolved_identity = payload[3]
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
            message="The registry list cursor is invalid",
        ) from exc
    return value, resolved_identity


def _backend_sort_value(
    record: BackendRecord,
    sort_by: BackendSortField,
) -> datetime | str:
    if sort_by is BackendSortField.CREATED_AT:
        return record.created_at
    if sort_by is BackendSortField.UPDATED_AT:
        return record.updated_at
    return record.name


def _pipeline_sort_value(
    record: PipelineRecord,
    sort_by: PipelineSortField,
) -> datetime | str | int:
    if sort_by is PipelineSortField.CREATED_AT:
        return record.created_at
    if sort_by is PipelineSortField.UPDATED_AT:
        return record.updated_at
    if sort_by is PipelineSortField.NAME:
        return record.name
    return record.version


def backend_list_query(
    statuses: Annotated[list[BackendStatus] | None, Query()] = None,
    runtimes: Annotated[list[DeviceRuntime] | None, Query()] = None,
    media_category: Annotated[MediaCategory | None, Query()] = None,
    execution_mode: Annotated[BackendExecutionMode | None, Query()] = None,
    name_contains: Annotated[
        str | None,
        Query(min_length=1, max_length=128),
    ] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    cursor: Annotated[str | None, Query(min_length=1, max_length=1024)] = None,
    sort_by: Annotated[BackendSortField, Query()] = BackendSortField.CREATED_AT,
    sort_direction: Annotated[SortDirection, Query()] = SortDirection.DESC,
) -> BackendListQuery:
    return BackendListQuery(
        statuses=statuses or [],
        runtimes=runtimes or [],
        media_category=media_category,
        execution_mode=execution_mode,
        name_contains=name_contains,
        limit=limit,
        cursor=cursor,
        sort_by=sort_by,
        sort_direction=sort_direction,
    )


def pipeline_list_query(
    statuses: Annotated[list[PipelineStatus] | None, Query()] = None,
    media_category: Annotated[MediaCategory | None, Query()] = None,
    name_contains: Annotated[
        str | None,
        Query(min_length=1, max_length=128),
    ] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    cursor: Annotated[str | None, Query(min_length=1, max_length=1024)] = None,
    sort_by: Annotated[PipelineSortField, Query()] = PipelineSortField.CREATED_AT,
    sort_direction: Annotated[SortDirection, Query()] = SortDirection.DESC,
) -> PipelineListQuery:
    return PipelineListQuery(
        statuses=statuses or [],
        media_category=media_category,
        name_contains=name_contains,
        limit=limit,
        cursor=cursor,
        sort_by=sort_by,
        sort_direction=sort_direction,
    )


@router.post(
    "/defaults/initialize",
    operation_id="initialize_default_catalog",
    response_model=DefaultCatalogInitializationResponse,
    responses={409: {"model": ErrorResponse}},
)
async def initialize_default_catalog(
    request: Request,
    body: InitializeDefaultsRequest,
) -> DefaultCatalogInitializationResponse:
    try:
        async with _database(request).session_factory() as session:
            try:
                result = await DefaultCatalogInstaller().install(
                    session,
                    request=body,
                    now=request.app.state.clock(),
                )
                await session.commit()
            except IntegrityError as exc:
                raise RegistryConflictError from exc
    except RegistryConflictError as exc:
        raise ApiError(
            status_code=409,
            code=ErrorCode.CONFLICT,
            message="A concurrent default catalog initialization conflicted",
            retryable=True,
        ) from exc
    except SQLAlchemyError as exc:
        raise _database_error() from exc
    return api_response(request, result)


@router.post(
    "/backends",
    operation_id="create_backend",
    status_code=status.HTTP_201_CREATED,
    response_model=BackendDetailResponse,
    responses={409: {"model": ErrorResponse}},
)
async def create_backend(
    request: Request,
    body: CreateBackendRequest,
) -> BackendDetailResponse:
    repository: BackendRepository = request.app.state.backend_repository
    try:
        async with _database(request).session_factory() as session:
            try:
                record = await repository.create(
                    session,
                    request=body,
                    now=request.app.state.clock(),
                )
                await session.commit()
            except IntegrityError as exc:
                raise RegistryConflictError from exc
    except RegistryConflictError as exc:
        raise ApiError(
            status_code=409,
            code=ErrorCode.CONFLICT,
            message="The Backend name and version already exist",
        ) from exc
    except SQLAlchemyError as exc:
        raise _database_error() from exc
    return api_response(request, backend_detail(record))


@router.get(
    "/backends",
    operation_id="list_backends",
    response_model=BackendListResponse,
)
async def list_backends(
    request: Request,
    query: Annotated[BackendListQuery, Depends(backend_list_query)],
) -> BackendListResponse:
    cursor_value, cursor_identity = _decode_cursor(
        query.cursor,
        identity="backend",
        sort_by=query.sort_by,
        sort_direction=query.sort_direction,
        value_kind=("string" if query.sort_by is BackendSortField.NAME else "datetime"),
    )
    repository: BackendRepository = request.app.state.backend_repository
    try:
        async with _database(request).session_factory() as session:
            records = await repository.list(
                session,
                query=query,
                cursor_value=(
                    cursor_value if isinstance(cursor_value, (datetime, str)) else None
                ),
                cursor_backend_id=(
                    cursor_identity if isinstance(cursor_identity, str) else None
                ),
            )
    except SQLAlchemyError as exc:
        raise _database_error() from exc
    has_more = len(records) > query.limit
    page_records = records[: query.limit]
    return BackendListResponse(
        request_id=request_id_for(request),
        items=[backend_detail(record) for record in page_records],
        page=PageInfo(
            has_more=has_more,
            next_cursor=(
                _encode_cursor(
                    query.sort_by,
                    query.sort_direction,
                    _backend_sort_value(page_records[-1], query.sort_by),
                    page_records[-1].backend_id,
                )
                if has_more
                else None
            ),
        ),
    )


@router.get(
    "/backends/{backend_id}",
    operation_id="get_backend",
    response_model=BackendDetailResponse,
    responses=_not_found_responses,
)
async def get_backend(
    request: Request,
    backend_id: Annotated[BackendId, Path()],
) -> BackendDetailResponse:
    repository: BackendRepository = request.app.state.backend_repository
    try:
        async with _database(request).session_factory() as session:
            record = await repository.get(session, backend_id)
    except SQLAlchemyError as exc:
        raise _database_error() from exc
    if record is None:
        raise _backend_not_found()
    return api_response(request, backend_detail(record))


@router.patch(
    "/backends/{backend_id}",
    operation_id="update_backend",
    response_model=BackendDetailResponse,
    responses=_not_found_responses,
)
async def update_backend(
    request: Request,
    body: UpdateBackendRequest,
    backend_id: Annotated[BackendId, Path()],
) -> BackendDetailResponse:
    repository: BackendRepository = request.app.state.backend_repository
    try:
        async with _database(request).session_factory() as session:
            record = await repository.update(
                session,
                backend_id=backend_id,
                update=body,
                now=request.app.state.clock(),
            )
            if record is None:
                raise _backend_not_found()
            await session.commit()
    except SQLAlchemyError as exc:
        raise _database_error() from exc
    return api_response(request, backend_detail(record))


@router.post(
    "/pipelines",
    operation_id="create_pipeline",
    status_code=status.HTTP_201_CREATED,
    response_model=PipelineDetailResponse,
    responses={409: {"model": ErrorResponse}},
)
async def create_pipeline(
    request: Request,
    body: CreatePipelineRequest,
) -> PipelineDetailResponse:
    repository: PipelineRepository = request.app.state.pipeline_repository
    try:
        async with _database(request).session_factory() as session:
            try:
                record = await repository.create(
                    session,
                    request=body,
                    now=request.app.state.clock(),
                )
                await session.commit()
            except IntegrityError as exc:
                raise RegistryConflictError from exc
    except RegistryConflictError as exc:
        raise ApiError(
            status_code=409,
            code=ErrorCode.CONFLICT,
            message="A concurrent Pipeline version creation conflicted",
            retryable=True,
        ) from exc
    except SQLAlchemyError as exc:
        raise _database_error() from exc
    return api_response(request, pipeline_definition(record))


@router.get(
    "/pipelines",
    operation_id="list_pipelines",
    response_model=PipelineListResponse,
)
async def list_pipelines(
    request: Request,
    query: Annotated[PipelineListQuery, Depends(pipeline_list_query)],
) -> PipelineListResponse:
    cursor_value, cursor_identity = _decode_cursor(
        query.cursor,
        identity="pipeline",
        sort_by=query.sort_by,
        sort_direction=query.sort_direction,
        value_kind=(
            "string"
            if query.sort_by is PipelineSortField.NAME
            else (
                "integer" if query.sort_by is PipelineSortField.VERSION else "datetime"
            )
        ),
    )
    repository: PipelineRepository = request.app.state.pipeline_repository
    try:
        async with _database(request).session_factory() as session:
            records = await repository.list(
                session,
                query=query,
                cursor_value=cursor_value,
                cursor_record_id=(
                    cursor_identity if isinstance(cursor_identity, int) else None
                ),
            )
    except SQLAlchemyError as exc:
        raise _database_error() from exc
    has_more = len(records) > query.limit
    page_records = records[: query.limit]
    return PipelineListResponse(
        request_id=request_id_for(request),
        items=[pipeline_definition(record) for record in page_records],
        page=PageInfo(
            has_more=has_more,
            next_cursor=(
                _encode_cursor(
                    query.sort_by,
                    query.sort_direction,
                    _pipeline_sort_value(page_records[-1], query.sort_by),
                    page_records[-1].record_id,
                )
                if has_more
                else None
            ),
        ),
    )


@router.get(
    "/pipelines/{pipeline_id}/versions/{version}",
    operation_id="get_pipeline",
    response_model=PipelineDetailResponse,
    responses=_not_found_responses,
)
async def get_pipeline(
    request: Request,
    pipeline_id: Annotated[PipelineId, Path()],
    version: Annotated[int, Path(ge=1)],
) -> PipelineDetailResponse:
    repository: PipelineRepository = request.app.state.pipeline_repository
    try:
        async with _database(request).session_factory() as session:
            record = await repository.get(
                session,
                pipeline_id=pipeline_id,
                version=version,
            )
    except SQLAlchemyError as exc:
        raise _database_error() from exc
    if record is None:
        raise _pipeline_not_found()
    return api_response(request, pipeline_definition(record))


@router.post(
    "/pipelines/{pipeline_id}/versions/{version}/validate",
    operation_id="validate_pipeline",
    response_model=PipelineValidationResponse,
    responses=_not_found_responses,
)
async def validate_pipeline(
    request: Request,
    pipeline_id: Annotated[PipelineId, Path()],
    version: Annotated[int, Path(ge=1)],
) -> PipelineValidationResponse:
    repository: PipelineRepository = request.app.state.pipeline_repository
    try:
        async with _database(request).session_factory() as session:
            record = await repository.get(
                session,
                pipeline_id=pipeline_id,
                version=version,
            )
            if record is None:
                raise _pipeline_not_found()
            validation = await repository.validate(session, record)
    except SQLAlchemyError as exc:
        raise _database_error() from exc
    return api_response(request, validation)


@router.post(
    "/pipelines/{pipeline_id}/versions/{version}/test",
    operation_id="test_pipeline",
    status_code=status.HTTP_201_CREATED,
    response_model=TaskDetailResponse,
    responses={
        404: {"model": ErrorResponse},
        409: {"model": ErrorResponse},
        415: {"model": ErrorResponse},
    },
)
async def test_pipeline(
    request: Request,
    body: PipelineTestRequest,
    pipeline_id: Annotated[PipelineId, Path()],
    version: Annotated[int, Path(ge=1)],
) -> TaskDetailResponse:
    pipeline_repository: PipelineRepository = request.app.state.pipeline_repository
    task_repository: TaskRepository = request.app.state.task_repository
    task_router: TaskRouter = request.app.state.task_router
    now = request.app.state.clock()
    try:
        async with _database(request).session_factory() as session:
            pipeline = await pipeline_repository.get(
                session,
                pipeline_id=pipeline_id,
                version=version,
            )
            if pipeline is None:
                raise _pipeline_not_found()
            if pipeline.status not in {
                PipelineStatus.DRAFT.value,
                PipelineStatus.PUBLISHED.value,
            }:
                raise ApiError(
                    status_code=409,
                    code=ErrorCode.CONFLICT,
                    message="Only draft or published Pipeline versions can be tested",
                )
            validation = await pipeline_repository.validate(session, pipeline)
            if not validation.valid:
                raise ApiError(
                    status_code=409,
                    code=ErrorCode.BACKEND_NOT_AVAILABLE,
                    message="The Pipeline test cannot be routed",
                    retryable=True,
                    context={
                        "violations": [
                            violation.model_dump(mode="json")
                            for violation in validation.violations
                        ]
                    },
                )
            task_request = CreateTaskRequest(
                source=body.source,
                options=TaskOptions(
                    pipeline_id=pipeline_id,
                    pipeline_version=version,
                    **body.options.model_dump(),
                ),
                client_reference=body.client_reference,
            )
            record, _ = await task_repository.create(
                session,
                request=task_request,
                idempotency_key=None,
                now=now,
                allow_unpublished_pipeline=True,
            )
            routed = await task_router.route(
                session,
                task_id=record.task_id,
                now=now,
                allow_unpublished_pipeline=True,
            )
            if routed is None:  # pragma: no cover - created in this transaction
                raise RuntimeError("Pipeline test task disappeared before routing")
            detail = task_detail(routed)
            await session.commit()
    except PipelineNotFoundError as exc:  # pragma: no cover - preloaded above
        raise _pipeline_not_found() from exc
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
    except TaskSourceUnresolvedError as exc:
        raise ApiError(
            status_code=409,
            code=ErrorCode.CONFLICT,
            message="The Pipeline test source metadata is unresolved",
        ) from exc
    except TaskRoutingUnavailableError as exc:
        raise ApiError(
            status_code=409,
            code=ErrorCode.BACKEND_NOT_AVAILABLE,
            message=(
                "The Pipeline does not support the source or no compatible "
                "Backend is available"
            ),
            retryable=True,
        ) from exc
    except TaskAlreadyRoutedError as exc:  # pragma: no cover - newly created task
        raise ApiError(
            status_code=409,
            code=ErrorCode.CONFLICT,
            message="The Pipeline test task was already routed",
        ) from exc
    except SQLAlchemyError as exc:
        raise _database_error() from exc
    await request.app.state.task_queue_notifier.publish(
        reason=QueueNoticeReason.TASK_ROUTED,
        task_id=detail.task_id,
        occurred_at=now,
    )
    return api_response(request, detail)


@router.post(
    "/pipelines/{pipeline_id}/versions/{version}/publish",
    operation_id="publish_pipeline",
    response_model=PipelineDetailResponse,
    responses=_mutation_responses,
)
async def publish_pipeline(
    request: Request,
    pipeline_id: Annotated[PipelineId, Path()],
    version: Annotated[int, Path(ge=1)],
) -> PipelineDetailResponse:
    repository: PipelineRepository = request.app.state.pipeline_repository
    try:
        async with _database(request).session_factory() as session:
            try:
                record = await repository.publish(
                    session,
                    pipeline_id=pipeline_id,
                    version=version,
                    now=request.app.state.clock(),
                )
            except PipelinePublishError as exc:
                raise ApiError(
                    status_code=409,
                    code=ErrorCode.CONFLICT,
                    message="The Pipeline cannot be published",
                    context={
                        "violations": [
                            violation.model_dump(mode="json")
                            for violation in exc.validation.violations
                        ]
                    },
                ) from exc
            if record is None:
                raise _pipeline_not_found()
            await session.commit()
    except SQLAlchemyError as exc:
        raise _database_error() from exc
    return api_response(request, pipeline_definition(record))


@router.post(
    "/tasks/{task_id}/route",
    operation_id="route_task",
    response_model=TaskDetailResponse,
    responses=_mutation_responses,
)
async def route_task(
    request: Request,
    task_id: Annotated[TaskId, Path()],
) -> TaskDetailResponse:
    task_router: TaskRouter = request.app.state.task_router
    now = request.app.state.clock()
    try:
        async with _database(request).session_factory() as session:
            try:
                record = await task_router.route(
                    session,
                    task_id=task_id,
                    now=now,
                )
            except TaskSourceUnresolvedError as exc:
                raise ApiError(
                    status_code=409,
                    code=ErrorCode.CONFLICT,
                    message="The task source metadata is not resolved",
                ) from exc
            except TaskRoutingUnavailableError as exc:
                raise ApiError(
                    status_code=409,
                    code=ErrorCode.BACKEND_NOT_AVAILABLE,
                    message="No compatible published Pipeline and Backend are available",
                    retryable=True,
                ) from exc
            except TaskAlreadyRoutedError as exc:
                raise ApiError(
                    status_code=409,
                    code=ErrorCode.CONFLICT,
                    message="The task is not pending and cannot be routed",
                ) from exc
            if record is None:
                raise ApiError(
                    status_code=404,
                    code=ErrorCode.NOT_FOUND,
                    message="The task does not exist",
                )
            detail = task_detail(record)
            await session.commit()
    except SQLAlchemyError as exc:
        raise _database_error() from exc
    await request.app.state.task_queue_notifier.publish(
        reason=QueueNoticeReason.TASK_ROUTED,
        task_id=record.task_id,
        occurred_at=now,
    )
    return api_response(request, detail)


def _backend_not_found() -> ApiError:
    return ApiError(
        status_code=404,
        code=ErrorCode.NOT_FOUND,
        message="The Backend does not exist",
    )


def _pipeline_not_found() -> ApiError:
    return ApiError(
        status_code=404,
        code=ErrorCode.NOT_FOUND,
        message="The Pipeline version does not exist",
    )


__all__ = ["router"]
