"""Worker internal protocol and externally accessible Worker management APIs."""

from __future__ import annotations

import base64
import json
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query, Request
from pydantic import TypeAdapter, ValidationError
from sqlalchemy.exc import SQLAlchemyError

from ...control import (
    InvalidLeaseError,
    LeaseExpiredError,
    StageExecutionConflictError,
    StageScheduler,
    WorkerUnavailableError,
)
from ...persistence import Database
from ...persistence.models import WorkerRecord
from ...queue import TaskQueueUnavailableError
from ...persistence.workers import (
    StaleHeartbeatError,
    UnknownHeartbeatDeviceError,
    WorkerRepository,
    worker_detail,
)
from ...schema.common import PageInfo, SortDirection, StageId, UTCDateTime, WorkerId
from ...schema.error import ErrorCode, ErrorResponse
from ...schema.hardware import DeviceRuntime
from ...schema.management import (
    UpdateWorkerRequest,
    WorkerListQuery,
    WorkerSortField,
)
from ...schema.queue import QueueNoticeReason
from ...schema.worker import (
    CompleteStageRequest,
    LeasedStage,
    RenewStageLeaseRequest,
    RenewStageLeaseResponse,
    StageExecutionResponse,
    StageProgressRequest,
    StartStageRequest,
    WorkerDetailResponse,
    WorkerHeartbeatData,
    WorkerHeartbeatRequest,
    WorkerHeartbeatResponse,
    WorkerLeaseData,
    WorkerLeaseRequest,
    WorkerLeaseResponse,
    WorkerListResponse,
    WorkerReconcileData,
    WorkerReconcileResponse,
    WorkerRegistrationData,
    WorkerRegistrationRequest,
    WorkerRegistrationResponse,
    WorkerStatus,
)
from ..authentication import require_api_key, require_worker_api_key
from ..errors import ApiError
from ..request_id import request_id_for
from ..responses import api_response


internal_router = APIRouter(
    prefix="/internal/v1/workers",
    tags=["worker-internal"],
    dependencies=[Depends(require_worker_api_key)],
)
management_router = APIRouter(
    prefix="/api/v1/management/workers",
    tags=["workers"],
    dependencies=[Depends(require_api_key)],
)

_worker_id_adapter = TypeAdapter(WorkerId)
_utc_datetime_adapter = TypeAdapter(UTCDateTime)
_not_found_responses: dict[int | str, dict[str, object]] = {
    404: {"model": ErrorResponse}
}
_execution_responses: dict[int | str, dict[str, object]] = {
    404: {"model": ErrorResponse},
    409: {"model": ErrorResponse},
}


def _database(request: Request) -> Database:
    database: Database | None = request.app.state.database
    if database is None:
        raise _database_error("The Worker database is not configured")
    return database


def _database_error(message: str = "The Worker database is unavailable") -> ApiError:
    return ApiError(
        status_code=503,
        code=ErrorCode.DEPENDENCY_UNAVAILABLE,
        message=message,
        retryable=True,
    )


def _not_found(subject: str) -> ApiError:
    return ApiError(
        status_code=404,
        code=ErrorCode.NOT_FOUND,
        message=f"The {subject} does not exist",
    )


def _require_worker_identity(request: Request, worker_id: str) -> None:
    authenticated_worker_id = getattr(
        request.state,
        "authenticated_worker_id",
        None,
    )
    if authenticated_worker_id is not None and authenticated_worker_id != worker_id:
        raise ApiError(
            status_code=401,
            code=ErrorCode.AUTHENTICATION_FAILED,
            message="The Worker API key is bound to a different worker_id",
        )


