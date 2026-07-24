"""API key generation, hashing, and persistence operations."""

from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import Select, and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..schema.authentication import (
    ApiKeyListQuery,
    ApiKeyKind,
    ApiKeySortField,
    ApiKeyStatus,
    ApiKeySummary,
    ApiKeyValue,
    CreateApiKeyData,
    RotateApiKeyData,
    UpdateApiKeyRequest,
)
from .models import ApiKeyRecord


class LastActiveApiKeyError(Exception):
    """Raised when an operation would remove the final active database key."""


def generate_api_key() -> ApiKeyValue:
    return f"parser_{secrets.token_urlsafe(32)}"


def api_key_digest(api_key: str) -> bytes:
    return hashlib.sha256(api_key.encode("utf-8")).digest()


def api_key_prefix(api_key: str) -> str:
    return api_key[:15]


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _is_active(record: ApiKeyRecord, *, now: datetime) -> bool:
    expires_at = _as_utc(record.expires_at)
    return record.enabled and (expires_at is None or expires_at > now)


def api_key_summary(
    record: ApiKeyRecord,
    *,
    now: datetime,
) -> ApiKeySummary:
    expires_at = _as_utc(record.expires_at)
    if not record.enabled:
        status = ApiKeyStatus.DISABLED
    elif expires_at is not None and expires_at <= now:
        status = ApiKeyStatus.EXPIRED
    else:
        status = ApiKeyStatus.ACTIVE

    return ApiKeySummary(
        api_key_id=record.api_key_id,
        name=record.name,
        kind=ApiKeyKind(record.kind),
        worker_id=record.worker_id,
        prefix=record.prefix,
        status=status,
        created_at=_as_utc(record.created_at) or now,
        updated_at=_as_utc(record.updated_at) or now,
        expires_at=expires_at,
        last_used_at=_as_utc(record.last_used_at),
    )


