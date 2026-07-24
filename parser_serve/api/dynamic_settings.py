"""Resolve effective dynamic settings for HTTP request paths."""

from __future__ import annotations

from fastapi import Request
from sqlalchemy.exc import SQLAlchemyError

from ..persistence import Database, SystemSettingRepository
from ..schema.error import ErrorCode
from ..schema.management import SettingKey
from .errors import ApiError


async def effective_int_setting(request: Request, key: SettingKey) -> int:
    database: Database | None = request.app.state.database
    if database is None:
        defaults = request.app.state.settings
        return {
            SettingKey.MAXIMUM_UPLOAD_BYTES: defaults.maximum_upload_bytes,
            SettingKey.MAXIMUM_RESULT_JSON_BYTES: (defaults.maximum_result_json_bytes),
            SettingKey.CALLBACK_MAXIMUM_ATTEMPTS: (defaults.callback_maximum_attempts),
        }[key]
    repository: SystemSettingRepository = request.app.state.system_setting_repository
    try:
        async with database.session_factory() as session:
            return await repository.get_int(
                session,
                key=key,
                defaults=request.app.state.settings,
            )
    except SQLAlchemyError as exc:
        raise ApiError(
            status_code=503,
            code=ErrorCode.DEPENDENCY_UNAVAILABLE,
            message="The effective system setting is unavailable",
            retryable=True,
        ) from exc


__all__ = ["effective_int_setting"]