def _lease_error(exc: Exception) -> ApiError:
    if isinstance(exc, LeaseExpiredError):
        message = "The Stage lease has expired"
    elif isinstance(exc, InvalidLeaseError):
        message = "The Stage lease token or owner is invalid"
    else:
        message = "The Stage is not in the required execution state"
    return ApiError(
        status_code=409,
        code=ErrorCode.CONFLICT,
        message=message,
    )


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _worker_sort_value(
    record: WorkerRecord,
    sort_by: WorkerSortField,
) -> datetime | str:
    if sort_by is WorkerSortField.CREATED_AT:
        return record.created_at
    if sort_by is WorkerSortField.UPDATED_AT:
        return record.updated_at
    return record.name


def _encode_cursor(record: WorkerRecord, query: WorkerListQuery) -> str:
    value = _worker_sort_value(record, query.sort_by)
    serialized = _as_utc(value).isoformat() if isinstance(value, datetime) else value
    payload = json.dumps(
        [
            query.sort_by.value,
            query.sort_direction.value,
            serialized,
            record.worker_id,
        ],
        separators=(",", ":"),
    ).encode()
    return base64.urlsafe_b64encode(payload).decode().rstrip("=")


def _decode_cursor(
    query: WorkerListQuery,
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
        if query.sort_by is WorkerSortField.NAME:
            if not isinstance(payload[2], str):
                raise ValueError
            value = payload[2]
        else:
            value = _utc_datetime_adapter.validate_python(payload[2])
        worker_id = _worker_id_adapter.validate_python(payload[3])
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
            message="The Worker list cursor is invalid",
        ) from exc
    return value, worker_id


def worker_list_query(
    statuses: Annotated[list[WorkerStatus] | None, Query()] = None,
    runtimes: Annotated[list[DeviceRuntime] | None, Query()] = None,
    labels: Annotated[list[str] | None, Query()] = None,
    name_contains: Annotated[
        str | None,
        Query(min_length=1, max_length=128),
    ] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    cursor: Annotated[str | None, Query(min_length=1, max_length=1024)] = None,
    sort_by: Annotated[WorkerSortField, Query()] = WorkerSortField.CREATED_AT,
    sort_direction: Annotated[SortDirection, Query()] = SortDirection.DESC,
) -> WorkerListQuery:
    parsed_labels: dict[str, str] = {}
    for label in labels or []:
        key, separator, value = label.partition("=")
        if not separator or not key or not value:
            raise ApiError(
                status_code=422,
                code=ErrorCode.VALIDATION_ERROR,
                message="Worker labels must use key=value format",
            )
        parsed_labels[key] = value
    return WorkerListQuery(
        statuses=statuses or [],
        runtimes=runtimes or [],
        labels=parsed_labels,
        name_contains=name_contains,
        limit=limit,
        cursor=cursor,
        sort_by=sort_by,
        sort_direction=sort_direction,
    )


@internal_router.post(
    "/register",
    operation_id="register_worker",
    response_model=WorkerRegistrationResponse,
)
async def register_worker(
    request: Request,
    body: WorkerRegistrationRequest,
) -> WorkerRegistrationResponse:
    _require_worker_identity(request, body.worker_id)
    repository: WorkerRepository = request.app.state.worker_repository
    now = request.app.state.clock()
    try:
        async with _database(request).session_factory() as session:
            record = await repository.register(
                session,
                request=body,
                now=now,
            )
            await session.commit()
    except SQLAlchemyError as exc:
        raise _database_error() from exc
    settings = request.app.state.settings
    return api_response(
        request,
        WorkerRegistrationData(
            worker_id=record.worker_id,
            accepted=record.enabled,
            heartbeat_interval_seconds=settings.worker_heartbeat_interval_seconds,
            lease_duration_seconds=settings.stage_lease_duration_seconds,
            registered_at=now,
        ),
    )


