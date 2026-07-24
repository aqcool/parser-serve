"""Process health and dependency readiness endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Request
from sqlalchemy import text

from ...schema.common import HealthData, HealthResponse, HealthStatus
from ...schema.management import (
    ComponentHealth,
    SystemHealthData,
)
from ...schema.common import ApiResponse
from ..responses import api_response


router = APIRouter(tags=["health"])


@router.get(
    "/health",
    operation_id="get_health",
    response_model=HealthResponse,
)
async def get_health(request: Request) -> HealthResponse:
    settings = request.app.state.settings
    return api_response(
        request,
        HealthData(
            status=HealthStatus.HEALTHY,
            version=settings.app_version,
            timestamp=request.app.state.clock(),
        ),
    )


@router.get(
    "/ready",
    operation_id="get_readiness",
    response_model=ApiResponse[SystemHealthData],
)
async def get_readiness(request: Request) -> ApiResponse[SystemHealthData]:
    checked_at = request.app.state.clock()
    components = [
        ComponentHealth(
            name="api",
            healthy=True,
            checked_at=checked_at,
        )
    ]
    try:
        await request.app.state.storage.exists(
            "_parser_serve_health/readiness",
        )
    except Exception as exc:
        components.append(
            ComponentHealth(
                name="storage",
                healthy=False,
                message=f"Storage check failed: {type(exc).__name__}",
                checked_at=checked_at,
            )
        )
    else:
        components.append(
            ComponentHealth(
                name="storage",
                healthy=True,
                checked_at=checked_at,
            )
        )
    database = request.app.state.database
    if database is not None:
        try:
            async with database.engine.connect() as connection:
                await connection.execute(text("SELECT 1"))
        except Exception as exc:
            components.append(
                ComponentHealth(
                    name="database",
                    healthy=False,
                    message=f"Database check failed: {type(exc).__name__}",
                    checked_at=checked_at,
                )
            )
        else:
            components.append(
                ComponentHealth(
                    name="database",
                    healthy=True,
                    checked_at=checked_at,
                )
            )
    try:
        await request.app.state.task_queue.check()
    except Exception as exc:
        components.append(
            ComponentHealth(
                name="task_queue",
                healthy=False,
                message=f"Task queue check failed: {type(exc).__name__}",
                checked_at=checked_at,
            )
        )
    else:
        components.append(
            ComponentHealth(
                name="task_queue",
                healthy=True,
                checked_at=checked_at,
            )
        )
    return api_response(
        request,
        SystemHealthData(
            healthy=all(component.healthy for component in components),
            components=components,
        ),
    )


__all__ = ["router"]
