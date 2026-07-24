"""APIKey-protected persistent dynamic system settings."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy.exc import SQLAlchemyError

from ...persistence import Database, SystemSettingRepository
from ...schema.error import ErrorCode
from ...schema.management import (
    SystemSettingsData,
    SystemSettingsResponse,
    UpdateSettingsRequest,
)
from ..authentication import require_api_key
from ..errors import ApiError
from ..responses import api_response


router = APIRouter(
    prefix="/api/v1/management/settings",
    tags=["settings"],
    dependencies=[Depends(require_api_key)],
)


def _database(request: Request) -> Database:
    database: Database | None = request.app.state.database
    if database is None:
        raise ApiError(
            status_code=503,
            code=ErrorCode.DEPENDENCY_UNAVAILABLE,
            message="The settings database is not configured",
            retryable=True,
        )
    return database


def _repository(request: Request) -> SystemSettingRepository:
    return request.app.state.system_setting_repository


async def _effective(request: Request) -> SystemSettingsData:
    try:
        async with _database(request).session_factory() as session:
            settings = await _repository(request).list_effective(
                session,
                defaults=request.app.state.settings,
            )
    except SQLAlchemyError as exc:
        raise ApiError(
            status_code=503,
            code=ErrorCode.DEPENDENCY_UNAVAILABLE,
            message="The system settings are unavailable",
            retryable=True,
        ) from exc
    return SystemSettingsData(settings=settings)


@router.get(
    "",
    operation_id="get_system_settings",
    response_model=SystemSettingsResponse,
)
async def get_system_settings(request: Request) -> SystemSettingsResponse:
    return api_response(request, await _effective(request))


@router.patch(
    "",
    operation_id="update_system_settings",
    response_model=SystemSettingsResponse,
)
async def update_system_settings(
    request: Request,
    body: UpdateSettingsRequest,
) -> SystemSettingsResponse:
    try:
        async with _database(request).session_factory() as session:
            await _repository(request).update(
                session,
                request=body,
                now=request.app.state.clock(),
            )
            await session.commit()
    except SQLAlchemyError as exc:
        raise ApiError(
            status_code=503,
            code=ErrorCode.DEPENDENCY_UNAVAILABLE,
            message="The system settings could not be updated",
            retryable=True,
        ) from exc
    return api_response(request, await _effective(request))


__all__ = ["router"]
