"""Task persistence, idempotent creation, and lifecycle transactions."""

from __future__ import annotations

import hashlib
import json
import mimetypes
from datetime import UTC, datetime
from pathlib import PurePosixPath
from urllib.parse import unquote, urlsplit
from uuid import uuid4

from pydantic import TypeAdapter
from sqlalchemy import Select, and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ..domain.task_state import require_task_transition
from ..observability import capture_trace_context
from ..schema.common import MediaCategory
from ..schema.error import ErrorDetail
from ..schema.event import TaskCreatedEvent, TaskStatusChangedEvent
from ..schema.hardware import DeviceRuntime
from ..schema.source import (
    ParseSource,
    ObjectStorageSource,
    SourceMetadata,
    TextSource,
    UploadedFileSource,
    UrlSource,
)
from ..schema.stage import StageDetail, StageStatus
from ..schema.task import (
    CreateTaskRequest,
    TaskDetail,
    TaskListQuery,
    TaskOptions,
    TaskSortField,
    TaskStatus,
)
from ..schema.trace import TraceContext
from .events import DatabaseEventBus, TransactionalEventPublisher
from .models import PipelineRecord, StageRecord, TaskRecord
from .files import (
    FileRepository,
    UnsupportedFileTypeError,
    UploadedFileNotFoundError,
    media_category_for,
)


_source_adapter = TypeAdapter(ParseSource)


class IdempotencyConflictError(Exception):
    """The same Idempotency-Key was used with a different request."""


class PipelineNotFoundError(Exception):
    """The requested published pipeline version does not exist."""


class TaskNotCancellableError(Exception):
    """The task is already terminal."""


class TaskNotRetryableError(Exception):
    """Only failed and cancelled tasks may be manually retried."""


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _required_utc(value: datetime) -> datetime:
    return _as_utc(value) or value.replace(tzinfo=UTC)


def _canonical_request(request: CreateTaskRequest) -> bytes:
    payload = request.model_dump(mode="json")
    return json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _digest(value: bytes) -> bytes:
    return hashlib.sha256(value).digest()


async def _source_metadata(
    session: AsyncSession,
    source: ParseSource,
    *,
    now: datetime,
) -> SourceMetadata | None:
    if isinstance(source, TextSource):
        encoded = source.text.encode("utf-8")
        return SourceMetadata(
            filename=source.filename,
            mime_type=source.mime_type,
            media_category=(
                MediaCategory.WEB
                if source.mime_type in {"text/html", "application/xhtml+xml"}
                else MediaCategory.TEXT
            ),
            size_bytes=len(encoded),
            sha256=hashlib.sha256(encoded).hexdigest(),
        )
    if isinstance(source, UploadedFileSource):
        uploaded = await FileRepository().get(session, source.file_id, now=now)
        if uploaded is None:
            raise UploadedFileNotFoundError
        return SourceMetadata(
            filename=uploaded.filename,
            mime_type=uploaded.mime_type,
            media_category=MediaCategory(uploaded.media_category),
            size_bytes=uploaded.size_bytes,
            sha256=uploaded.sha256,
        )
    if isinstance(source, UrlSource):
        parsed = urlsplit(str(source.url))
        filename = PurePosixPath(unquote(parsed.path)).name or "index.html"
        return SourceMetadata(
            filename=filename,
            mime_type="text/html",
            media_category=MediaCategory.WEB,
            attributes={"source_url": str(source.url)},
        )
    if isinstance(source, ObjectStorageSource):
        parsed = urlsplit(str(source.uri))
        filename = PurePosixPath(unquote(parsed.path)).name
        if not filename:
            raise UnsupportedFileTypeError
        mime_type = mimetypes.guess_type(filename)[0] or "application/octet-stream"
        return SourceMetadata(
            filename=filename,
            mime_type=mime_type,
            media_category=media_category_for(filename, mime_type),
            attributes={
                "object_uri": str(source.uri),
                **(
                    {"version_id": source.version_id}
                    if source.version_id is not None
                    else {}
                ),
            },
        )
    return None


