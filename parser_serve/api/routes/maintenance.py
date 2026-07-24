"""APIKey-protected retention maintenance operations."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy.exc import SQLAlchemyError

from ...control import RetentionService
from ...schema.error import ErrorCode
from ...schema.maintenance import (
    RetentionRunResponse,
    RunRetentionRequest,
)
from ..authentication import require_api_key
from ..errors import ApiError
from ..responses import api_response


router = APIRouter(
    prefix="/api/v1/management/maintenance",
    tags=["maintenance"],
    dependencies=[Depends(require_api_key)],
)


@router.post(
    "/retention/run",
    operation_id="run_retention_cleanup",
    response_model=RetentionRunResponse,
)
async def run_retention_cleanup(
    request: Request,
    body: RunRetentionRequest,
) -> RetentionRunResponse:
    service: RetentionService | None = request.app.state.retention_service
    if service is None:
        raise ApiError(
            status_code=503,
            code=ErrorCode.DEPENDENCY_UNAVAILABLE,
            message="Retention maintenance is not configured",
            retryable=True,
        )
    try:
        result = await service.run_once(
            now=request.app.state.clock(),
            dry_run=body.dry_run,
            maximum_records=body.maximum_records,
        )
    except SQLAlchemyError as exc:
        raise ApiError(
            status_code=503,
            code=ErrorCode.DEPENDENCY_UNAVAILABLE,
            message="Retention maintenance database is unavailable",
            retryable=True,
        ) from exc
    return api_response(request, result)


__all__ = ["router"]
