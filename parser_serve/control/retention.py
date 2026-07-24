"""Database and object-storage retention lifecycle."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

from sqlalchemy import or_, select, update
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from ..persistence import Database
from ..persistence.models import (
    ArtifactRecord,
    EventRecord,
    StageRecord,
    TaskRecord,
    UploadedFileRecord,
)
from ..schema.maintenance import RetentionRunData
from ..schema.task import TaskStatus
from ..storage import Storage


_ACTIVE_TASK_STATUSES = {
    TaskStatus.PENDING.value,
    TaskStatus.LEASED.value,
    TaskStatus.RUNNING.value,
}
_CALLBACK_SOURCE_EVENTS = {
    "task.created",
    "task.status_changed",
    "task.progress_updated",
}


class RetentionService:
    def __init__(
        self,
        *,
        database: Database,
        storage: Storage,
        uploaded_file_retention_seconds: int | None,
        artifact_retention_seconds: int | None,
        event_retention_seconds: int | None,
        batch_size: int = 500,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if batch_size < 1:
            raise ValueError("retention batch_size must be greater than zero")
        for value in (
            uploaded_file_retention_seconds,
            artifact_retention_seconds,
            event_retention_seconds,
        ):
            if value is not None and value < 1:
                raise ValueError("retention durations must be positive")
        self.database = database
        self.storage = storage
        self.uploaded_file_retention_seconds = uploaded_file_retention_seconds
        self.artifact_retention_seconds = artifact_retention_seconds
        self.event_retention_seconds = event_retention_seconds
        self.batch_size = batch_size
        self.clock = clock or (lambda: datetime.now(UTC))
        self.logger = logging.getLogger("parser_serve.retention")

    async def run_once(
        self,
        *,
        now: datetime | None = None,
        dry_run: bool = False,
        maximum_records: int | None = None,
    ) -> RetentionRunData:
        current = now or self.clock()
        limit = maximum_records if maximum_records is not None else self.batch_size
        if not 1 <= limit <= 10_000:
            raise ValueError("maximum_records must be between 1 and 10000")
        async with self.database.session_factory() as session:
            active_file_ids = {
                str(source["file_id"])
                for source in await session.scalars(
                    select(TaskRecord.source_payload).where(
                        TaskRecord.status.in_(_ACTIVE_TASK_STATUSES)
                    )
                )
                if source.get("type") == "uploaded_file"
                and isinstance(source.get("file_id"), str)
            }
            active_task_ids = set(
                await session.scalars(
                    select(TaskRecord.task_id).where(
                        TaskRecord.status.in_(_ACTIVE_TASK_STATUSES)
                    )
                )
            )
            uploads = await self._expired_uploads(
                session,
                now=current,
                limit=limit,
            )
            eligible_uploads = [
                record for record in uploads if record.file_id not in active_file_ids
            ]
            skipped_uploads = len(uploads) - len(eligible_uploads)
            artifacts = await self._expired_artifacts(
                session,
                now=current,
                limit=limit,
            )
            eligible_artifacts = [
                record for record in artifacts if record.task_id not in active_task_ids
            ]
            skipped_artifacts = len(artifacts) - len(eligible_artifacts)
            events = await self._expired_events(
                session,
                now=current,
                limit=limit,
            )
            if dry_run:
                return RetentionRunData(
                    dry_run=True,
                    cutoff_time=current,
                    uploaded_files_selected=len(eligible_uploads),
                    uploaded_files_skipped_active=skipped_uploads,
                    artifacts_selected=len(eligible_artifacts),
                    artifacts_skipped_active=skipped_artifacts,
                    events_selected=len(events),
                    storage_delete_failures=0,
                )

            failures = 0
            for record in eligible_uploads:
                if await self._delete_storage(record.storage_key):
                    await session.delete(record)
                else:
                    failures += 1
            for record in eligible_artifacts:
                if not await self._delete_storage(record.storage_key):
                    failures += 1
                    continue
                await session.execute(
                    update(TaskRecord)
                    .where(TaskRecord.result_uri == record.storage_uri)
                    .values(result_uri=None)
                )
                await session.execute(
                    update(StageRecord)
                    .where(StageRecord.result_uri == record.storage_uri)
                    .values(result_uri=None)
                )
                await session.delete(record)
            for record in events:
                await session.delete(record)
            await session.commit()
        return RetentionRunData(
            dry_run=False,
            cutoff_time=current,
            uploaded_files_selected=len(eligible_uploads),
            uploaded_files_skipped_active=skipped_uploads,
            artifacts_selected=len(eligible_artifacts),
            artifacts_skipped_active=skipped_artifacts,
            events_selected=len(events),
            storage_delete_failures=failures,
        )

    async def _expired_uploads(
        self,
        session: AsyncSession,
        *,
        now: datetime,
        limit: int,
    ) -> list[UploadedFileRecord]:
        if self.uploaded_file_retention_seconds is None:
            return []
        legacy_cutoff = now - timedelta(seconds=self.uploaded_file_retention_seconds)
        return list(
            await session.scalars(
                select(UploadedFileRecord)
                .where(
                    or_(
                        UploadedFileRecord.expires_at <= now,
                        (
                            UploadedFileRecord.expires_at.is_(None)
                            & (UploadedFileRecord.created_at <= legacy_cutoff)
                        ),
                    )
                )
                .order_by(
                    UploadedFileRecord.created_at,
                    UploadedFileRecord.file_id,
                )
                .limit(limit)
                .with_for_update(skip_locked=True)
            )
        )

    async def _expired_artifacts(
        self,
        session: AsyncSession,
        *,
        now: datetime,
        limit: int,
    ) -> list[ArtifactRecord]:
        if self.artifact_retention_seconds is None:
            return []
        legacy_cutoff = now - timedelta(seconds=self.artifact_retention_seconds)
        return list(
            await session.scalars(
                select(ArtifactRecord)
                .where(
                    or_(
                        ArtifactRecord.expires_at <= now,
                        (
                            ArtifactRecord.expires_at.is_(None)
                            & (ArtifactRecord.created_at <= legacy_cutoff)
                        ),
                    )
                )
                .order_by(ArtifactRecord.created_at, ArtifactRecord.artifact_id)
                .limit(limit)
                .with_for_update(skip_locked=True)
            )
        )

    async def _expired_events(
        self,
        session: AsyncSession,
        *,
        now: datetime,
        limit: int,
    ) -> list[EventRecord]:
        if self.event_retention_seconds is None:
            return []
        cutoff = now - timedelta(seconds=self.event_retention_seconds)
        return list(
            await session.scalars(
                select(EventRecord)
                .where(
                    EventRecord.occurred_at <= cutoff,
                    or_(
                        EventRecord.callback_processed.is_(True),
                        EventRecord.event_type.not_in(_CALLBACK_SOURCE_EVENTS),
                    ),
                )
                .order_by(EventRecord.occurred_at, EventRecord.event_id)
                .limit(limit)
                .with_for_update(skip_locked=True)
            )
        )

    async def _delete_storage(self, key: str) -> bool:
        try:
            await self.storage.delete(key)
        except Exception:
            self.logger.exception(
                "Retention storage deletion failed",
                extra={"reason": "storage_delete_failed"},
            )
            return False
        return True

    async def run(
        self,
        *,
        interval_seconds: float,
        stop: asyncio.Event,
    ) -> None:
        if interval_seconds <= 0:
            raise ValueError("retention interval must be greater than zero")
        while not stop.is_set():
            try:
                await self.run_once()
            except SQLAlchemyError:
                self.logger.exception("Retention pass failed")
            try:
                await asyncio.wait_for(stop.wait(), timeout=interval_seconds)
            except TimeoutError:
                pass


__all__ = ["RetentionService"]