@internal_router.post(
    "/heartbeat",
    operation_id="heartbeat_worker",
    response_model=WorkerHeartbeatResponse,
    responses=_execution_responses,
)
async def heartbeat_worker(
    request: Request,
    body: WorkerHeartbeatRequest,
) -> WorkerHeartbeatResponse:
    _require_worker_identity(request, body.worker_id)
    repository: WorkerRepository = request.app.state.worker_repository
    try:
        async with _database(request).session_factory() as session:
            try:
                record = await repository.heartbeat(
                    session,
                    request=body,
                    now=request.app.state.clock(),
                )
            except StaleHeartbeatError as exc:
                raise ApiError(
                    status_code=409,
                    code=ErrorCode.CONFLICT,
                    message="Heartbeat sequence must increase monotonically",
                ) from exc
            except UnknownHeartbeatDeviceError as exc:
                raise ApiError(
                    status_code=422,
                    code=ErrorCode.VALIDATION_ERROR,
                    message="Heartbeat usage references an unregistered device",
                ) from exc
            if record is None:
                raise _not_found("Worker")
            await session.commit()
    except SQLAlchemyError as exc:
        raise _database_error() from exc
    return api_response(
        request,
        WorkerHeartbeatData(
            accepted=record.enabled,
            next_heartbeat_seconds=request.app.state.settings.worker_heartbeat_interval_seconds,
            should_drain=record.status == WorkerStatus.DRAINING.value,
        ),
    )


@internal_router.post(
    "/{worker_id}/drain",
    operation_id="drain_worker_self",
    response_model=WorkerDetailResponse,
    responses=_not_found_responses,
)
async def drain_worker_self(
    request: Request,
    worker_id: Annotated[WorkerId, Path()],
) -> WorkerDetailResponse:
    _require_worker_identity(request, worker_id)
    repository: WorkerRepository = request.app.state.worker_repository
    try:
        async with _database(request).session_factory() as session:
            record = await repository.update(
                session,
                worker_id=worker_id,
                update=UpdateWorkerRequest(draining=True),
                now=request.app.state.clock(),
            )
            if record is None:
                raise _not_found("Worker")
            await session.commit()
    except SQLAlchemyError as exc:
        raise _database_error() from exc
    return api_response(request, worker_detail(record))


@internal_router.post(
    "/lease",
    operation_id="lease_stages",
    response_model=WorkerLeaseResponse,
    responses={409: {"model": ErrorResponse}},
)
async def lease_stages(
    request: Request,
    body: WorkerLeaseRequest,
) -> WorkerLeaseResponse:
    _require_worker_identity(request, body.worker_id)
    scheduler: StageScheduler = request.app.state.stage_scheduler

    async def try_lease() -> list[LeasedStage]:
        async with _database(request).session_factory() as session:
            try:
                selected = await scheduler.lease(
                    session,
                    request=body,
                    now=request.app.state.clock(),
                )
            except WorkerUnavailableError as exc:
                raise ApiError(
                    status_code=409,
                    code=ErrorCode.WORKER_NOT_AVAILABLE,
                    message="The Worker cannot accept Stage leases",
                    retryable=True,
                ) from exc
            await session.commit()
            return selected

    cursor: str | None = None
    if body.wait_seconds > 0:
        try:
            cursor = await request.app.state.task_queue.snapshot()
        except TaskQueueUnavailableError:
            request.app.state.logger.warning(
                "Task queue snapshot failed; falling back to database polling"
            )
    try:
        leases = await try_lease()
        wait_seconds = min(
            body.wait_seconds,
            request.app.state.settings.worker_lease_wait_maximum_seconds,
        )
        if not leases and cursor is not None and wait_seconds > 0:
            try:
                await request.app.state.task_queue.wait(
                    after=cursor,
                    timeout_seconds=wait_seconds,
                )
            except TaskQueueUnavailableError:
                request.app.state.logger.warning(
                    "Task queue wait failed; falling back to database polling"
                )
            leases = await try_lease()
    except SQLAlchemyError as exc:
        raise _database_error() from exc
    return api_response(request, WorkerLeaseData(leases=leases))


