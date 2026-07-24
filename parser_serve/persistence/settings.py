"""Persistent dynamic settings with deployment defaults."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..schema.base import JsonValue
from ..schema.management import (
    SettingKey,
    SettingSource,
    SystemSetting,
    UpdateSettingsRequest,
)
from ..settings import Settings
from .models import SystemSettingRecord


def deployment_setting_values(settings: Settings) -> dict[SettingKey, int]:
    return {
        SettingKey.MAXIMUM_UPLOAD_BYTES: settings.maximum_upload_bytes,
        SettingKey.MAXIMUM_RESULT_JSON_BYTES: settings.maximum_result_json_bytes,
        SettingKey.CALLBACK_MAXIMUM_ATTEMPTS: settings.callback_maximum_attempts,
    }


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


class SystemSettingRepository:
    async def list_effective(
        self,
        session: AsyncSession,
        *,
        defaults: Settings,
    ) -> list[SystemSetting]:
        records = {
            SettingKey(record.key): record
            for record in (
                await session.scalars(
                    select(SystemSettingRecord).order_by(SystemSettingRecord.key)
                )
            ).all()
        }
        return [
            (
                SystemSetting(
                    key=key,
                    value=records[key].value_payload,
                    source=SettingSource.DATABASE,
                    updated_at=_as_utc(records[key].updated_at),
                )
                if key in records
                else SystemSetting(
                    key=key,
                    value=value,
                    source=SettingSource.DEPLOYMENT,
                )
            )
            for key, value in deployment_setting_values(defaults).items()
        ]

    async def get_int(
        self,
        session: AsyncSession,
        *,
        key: SettingKey,
        defaults: Settings,
    ) -> int:
        record = await session.get(SystemSettingRecord, key.value)
        value: JsonValue = (
            record.value_payload
            if record is not None
            else deployment_setting_values(defaults)[key]
        )
        setting = SystemSetting(
            key=key,
            value=value,
            source=(
                SettingSource.DATABASE
                if record is not None
                else SettingSource.DEPLOYMENT
            ),
            updated_at=(_as_utc(record.updated_at) if record is not None else None),
        )
        assert isinstance(setting.value, int) and not isinstance(setting.value, bool)
        return setting.value

    async def update(
        self,
        session: AsyncSession,
        *,
        request: UpdateSettingsRequest,
        now: datetime,
    ) -> None:
        for update in request.settings:
            record = await session.scalar(
                select(SystemSettingRecord)
                .where(SystemSettingRecord.key == update.key.value)
                .with_for_update()
            )
            if record is None:
                session.add(
                    SystemSettingRecord(
                        key=update.key.value,
                        value_payload=update.value,
                        created_at=now,
                        updated_at=now,
                    )
                )
            else:
                record.value_payload = update.value
                record.updated_at = now
        await session.flush()


__all__ = ["SystemSettingRepository", "deployment_setting_values"]