def _stage_detail(record: StageRecord) -> StageDetail:
    return StageDetail(
        stage_id=record.stage_id,
        name=record.name,
        position=record.position,
        depends_on=[str(item) for item in record.depends_on_payload],
        optional=record.optional,
        timeout_seconds=record.timeout_seconds,
        status=StageStatus(record.status),
        progress_percent=record.progress_percent,
        backend_id=record.backend_id,
        backend_version=record.backend_version,
        backend_candidates=[str(item) for item in record.backend_candidates_payload],
        worker_id=record.worker_id,
        runtime=DeviceRuntime(record.runtime) if record.runtime is not None else None,
        device_id=record.device_id,
        required_runtimes=[
            DeviceRuntime(str(item)) for item in record.required_runtimes_payload
        ],
        attempt=record.attempt,
        maximum_attempts=record.maximum_attempts,
        created_at=_required_utc(record.created_at),
        started_at=_as_utc(record.started_at),
        completed_at=_as_utc(record.completed_at),
        result_uri=record.result_uri,
        error=(
            ErrorDetail.model_validate_json(json.dumps(record.error_payload))
            if record.error_payload is not None
            else None
        ),
    )


def task_detail(record: TaskRecord) -> TaskDetail:
    return TaskDetail(
        task_id=record.task_id,
        status=TaskStatus(record.status),
        progress_percent=record.progress_percent,
        source=_source_adapter.validate_json(json.dumps(record.source_payload)),
        source_metadata=(
            SourceMetadata.model_validate_json(
                json.dumps(record.source_metadata_payload)
            )
            if record.source_metadata_payload is not None
            else None
        ),
        options=TaskOptions.model_validate_json(json.dumps(record.options_payload)),
        pipeline_id=record.pipeline_id,
        pipeline_version=record.pipeline_version,
        stages=[
            _stage_detail(stage)
            for stage in sorted(
                record.stages,
                key=lambda item: (item.position, item.stage_id),
            )
        ],
        client_reference=record.client_reference,
        created_at=_required_utc(record.created_at),
        started_at=_as_utc(record.started_at),
        completed_at=_as_utc(record.completed_at),
        result_uri=record.result_uri,
        error=(
            ErrorDetail.model_validate_json(json.dumps(record.error_payload))
            if record.error_payload is not None
            else None
        ),
    )