@internal_router.post(
    "/stages/{stage_id}/renew",
    operation_id="renew_stage_lease",
    response_model=RenewStageLeaseResponse,
    responses=_execution_responses,
)
async def renew_stage_lease(
    request: Request,
    body: RenewStageLeaseRequest,
    stage_id: Annotated[StageId, Path()],
) -> RenewStageLeaseResponse:
    _require_worker_identity(request, body.worker_id)
    scheduler: StageScheduler = request.app.state.stage_scheduler
    try:
        async with _database(request).session_factory() as session:
            try:
                data = await scheduler.renew(
                    session,
                    stage_id=stage_id,
                    worker_id=body.worker_id,
                    lease_token=body.lease_token,
                    now=request.app.state.clock(),
                )
            except (
                InvalidLeaseError,
                LeaseExpiredError,
                StageExecutionConflictError,
            ) as exc:
                raise _lease_error(exc) from exc
            if data is None:
                raise _not_found("Stage")
            await session.commit()
    except SQLAlchemyError as exc:
        raise _database_error() from exc
    return api_response(request, data)


@internal_router.post(
    "/stages/{stage_id}/start",
    operation_id="start_stage",
    response_model=StageExecutionResponse,
    responses=_execution_responses,
)
async def start_stage(
    request: Request,
    body: StartStageRequest,
    stage_id: Annotated[StageId, Path()],
) -> StageExecutionResponse:
    _require_worker_identity(request, body.worker_id)
    return await _execute_stage_action(
        request,
        stage_id=stage_id,
        action="start",
        body=body,
    )


@internal_router.post(
    "/stages/{stage_id}/progress",
    operation_id="update_stage_progress",
    response_model=StageExecutionResponse,
    responses=_execution_responses,
)
async def update_stage_progress(
    request: Request,
    body: StageProgressRequest,
    stage_id: Annotated[StageId, Path()],
) -> StageExecutionResponse:
    _require_worker_identity(request, body.worker_id)
    return await _execute_stage_action(
        request,
        stage_id=stage_id,
        action="progress",
        body=body,
    )


@internal_router.post(
    "/stages/{stage_id}/complete",
    operation_id="complete_stage",
    response_model=StageExecutionResponse,
    responses=_execution_responses,
)
async def complete_stage(
    request: Request,
    body: CompleteStageRequest,
    stage_id: Annotated[StageId, Path()],
) -> StageExecutionResponse:
    _require_worker_identity(request, body.worker_id)
    return await _execute_stage_action(
        request,
        stage_id=stage_id,
        action="complete",
        body=body,
    )


async def _execute_stage_action(
    request: Request,
    *,
    stage_id: str,
    action: str,
    body: StartStageRequest | StageProgressRequest | CompleteStageRequest,
) -> StageExecutionResponse:
    scheduler: StageScheduler = request.app.state.stage_scheduler
    try:
        async with _database(request).session_factory() as session:
            try:
                if action == "start" and isinstance(body, StartStageRequest):
                    data = await scheduler.start(
                        session,
                        stage_id=stage_id,
                        worker_id=body.worker_id,
                        lease_token=body.lease_token,
                        now=request.app.state.clock(),
                    )
                elif action == "progress" and isinstance(
                    body,
                    StageProgressRequest,
                ):
                    data = await scheduler.progress(
                        session,
                        stage_id=stage_id,
                        request=body,
                        now=request.app.state.clock(),
                    )
                elif action == "complete" and isinstance(
                    body,
                    CompleteStageRequest,
                ):
                    data = await scheduler.complete(
                        session,
                        stage_id=stage_id,
                        request=body,
                        now=request.app.state.clock(),
                    )
                else:
                    raise RuntimeError("invalid Stage action dispatch")
            except (
                InvalidLeaseError,
                LeaseExpiredError,
                StageExecutionConflictError,
            ) as exc:
                raise _lease_error(exc) from exc
            if data is None:
                raise _not_found("Stage")
            await session.commit()
    except SQLAlchemyError as exc:
        raise _database_error() from exc
    if action == "complete":
        await request.app.state.task_queue_notifier.publish(
            reason=QueueNoticeReason.STAGE_COMPLETED,
            task_id=data.task_id,
            stage_id=data.stage_id,
            occurred_at=request.app.state.clock(),
        )
    return api_response(request, data)


