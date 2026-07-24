"""Uploaded file and task Artifact persistence."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import PurePath
from uuid import uuid4

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..schema.artifact import (
    Artifact,
    ArtifactListQuery,
    ArtifactSortField,
    ArtifactType,
)
from ..schema.base import JsonValue
from ..schema.common import MediaCategory
from ..schema.file import UploadedFileDetail
from ..storage import StorageObject
from .models import ArtifactRecord, UploadedFileRecord


_DOCUMENT_EXTENSIONS = {
    ".doc",
    ".docx",
    ".epub",
    ".odg",
    ".odp",
    ".ods",
    ".odt",
    ".pdf",
    ".ppt",
    ".pptx",
    ".rtf",
    ".xls",
    ".xlsx",
}
_IMAGE_EXTENSIONS = {
    ".avif",
    ".bmp",
    ".gif",
    ".heic",
    ".heif",
    ".jpeg",
    ".jpg",
    ".png",
    ".tif",
    ".tiff",
    ".webp",
}
_AUDIO_EXTENSIONS = {
    ".aac",
    ".flac",
    ".m4a",
    ".mp3",
    ".ogg",
    ".opus",
    ".wav",
    ".wma",
}
_VIDEO_EXTENSIONS = {
    ".avi",
    ".flv",
    ".m4v",
    ".mkv",
    ".mov",
    ".mp4",
    ".mpeg",
    ".mpg",
    ".ts",
    ".webm",
    ".wmv",
}
_WEB_EXTENSIONS = {".htm", ".html", ".mhtml", ".xhtml"}
_TEXT_EXTENSIONS = {
    ".csv",
    ".json",
    ".log",
    ".md",
    ".rst",
    ".text",
    ".txt",
    ".xml",
    ".yaml",
    ".yml",
}


class UnsupportedFileTypeError(Exception):
    """The file cannot be assigned to a supported media category."""


class UploadedFileNotFoundError(Exception):
    """The uploaded file does not exist or has expired."""


def media_category_for(filename: str, mime_type: str) -> MediaCategory:
    normalized_mime = mime_type.lower().split(";", 1)[0].strip()
    suffix = PurePath(filename.lower()).suffix
    if normalized_mime == "text/html" or suffix in _WEB_EXTENSIONS:
        return MediaCategory.WEB
    if normalized_mime.startswith("image/") or suffix in _IMAGE_EXTENSIONS:
        return MediaCategory.IMAGE
    if normalized_mime.startswith("audio/") or suffix in _AUDIO_EXTENSIONS:
        return MediaCategory.AUDIO
    if normalized_mime.startswith("video/") or suffix in _VIDEO_EXTENSIONS:
        return MediaCategory.VIDEO
    if suffix in _DOCUMENT_EXTENSIONS or normalized_mime in {
        "application/epub+zip",
        "application/msword",
        "application/pdf",
        "application/rtf",
        "application/vnd.ms-excel",
        "application/vnd.ms-powerpoint",
        "application/vnd.oasis.opendocument.presentation",
        "application/vnd.oasis.opendocument.spreadsheet",
        "application/vnd.oasis.opendocument.text",
        "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    }:
        return MediaCategory.DOCUMENT
    if normalized_mime.startswith("text/") or suffix in _TEXT_EXTENSIONS:
        return MediaCategory.TEXT
    raise UnsupportedFileTypeError


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def uploaded_file_detail(record: UploadedFileRecord) -> UploadedFileDetail:
    return UploadedFileDetail(
        file_id=record.file_id,
        filename=record.filename,
        mime_type=record.mime_type,
        media_category=MediaCategory(record.media_category),
        size_bytes=record.size_bytes,
        sha256=record.sha256,
        created_at=_utc(record.created_at),
        expires_at=_utc(record.expires_at) if record.expires_at is not None else None,
    )


def artifact_detail(record: ArtifactRecord) -> Artifact:
    return Artifact(
        artifact_id=record.artifact_id,
        type=ArtifactType(record.artifact_type),
        filename=record.filename,
        mime_type=record.mime_type,
        size_bytes=record.size_bytes,
        sha256=record.sha256,
        storage_uri=record.storage_uri,
        created_at=_utc(record.created_at),
        expires_at=_utc(record.expires_at) if record.expires_at is not None else None,
        metadata=record.artifact_metadata,
    )


class FileRepository:
    async def create(
        self,
        session: AsyncSession,
        *,
        file_id: str,
        filename: str,
        mime_type: str,
        media_category: MediaCategory,
        stored: StorageObject,
        now: datetime,
        expires_at: datetime | None = None,
    ) -> UploadedFileRecord:
        record = UploadedFileRecord(
            file_id=file_id,
            filename=filename,
            mime_type=mime_type,
            media_category=media_category.value,
            size_bytes=stored.size_bytes,
            sha256=stored.sha256,
            storage_key=stored.key,
            storage_uri=stored.uri,
            created_at=now,
            expires_at=expires_at,
        )
        session.add(record)
        await session.flush()
        return record

    async def get(
        self,
        session: AsyncSession,
        file_id: str,
        *,
        now: datetime | None = None,
    ) -> UploadedFileRecord | None:
        record = await session.get(UploadedFileRecord, file_id)
        if record is not None and now is not None and record.expires_at is not None:
            if _utc(record.expires_at) <= now:
                return None
        return record


class ArtifactRepository:
    async def get_by_storage_uri(
        self,
        session: AsyncSession,
        *,
        task_id: str,
        storage_uri: str,
        now: datetime | None = None,
    ) -> ArtifactRecord | None:
        record = await session.scalar(
            select(ArtifactRecord).where(
                ArtifactRecord.task_id == task_id,
                ArtifactRecord.storage_uri == storage_uri,
            )
        )
        if (
            record is not None
            and now is not None
            and record.expires_at is not None
            and _utc(record.expires_at) <= now
        ):
            return None
        return record

    async def get_by_idempotency(
        self,
        session: AsyncSession,
        *,
        stage_id: str,
        idempotency_digest: bytes,
    ) -> ArtifactRecord | None:
        return await session.scalar(
            select(ArtifactRecord).where(
                ArtifactRecord.stage_id == stage_id,
                ArtifactRecord.idempotency_digest == idempotency_digest,
            )
        )

    async def list_for_task(
        self,
        session: AsyncSession,
        task_id: str,
        *,
        query: ArtifactListQuery | None = None,
        cursor_value: datetime | str | int | None = None,
        cursor_artifact_id: str | None = None,
        now: datetime | None = None,
    ) -> list[ArtifactRecord]:
        statement = select(ArtifactRecord).where(ArtifactRecord.task_id == task_id)
        if now is not None:
            statement = statement.where(
                or_(
                    ArtifactRecord.expires_at.is_(None),
                    ArtifactRecord.expires_at > now,
                )
            )
        if query is None:
            return list(
                await session.scalars(
                    statement.order_by(
                        ArtifactRecord.created_at,
                        ArtifactRecord.artifact_id,
                    )
                )
            )
        if query.types:
            statement = statement.where(
                ArtifactRecord.artifact_type.in_(
                    [artifact_type.value for artifact_type in query.types]
                )
            )
        if query.mime_type is not None:
            statement = statement.where(ArtifactRecord.mime_type == query.mime_type)
        sort_column = {
            ArtifactSortField.CREATED_AT: ArtifactRecord.created_at,
            ArtifactSortField.FILENAME: ArtifactRecord.filename,
            ArtifactSortField.SIZE_BYTES: ArtifactRecord.size_bytes,
        }[query.sort_by]
        if cursor_value is not None and cursor_artifact_id is not None:
            comparison = (
                sort_column > cursor_value
                if query.sort_direction.value == "asc"
                else sort_column < cursor_value
            )
            id_comparison = (
                ArtifactRecord.artifact_id > cursor_artifact_id
                if query.sort_direction.value == "asc"
                else ArtifactRecord.artifact_id < cursor_artifact_id
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
            (sort_column.asc(), ArtifactRecord.artifact_id.asc())
            if query.sort_direction.value == "asc"
            else (sort_column.desc(), ArtifactRecord.artifact_id.desc())
        )
        return list(
            await session.scalars(statement.order_by(*ordering).limit(query.limit + 1))
        )

    async def get(
        self,
        session: AsyncSession,
        *,
        task_id: str,
        artifact_id: str,
        now: datetime | None = None,
    ) -> ArtifactRecord | None:
        record = await session.scalar(
            select(ArtifactRecord).where(
                ArtifactRecord.task_id == task_id,
                ArtifactRecord.artifact_id == artifact_id,
            )
        )
        if (
            record is not None
            and now is not None
            and record.expires_at is not None
            and _utc(record.expires_at) <= now
        ):
            return None
        return record

    async def create(
        self,
        session: AsyncSession,
        *,
        task_id: str,
        stage_id: str | None = None,
        worker_id: str | None = None,
        artifact_type: ArtifactType,
        filename: str,
        mime_type: str,
        stored: StorageObject,
        now: datetime,
        metadata: dict[str, JsonValue] | None = None,
        expires_at: datetime | None = None,
        artifact_id: str | None = None,
        idempotency_digest: bytes | None = None,
        request_digest: bytes | None = None,
    ) -> ArtifactRecord:
        record = ArtifactRecord(
            artifact_id=artifact_id or f"artifact_{uuid4().hex}",
            task_id=task_id,
            stage_id=stage_id,
            worker_id=worker_id,
            artifact_type=artifact_type.value,
            filename=filename,
            mime_type=mime_type,
            size_bytes=stored.size_bytes,
            sha256=stored.sha256,
            storage_key=stored.key,
            storage_uri=stored.uri,
            idempotency_digest=idempotency_digest,
            request_digest=request_digest,
            artifact_metadata=metadata or {},
            created_at=now,
            expires_at=expires_at,
        )
        session.add(record)
        await session.flush()
        return record


__all__ = [
    "ArtifactRepository",
    "FileRepository",
    "UnsupportedFileTypeError",
    "UploadedFileNotFoundError",
    "artifact_detail",
    "media_category_for",
    "uploaded_file_detail",
]