class ApiKeyRepository:
    async def create(
        self,
        session: AsyncSession,
        *,
        name: str,
        expires_at: datetime | None,
        now: datetime,
        kind: ApiKeyKind = ApiKeyKind.ORDINARY,
        worker_id: str | None = None,
    ) -> CreateApiKeyData:
        api_key = generate_api_key()
        record = ApiKeyRecord(
            api_key_id=f"key_{uuid4().hex}",
            name=name,
            kind=kind.value,
            worker_id=worker_id,
            prefix=api_key_prefix(api_key),
            digest=api_key_digest(api_key),
            enabled=True,
            expires_at=expires_at,
            created_at=now,
            updated_at=now,
        )
        session.add(record)
        await session.flush()
        return CreateApiKeyData(
            api_key=api_key,
            summary=api_key_summary(record, now=now),
        )

    async def authenticate(
        self,
        session: AsyncSession,
        *,
        api_key: str,
        now: datetime,
        kind: ApiKeyKind = ApiKeyKind.ORDINARY,
    ) -> ApiKeyRecord | None:
        digest = api_key_digest(api_key)
        result = await session.execute(
            select(ApiKeyRecord).where(
                ApiKeyRecord.digest == digest,
                ApiKeyRecord.kind == kind.value,
            )
        )
        record = result.scalar_one_or_none()
        if record is None or not hmac.compare_digest(record.digest, digest):
            return None
        if not _is_active(record, now=now):
            return None

        record.last_used_at = now
        await session.flush()
        return record

    async def get(
        self,
        session: AsyncSession,
        api_key_id: str,
    ) -> ApiKeyRecord | None:
        return await session.get(ApiKeyRecord, api_key_id)

    async def list(
        self,
        session: AsyncSession,
        *,
        query: ApiKeyListQuery,
        now: datetime,
        cursor_value: datetime | str | None = None,
        cursor_api_key_id: str | None = None,
    ) -> list[ApiKeySummary]:
        statement: Select[tuple[ApiKeyRecord]] = select(ApiKeyRecord)
        if query.kinds:
            statement = statement.where(
                ApiKeyRecord.kind.in_([kind.value for kind in query.kinds])
            )
        if query.statuses:
            predicates = []
            if ApiKeyStatus.ACTIVE in query.statuses:
                predicates.append(
                    and_(
                        ApiKeyRecord.enabled.is_(True),
                        or_(
                            ApiKeyRecord.expires_at.is_(None),
                            ApiKeyRecord.expires_at > now,
                        ),
                    )
                )
            if ApiKeyStatus.DISABLED in query.statuses:
                predicates.append(ApiKeyRecord.enabled.is_(False))
            if ApiKeyStatus.EXPIRED in query.statuses:
                predicates.append(
                    and_(
                        ApiKeyRecord.enabled.is_(True),
                        ApiKeyRecord.expires_at.is_not(None),
                        ApiKeyRecord.expires_at <= now,
                    )
                )
            statement = statement.where(or_(*predicates))
        if query.name_contains is not None:
            escaped = (
                query.name_contains.replace("\\", "\\\\")
                .replace("%", "\\%")
                .replace("_", "\\_")
            )
            statement = statement.where(
                ApiKeyRecord.name.ilike(f"%{escaped}%", escape="\\")
            )
        sort_column = {
            ApiKeySortField.CREATED_AT: ApiKeyRecord.created_at,
            ApiKeySortField.UPDATED_AT: ApiKeyRecord.updated_at,
            ApiKeySortField.NAME: ApiKeyRecord.name,
        }[query.sort_by]
        if cursor_value is not None and cursor_api_key_id is not None:
            comparison = (
                sort_column > cursor_value
                if query.sort_direction.value == "asc"
                else sort_column < cursor_value
            )
            id_comparison = (
                ApiKeyRecord.api_key_id > cursor_api_key_id
                if query.sort_direction.value == "asc"
                else ApiKeyRecord.api_key_id < cursor_api_key_id
            )
            statement = statement.where(
                or_(
                    comparison,
                    and_(
                        sort_column == cursor_value,
                        id_comparison,
                    ),
                )
            )
        ordering = (
            (sort_column.asc(), ApiKeyRecord.api_key_id.asc())
            if query.sort_direction.value == "asc"
            else (sort_column.desc(), ApiKeyRecord.api_key_id.desc())
        )
        statement = statement.order_by(*ordering).limit(query.limit + 1)
        records = (await session.scalars(statement)).all()
        return [api_key_summary(record, now=now) for record in records]

    async def update(
        self,
        session: AsyncSession,
        *,
        api_key_id: str,
        update: UpdateApiKeyRequest,
        now: datetime,
    ) -> ApiKeyRecord | None:
        record = await self._get_for_update(session, api_key_id)
        if record is None:
            return None

        effective_enabled = (
            update.enabled if update.enabled is not None else record.enabled
        )
        effective_expiry = (
            update.expires_at
            if update.expires_at is not None
            else _as_utc(record.expires_at)
        )
        remains_active = effective_enabled and (
            effective_expiry is None or effective_expiry > now
        )
        if (
            record.kind == ApiKeyKind.ORDINARY.value
            and _is_active(record, now=now)
            and not remains_active
        ):
            await self._require_another_active_key(
                session,
                excluding_api_key_id=api_key_id,
                now=now,
            )

        if update.name is not None:
            record.name = update.name
        if update.enabled is not None:
            record.enabled = update.enabled
        if update.expires_at is not None:
            record.expires_at = update.expires_at
        record.updated_at = now
        await session.flush()
        return record

    async def set_enabled(
        self,
        session: AsyncSession,
        *,
        api_key_id: str,
        enabled: bool,
        now: datetime,
    ) -> ApiKeyRecord | None:
        return await self.update(
            session,
            api_key_id=api_key_id,
            update=UpdateApiKeyRequest(enabled=enabled),
            now=now,
        )

    async def rotate(
        self,
        session: AsyncSession,
        *,
        api_key_id: str,
        now: datetime,
    ) -> RotateApiKeyData | None:
        record = await self._get_for_update(session, api_key_id)
        if record is None:
            return None
        api_key = generate_api_key()
        record.prefix = api_key_prefix(api_key)
        record.digest = api_key_digest(api_key)
        record.updated_at = now
        await session.flush()
        return RotateApiKeyData(
            api_key=api_key,
            summary=api_key_summary(record, now=now),
            previous_key_valid_until=None,
        )

    async def delete(
        self,
        session: AsyncSession,
        *,
        api_key_id: str,
        now: datetime,
    ) -> bool:
        record = await self._get_for_update(session, api_key_id)
        if record is None:
            return False
        if record.kind == ApiKeyKind.ORDINARY.value and _is_active(record, now=now):
            await self._require_another_active_key(
                session,
                excluding_api_key_id=api_key_id,
                now=now,
            )
        await session.delete(record)
        await session.flush()
        return True

    async def _get_for_update(
        self,
        session: AsyncSession,
        api_key_id: str,
    ) -> ApiKeyRecord | None:
        result = await session.execute(
            select(ApiKeyRecord)
            .where(ApiKeyRecord.api_key_id == api_key_id)
            .with_for_update()
        )
        return result.scalar_one_or_none()

    async def _require_another_active_key(
        self,
        session: AsyncSession,
        *,
        excluding_api_key_id: str,
        now: datetime,
    ) -> None:
        active_count = await session.scalar(
            select(func.count())
            .select_from(ApiKeyRecord)
            .where(
                ApiKeyRecord.api_key_id != excluding_api_key_id,
                ApiKeyRecord.kind == ApiKeyKind.ORDINARY.value,
                ApiKeyRecord.enabled.is_(True),
                or_(
                    ApiKeyRecord.expires_at.is_(None),
                    ApiKeyRecord.expires_at > now,
                ),
            )
        )
        if active_count == 0:
            raise LastActiveApiKeyError


__all__ = [
    "ApiKeyRepository",
    "LastActiveApiKeyError",
    "api_key_digest",
    "api_key_prefix",
    "api_key_summary",
    "generate_api_key",
]