@management_router.get(
    "",
    operation_id="list_workers",
    response_model=WorkerListResponse,
)
async def list_workers(
    request: Request,
    query: Annotated[WorkerListQuery, Depends(worker_list_query)],
) -> WorkerListResponse:
    cursor_value, cursor_worker_id = _decode_cursor(query)
    repository: WorkerRepository = request.app.state.worker_repository
    try:
        async with _database(request).session_factory() as session:
            records = await repository.list(
                session,
                query=query,
                cursor_value=cursor_value,
                cursor_worker_id=cursor_worker_id,
            )
    except SQLAlchemyError as exc:
        raise _database_error() from exc
    has_more = len(records) > query.limit
    page_records = records[: query.limit]
    return WorkerListResponse(
        request_id=request_id_for(request),
        items=[worker_detail(record) for record in page_records],
        page=PageInfo(
            has_more=has_more,
            next_cursor=(_encode_cursor(page_records[-1], query) if has_more else None),
        ),
    )


@management_router.get(
    "/{worker_id}",
    operation_id="get_worker",
    response_model=WorkerDetailResponse,
    responses=_not_found_responses,
)
async def get_worker(
    request: Request,
    worker_id: Annotated[WorkerId, Path()],
) -> WorkerDetailResponse:
    repository: WorkerRepository = request.app.state.worker_repository
    try:
        async with _database(request).session_factory() as session:
            record = await repository.get(session, worker_id)
    except SQLAlchemyError as exc:
        raise _database_error() from exc
    if record is None:
        raise _not_found("Worker")
    return api_response(request, worker_detail(record))


@management_router.patch(
    "/{worker_id}",
    operation_id="update_worker",
    response_model=WorkerDetailResponse,
    responses=_not_found_responses,
)
async def update_worker(
    request: Request,
    body: UpdateWorkerRequest,
    worker_id: Annotated[WorkerId, Path()],
) -> WorkerDetailResponse:
    repository: WorkerRepository = request.app.state.worker_repository
    try:
        async with _database(request).session_factory() as session:
            record = await repository.update(
                session,
                worker_id=worker_id,
                update=body,
                now=request.app.state.clock(),
            )
            if record is None:
                raise _not_found("Worker")
            await session.commit()
    except SQLAlchemyError as exc:
        raise _database_error() from exc
    return api_response(request, worker_detail(record))


@management_router.post(
    "/reconcile",
    operation_id="reconcile_workers",
    response_model=WorkerReconcileResponse,
)
async def reconcile_workers(request: Request) -> WorkerReconcileResponse:
    now = request.app.state.clock()
    repository: WorkerRepository = request.app.state.worker_repository
    scheduler: StageScheduler = request.app.state.stage_scheduler
    try:
        async with _database(request).session_factory() as session:
            offline = await repository.mark_offline(
                session,
                now=now,
                offline_after_seconds=request.app.state.settings.worker_offline_after_seconds,
            )
            requeued = await scheduler.requeue_expired(session, now=now)
            await session.commit()
    except SQLAlchemyError as exc:
        raise _database_error() from exc
    if requeued:
        await request.app.state.task_queue_notifier.publish(
            reason=QueueNoticeReason.LEASE_REQUEUED,
            occurred_at=now,
        )
    return api_response(
        request,
        WorkerReconcileData(
            offline_worker_ids=offline,
            requeued_stage_ids=requeued,
        ),
    )


__all__ = ["internal_router", "management_router"]