class TaskRepository:
    def __init__(
        self,
        *,
        events: TransactionalEventPublisher | None = None,
    ) -> None:
        self.events = events or DatabaseEventBus()

    async def create(
        self,
        session: AsyncSession,
        *,
        request: CreateTaskRequest,
        idempotency_key: str | None,
        now: datetime,
        allow_unpublished_pipeline: bool = False,
        trace_context: TraceContext | None = None,
    ) -> tuple[TaskRecord, bool]:
        request_digest = _digest(_canonical_request(request))
        idempotency_digest = (
            _digest(idempotency_key.encode("utf-8"))
            if idempotency_key is not None
            else None
        )
        if idempotency_digest is not None:
            existing = await session.scalar(
                select(TaskRecord).where(
                    TaskRecord.idempotency_digest == idempotency_digest
                )
            )
            if existing is not None:
                if existing.request_digest != request_digest:
                    raise IdempotencyConflictError
                return existing, False

        await self._validate_pipeline(
            session,
            request.options,
            allow_unpublished=allow_unpublished_pipeline,
        )
        source_metadata = await _source_metadata(
            session,
            request.source,
            now=now,
        )
        runtime = (
            request.options.device.runtimes[0].value
            if len(request.options.device.runtimes) == 1
            else None
        )
        resolved_trace_context = trace_context or capture_trace_context()
        record = TaskRecord(
            task_id=f"task_{uuid4().hex}",
            status=TaskStatus.PENDING.value,
            progress_percent=0.0,
            source_payload=request.source.model_dump(mode="json"),
            source_metadata_payload=(
                source_metadata.model_dump(mode="json")
                if source_metadata is not None
                else None
            ),
            media_category=(
                source_metadata.media_category.value
                if source_metadata is not None
                else None
            ),
            options_payload=request.options.model_dump(mode="json"),
            callback_payload=(
                request.callback.model_dump(mode="json")
                if request.callback is not None
                else None
            ),
            trace_context_payload=(
                resolved_trace_context.model_dump(mode="json")
                if resolved_trace_context is not None
                else None
            ),
            pipeline_id=request.options.pipeline_id,
            pipeline_version=request.options.pipeline_version,
            backend_name=request.options.backend_name,
            requested_runtime=runtime,
            priority=request.options.priority,
            client_reference=request.client_reference,
            idempotency_digest=idempotency_digest,
            request_digest=request_digest,
            created_at=now,
            updated_at=now,
        )
        session.add(record)
        self._add_event(
            session,
            payload=TaskCreatedEvent(type="task.created", task_id=record.task_id),
            now=now,
        )
        await session.flush()
        return record, True

    async def get(
        self,
        session: AsyncSession,
        task_id: str,
    ) -> TaskRecord | None:
        result = await session.execute(
            select(TaskRecord)
            .where(TaskRecord.task_id == task_id)
            .options(selectinload(TaskRecord.stages))
        )
        return result.scalar_one_or_none()

    async def list(
        self,
        session: AsyncSession,
        *,
        query: TaskListQuery,
        cursor_value: datetime | int | None = None,
        cursor_task_id: str | None = None,
    ) -> list[TaskRecord]:
        statement: Select[tuple[TaskRecord]] = select(TaskRecord).options(
            selectinload(TaskRecord.stages)
        )
        if query.statuses:
            statement = statement.where(
                TaskRecord.status.in_([status.value for status in query.statuses])
            )
        if query.media_category is not None:
            statement = statement.where(
                TaskRecord.media_category == query.media_category.value
            )
        if query.pipeline_id is not None:
            statement = statement.where(TaskRecord.pipeline_id == query.pipeline_id)
        if query.backend_name is not None:
            statement = statement.where(TaskRecord.backend_name == query.backend_name)
        if query.runtime is not None:
            statement = statement.where(
                TaskRecord.requested_runtime == query.runtime.value
            )
        if query.created_after is not None:
            statement = statement.where(TaskRecord.created_at >= query.created_after)
        if query.created_before is not None:
            statement = statement.where(TaskRecord.created_at <= query.created_before)

        sort_column = {
            TaskSortField.CREATED_AT: TaskRecord.created_at,
            TaskSortField.UPDATED_AT: TaskRecord.updated_at,
            TaskSortField.PRIORITY: TaskRecord.priority,
        }[query.sort_by]
        if cursor_value is not None and cursor_task_id is not None:
            comparison = (
                sort_column > cursor_value
                if query.sort_direction.value == "asc"
                else sort_column < cursor_value
            )
            id_comparison = (
                TaskRecord.task_id > cursor_task_id
                if query.sort_direction.value == "asc"
                else TaskRecord.task_id < cursor_task_id
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
            (sort_column.asc(), TaskRecord.task_id.asc())
            if query.sort_direction.value == "asc"
            else (sort_column.desc(), TaskRecord.task_id.desc())
        )
        result = await session.scalars(
            statement.order_by(*ordering).limit(query.limit + 1)
        )
        return list(result.unique().all())

    async def cancel(
        self,
        session: AsyncSession,
        *,
        task_id: str,
        now: datetime,
    ) -> TaskRecord | None:
        record = await self._get_for_update(session, task_id)
        if record is None:
            return None
        current = TaskStatus(record.status)
        if current in {
            TaskStatus.SUCCEEDED,
            TaskStatus.FAILED,
            TaskStatus.CANCELLED,
        }:
            raise TaskNotCancellableError
        require_task_transition(current, TaskStatus.CANCELLED)
        record.status = TaskStatus.CANCELLED.value
        record.completed_at = now
        record.updated_at = now
        for stage in record.stages:
            stage_status = StageStatus(stage.status)
            if stage_status in {
                StageStatus.PENDING,
                StageStatus.LEASED,
                StageStatus.RUNNING,
            }:
                stage.status = StageStatus.CANCELLED.value
                stage.completed_at = now
                stage.updated_at = now
                stage.lease_token_digest = None
                stage.lease_expires_at = None
                stage.completion_worker_id = None
                stage.completion_lease_token_digest = None
                stage.completion_request_digest = None
        self._status_event(
            session,
            task_id=task_id,
            previous=current,
            current=TaskStatus.CANCELLED,
            now=now,
        )
        await session.flush()
        return record

    async def retry(
        self,
        session: AsyncSession,
        *,
        task_id: str,
        now: datetime,
    ) -> TaskRecord | None:
        record = await self._get_for_update(session, task_id)
        if record is None:
            return None
        current = TaskStatus(record.status)
        if current not in {TaskStatus.FAILED, TaskStatus.CANCELLED}:
            raise TaskNotRetryableError
        require_task_transition(current, TaskStatus.PENDING)
        record.status = TaskStatus.PENDING.value
        record.progress_percent = 0.0
        record.error_payload = None
        record.result_uri = None
        record.started_at = None
        record.completed_at = None
        record.updated_at = now
        for stage in record.stages:
            stage_status = StageStatus(stage.status)
            if stage_status in {StageStatus.FAILED, StageStatus.CANCELLED}:
                stage.status = StageStatus.PENDING.value
                stage.progress_percent = 0.0
                stage.worker_id = None
                stage.attempt = 0
                stage.lease_token_digest = None
                stage.lease_expires_at = None
                stage.completion_worker_id = None
                stage.completion_lease_token_digest = None
                stage.completion_request_digest = None
                stage.error_payload = None
                stage.started_at = None
                stage.completed_at = None
                stage.updated_at = now
        self._status_event(
            session,
            task_id=task_id,
            previous=current,
            current=TaskStatus.PENDING,
            now=now,
        )
        await session.flush()
        return record

    async def _validate_pipeline(
        self,
        session: AsyncSession,
        options: TaskOptions,
        *,
        allow_unpublished: bool = False,
    ) -> None:
        if options.pipeline_id is None:
            return
        statement = select(PipelineRecord).where(
            PipelineRecord.pipeline_id == options.pipeline_id,
            PipelineRecord.version == options.pipeline_version,
        )
        if allow_unpublished:
            statement = statement.where(
                PipelineRecord.status.in_(["draft", "published"])
            )
        else:
            statement = statement.where(PipelineRecord.status == "published")
        pipeline = await session.scalar(statement)
        if pipeline is None:
            raise PipelineNotFoundError

    async def _get_for_update(
        self,
        session: AsyncSession,
        task_id: str,
    ) -> TaskRecord | None:
        result = await session.execute(
            select(TaskRecord)
            .where(TaskRecord.task_id == task_id)
            .options(selectinload(TaskRecord.stages))
            .with_for_update()
        )
        return result.scalar_one_or_none()

    def _status_event(
        self,
        session: AsyncSession,
        *,
        task_id: str,
        previous: TaskStatus,
        current: TaskStatus,
        now: datetime,
    ) -> None:
        self._add_event(
            session,
            payload=TaskStatusChangedEvent(
                type="task.status_changed",
                task_id=task_id,
                previous_status=previous,
                current_status=current,
            ),
            now=now,
        )

    def _add_event(
        self,
        session: AsyncSession,
        *,
        payload: TaskCreatedEvent | TaskStatusChangedEvent,
        now: datetime,
    ) -> None:
        self.events.publish(session, payload=payload, now=now)


__all__ = [
    "IdempotencyConflictError",
    "PipelineNotFoundError",
    "TaskNotCancellableError",
    "TaskNotRetryableError",
    "TaskRepository",
    "task_detail",
]
