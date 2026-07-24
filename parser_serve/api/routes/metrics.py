"""APIKey-protected Prometheus metrics endpoint."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy.exc import SQLAlchemyError
from starlette.responses import Response

from ...schema.error import ErrorCode
from ..authentication import require_api_key
from ..errors import ApiError


PROMETHEUS_CONTENT_TYPE = "text/plain; version=0.0.4; charset=utf-8"

router = APIRouter(
    tags=["observability"],
    dependencies=[Depends(require_api_key)],
)


@router.get(
    "/metrics",
    operation_id="get_metrics",
    response_class=Response,
    responses={
        200: {
            "description": "Prometheus text exposition format",
            "content": {
                "text/plain": {
                    "schema": {"type": "string"},
                }
            },
        }
    },
)
async def get_metrics(request: Request) -> Response:
    database = request.app.state.database
    if database is not None:
        try:
            async with database.session_factory() as session:
                await request.app.state.metrics.update_persistent(session)
        except SQLAlchemyError as exc:
            raise ApiError(
                status_code=503,
                code=ErrorCode.DEPENDENCY_UNAVAILABLE,
                message="Persistent metrics are unavailable",
                retryable=True,
            ) from exc
    return Response(
        content=request.app.state.metrics.render(),
        headers={"Content-Type": PROMETHEUS_CONTENT_TYPE},
    )


__all__ = ["PROMETHEUS_CONTENT_TYPE", "router"]
