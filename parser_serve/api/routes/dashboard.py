"""APIKey-protected operational dashboard aggregation."""

from __future__ import annotations

from datetime import timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request
from pydantic import ValidationError
from sqlalchemy.exc import SQLAlchemyError

from ...persistence import Database
from ...schema.common import BackendId, MediaCategory, PipelineId, UTCDateTime, WorkerId
from ...schema.dashboard import (
    DashboardQuery,
    DashboardResponse,
    MetricInterval,
)
from ...schema.error import ErrorCode
from ...schema.hardware import DeviceRuntime
from ..authentication import require_api_key
from ..errors import ApiError
from ..responses import api_response


router = APIRouter(
    prefix="/api/v1/management/dashboard",
    tags=["dashboard"],
    dependencies=[Depends(require_api_key)],
)


def dashboard_query(
    request: Request,
    start_time: Annotated[UTCDateTime | None, Query()] = None,
    end_time: Annotated[UTCDateTime | None, Query()] = None,
    interval: Annotated[MetricInterval, Query()] = MetricInterval.HOUR,
    pipeline_id: Annotated[PipelineId | None, Query()] = None,
    backend_id: Annotated[BackendId | None, Query()] = None,
    worker_id: Annotated[WorkerId | None, Query()] = None,
    runtime: Annotated[DeviceRuntime | None, Query()] = None,
    media_category: Annotated[MediaCategory | None, Query()] = None,
) -> DashboardQuery:
    resolved_end = end_time or request.app.state.clock()
    try:
        return DashboardQuery(
            start_time=start_time or resolved_end - timedelta(hours=24),
            end_time=resolved_end,
            interval=interval,
            pipeline_id=pipeline_id,
            backend_id=backend_id,
            worker_id=worker_id,
            runtime=runtime,
            media_category=media_category,
        )
    except ValidationError as exc:
        raise ApiError(
            status_code=422,
            code=ErrorCode.VALIDATION_ERROR,
            message="The dashboard time range and interval are invalid",
        ) from exc


@router.get(
    "/summary",
    operation_id="get_dashboard_summary",
    response_model=DashboardResponse,
)
async def get_dashboard_summary(
    request: Request,
    query: Annotated[DashboardQuery, Depends(dashboard_query)],
) -> DashboardResponse:
    database: Database | None = request.app.state.database
    if database is None:
        raise ApiError(
            status_code=503,
            code=ErrorCode.DEPENDENCY_UNAVAILABLE,
            message="The dashboard database is not configured",
            retryable=True,
        )
    try:
        async with database.session_factory() as session:
            data = await request.app.state.dashboard_service.summary(
                session,
                query=query,
                generated_at=request.app.state.clock(),
            )
    except SQLAlchemyError as exc:
        raise ApiError(
            status_code=503,
            code=ErrorCode.DEPENDENCY_UNAVAILABLE,
            message="Dashboard metrics are unavailable",
            retryable=True,
        ) from exc
    return api_response(request, data)


__all__ = ["router"]
