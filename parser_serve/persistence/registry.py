"""Backend registry and versioned Pipeline persistence."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..schema.backend import (
    BackendDetail,
    BackendListQuery,
    BackendSortField,
    BackendStatus,
    CreateBackendRequest,
    UpdateBackendRequest,
)
from ..schema.common import MediaCategory
from ..schema.pipeline import (
    CreatePipelineRequest,
    PipelineDefinition,
    PipelineListQuery,
    PipelineSortField,
    PipelineStatus,
    PipelineValidationData,
    PipelineValidationViolation,
)
from .models import BackendRecord, PipelineRecord


class RegistryConflictError(Exception):
    """A unique Backend or Pipeline version already exists."""


class PipelinePublishError(Exception):
    def __init__(self, validation: PipelineValidationData) -> None:
        super().__init__("pipeline validation failed")
        self.validation = validation


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def backend_detail(record: BackendRecord) -> BackendDetail:
    return BackendDetail.model_validate_json(json.dumps(record.definition_payload))


def pipeline_definition(record: PipelineRecord) -> PipelineDefinition:
    return PipelineDefinition.model_validate_json(json.dumps(record.definition_payload))


def _mime_parts(pattern: str) -> tuple[str, str]:
    major, minor = pattern.split("/", maxsplit=1)
    return major, minor


def mime_patterns_overlap(first: str, second: str) -> bool:
    first_major, first_minor = _mime_parts(first)
    second_major, second_minor = _mime_parts(second)
    return (
        first_major == "*" or second_major == "*" or first_major == second_major
    ) and (first_minor == "*" or second_minor == "*" or first_minor == second_minor)


def backend_supports_pipeline(
    backend: BackendDetail,
    pipeline: PipelineDefinition,
) -> bool:
    categories_overlap = bool(
        set(backend.capability.media_categories) & set(pipeline.media_categories)
    )
    mime_overlap = any(
        mime_patterns_overlap(backend_mime, pipeline_mime)
        for backend_mime in backend.capability.mime_types
        for pipeline_mime in pipeline.mime_types
    )
    return categories_overlap or mime_overlap


def backend_supports_source(
    backend: BackendDetail,
    *,
    media_category: MediaCategory,
    mime_type: str,
) -> bool:
    return media_category in backend.capability.media_categories or any(
        mime_patterns_overlap(pattern, mime_type)
        for pattern in backend.capability.mime_types
    )


def pipeline_supports_source(
    pipeline: PipelineDefinition,
    *,
    media_category: MediaCategory,
    mime_type: str,
) -> bool:
    return media_category in pipeline.media_categories and (
        not pipeline.mime_types
        or any(
            mime_patterns_overlap(pattern, mime_type) for pattern in pipeline.mime_types
        )
    )


class BackendRepository:
    async def create(
        self,
        session: AsyncSession,
        *,
        request: CreateBackendRequest,
        now: datetime,
    ) -> BackendRecord:
        exists = await session.scalar(
            select(BackendRecord.backend_id).where(
                BackendRecord.name == request.capability.name,
                BackendRecord.version == request.capability.version,
            )
        )
        if exists is not None:
            raise RegistryConflictError
        detail = BackendDetail(
            backend_id=f"backend_{uuid4().hex}",
            capability=request.capability,
            status=(
                BackendStatus.ENABLED if request.enabled else BackendStatus.DISABLED
            ),
            execution_mode=request.execution_mode,
            default_timeout_seconds=request.default_timeout_seconds,
            maximum_attempts=request.maximum_attempts,
            scheduling_weight=request.scheduling_weight,
            remote_url=request.remote_url,
            configuration=request.configuration,
            created_at=now,
            updated_at=now,
        )
        record = BackendRecord(
            backend_id=detail.backend_id,
            name=detail.capability.name,
            version=detail.capability.version,
            status=detail.status.value,
            execution_mode=detail.execution_mode.value,
            definition_payload=detail.model_dump(mode="json"),
            created_at=now,
            updated_at=now,
        )
        session.add(record)
        await session.flush()
        return record

    async def get(
        self,
        session: AsyncSession,
        backend_id: str,
    ) -> BackendRecord | None:
        return await session.get(BackendRecord, backend_id)

    async def list(
        self,
        session: AsyncSession,
        *,
        query: BackendListQuery,
        cursor_value: datetime | str | None = None,
        cursor_backend_id: str | None = None,
    ) -> list[BackendRecord]:
        statement = select(BackendRecord)
        if query.statuses:
            statement = statement.where(
                BackendRecord.status.in_([status.value for status in query.statuses])
            )
        if query.execution_mode is not None:
            statement = statement.where(
                BackendRecord.execution_mode == query.execution_mode.value
            )
        if query.name_contains is not None:
            escaped = (
                query.name_contains.replace("\\", "\\\\")
                .replace("%", "\\%")
                .replace("_", "\\_")
            )
            statement = statement.where(
                BackendRecord.name.ilike(f"%{escaped}%", escape="\\")
            )
        sort_column = {
            BackendSortField.CREATED_AT: BackendRecord.created_at,
            BackendSortField.UPDATED_AT: BackendRecord.updated_at,
            BackendSortField.NAME: BackendRecord.name,
        }[query.sort_by]
        if cursor_value is not None and cursor_backend_id is not None:
            comparison = (
                sort_column > cursor_value
                if query.sort_direction.value == "asc"
                else sort_column < cursor_value
            )
            id_comparison = (
                BackendRecord.backend_id > cursor_backend_id
                if query.sort_direction.value == "asc"
                else BackendRecord.backend_id < cursor_backend_id
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
            (sort_column.asc(), BackendRecord.backend_id.asc())
            if query.sort_direction.value == "asc"
            else (sort_column.desc(), BackendRecord.backend_id.desc())
        )
        records = list((await session.scalars(statement.order_by(*ordering))).all())
        filtered = [
            record
            for record in records
            if self._matches_capability(backend_detail(record), query)
        ]
        return filtered[: query.limit + 1]

    async def update(
        self,
        session: AsyncSession,
        *,
        backend_id: str,
        update: UpdateBackendRequest,
        now: datetime,
    ) -> BackendRecord | None:
        record = await session.scalar(
            select(BackendRecord)
            .where(BackendRecord.backend_id == backend_id)
            .with_for_update()
        )
        if record is None:
            return None
        current = backend_detail(record)
        detail = BackendDetail(
            backend_id=current.backend_id,
            capability=current.capability,
            status=(
                BackendStatus.ENABLED
                if update.enabled is True
                else (
                    BackendStatus.DISABLED
                    if update.enabled is False
                    else current.status
                )
            ),
            execution_mode=current.execution_mode,
            default_timeout_seconds=(
                update.default_timeout_seconds or current.default_timeout_seconds
            ),
            maximum_attempts=update.maximum_attempts or current.maximum_attempts,
            scheduling_weight=(update.scheduling_weight or current.scheduling_weight),
            remote_url=current.remote_url,
            configuration=(
                update.configuration
                if update.configuration is not None
                else current.configuration
            ),
            created_at=current.created_at,
            updated_at=now,
        )
        record.status = detail.status.value
        record.definition_payload = detail.model_dump(mode="json")
        record.updated_at = now
        await session.flush()
        return record

    async def enabled_by_names(
        self,
        session: AsyncSession,
        names: list[str],
    ) -> list[BackendDetail]:
        if not names:
            return []
        records = list(
            (
                await session.scalars(
                    select(BackendRecord)
                    .where(
                        BackendRecord.name.in_(names),
                        BackendRecord.status == BackendStatus.ENABLED.value,
                    )
                    .order_by(
                        BackendRecord.updated_at.desc(),
                        BackendRecord.backend_id.desc(),
                    )
                )
            ).all()
        )
        grouped: dict[str, list[BackendDetail]] = {name: [] for name in names}
        for record in records:
            grouped[record.name].append(backend_detail(record))
        return [detail for name in names for detail in grouped[name]]

    @staticmethod
    def _matches_capability(
        detail: BackendDetail,
        query: BackendListQuery,
    ) -> bool:
        if query.runtimes and not (
            set(query.runtimes) & set(detail.capability.runtimes)
        ):
            return False
        return not (
            query.media_category is not None
            and query.media_category not in detail.capability.media_categories
        )


class PipelineRepository:
    async def create(
        self,
        session: AsyncSession,
        *,
        request: CreatePipelineRequest,
        now: datetime,
    ) -> PipelineRecord:
        current_version = await session.scalar(
            select(func.max(PipelineRecord.version)).where(
                PipelineRecord.pipeline_id == request.pipeline_id
            )
        )
        version = (current_version or 0) + 1
        definition = PipelineDefinition(
            pipeline_id=request.pipeline_id,
            name=request.name,
            version=version,
            status=PipelineStatus.DRAFT,
            media_categories=request.media_categories,
            mime_types=request.mime_types,
            routing_priority=request.routing_priority,
            stages=request.stages,
            created_at=now,
        )
        record = PipelineRecord(
            pipeline_id=definition.pipeline_id,
            version=definition.version,
            name=definition.name,
            status=definition.status.value,
            definition_payload=definition.model_dump(mode="json"),
            created_at=now,
            updated_at=now,
        )
        session.add(record)
        await session.flush()
        return record

    async def get(
        self,
        session: AsyncSession,
        *,
        pipeline_id: str,
        version: int,
    ) -> PipelineRecord | None:
        return await session.scalar(
            select(PipelineRecord).where(
                PipelineRecord.pipeline_id == pipeline_id,
                PipelineRecord.version == version,
            )
        )

    async def list(
        self,
        session: AsyncSession,
        *,
        query: PipelineListQuery,
        cursor_value: datetime | str | int | None = None,
        cursor_record_id: int | None = None,
    ) -> list[PipelineRecord]:
        statement = select(PipelineRecord)
        if query.statuses:
            statement = statement.where(
                PipelineRecord.status.in_([status.value for status in query.statuses])
            )
        if query.name_contains is not None:
            escaped = (
                query.name_contains.replace("\\", "\\\\")
                .replace("%", "\\%")
                .replace("_", "\\_")
            )
            statement = statement.where(
                PipelineRecord.name.ilike(f"%{escaped}%", escape="\\")
            )
        sort_column = {
            PipelineSortField.CREATED_AT: PipelineRecord.created_at,
            PipelineSortField.UPDATED_AT: PipelineRecord.updated_at,
            PipelineSortField.NAME: PipelineRecord.name,
            PipelineSortField.VERSION: PipelineRecord.version,
        }[query.sort_by]
        if cursor_value is not None and cursor_record_id is not None:
            comparison = (
                sort_column > cursor_value
                if query.sort_direction.value == "asc"
                else sort_column < cursor_value
            )
            id_comparison = (
                PipelineRecord.record_id > cursor_record_id
                if query.sort_direction.value == "asc"
                else PipelineRecord.record_id < cursor_record_id
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
            (sort_column.asc(), PipelineRecord.record_id.asc())
            if query.sort_direction.value == "asc"
            else (sort_column.desc(), PipelineRecord.record_id.desc())
        )
        records = list((await session.scalars(statement.order_by(*ordering))).all())
        if query.media_category is not None:
            records = [
                record
                for record in records
                if query.media_category in pipeline_definition(record).media_categories
            ]
        return records[: query.limit + 1]

    async def validate(
        self,
        session: AsyncSession,
        record: PipelineRecord,
    ) -> PipelineValidationData:
        definition = pipeline_definition(record)
        violations: list[PipelineValidationViolation] = []
        backend_repository = BackendRepository()
        for stage in definition.stages:
            names = [stage.backend.preferred, *stage.backend.fallbacks]
            candidates = await backend_repository.enabled_by_names(session, names)
            compatible = [
                backend
                for backend in candidates
                if backend_supports_pipeline(backend, definition)
                and (
                    not stage.backend.required_runtimes
                    or set(stage.backend.required_runtimes)
                    & set(backend.capability.runtimes)
                )
            ]
            if not compatible:
                violations.append(
                    PipelineValidationViolation(
                        location=f"stages.{stage.name}.backend",
                        message=(
                            "no enabled compatible backend provides the required "
                            "media and runtime capabilities"
                        ),
                    )
                )
        return PipelineValidationData(
            valid=not violations,
            violations=violations,
        )

    async def publish(
        self,
        session: AsyncSession,
        *,
        pipeline_id: str,
        version: int,
        now: datetime,
    ) -> PipelineRecord | None:
        record = await session.scalar(
            select(PipelineRecord)
            .where(
                PipelineRecord.pipeline_id == pipeline_id,
                PipelineRecord.version == version,
            )
            .with_for_update()
        )
        if record is None:
            return None
        validation = await self.validate(session, record)
        if not validation.valid:
            raise PipelinePublishError(validation)

        currently_published = list(
            (
                await session.scalars(
                    select(PipelineRecord)
                    .where(
                        PipelineRecord.pipeline_id == pipeline_id,
                        PipelineRecord.status == PipelineStatus.PUBLISHED.value,
                        PipelineRecord.record_id != record.record_id,
                    )
                    .with_for_update()
                )
            ).all()
        )
        for previous in currently_published:
            definition = pipeline_definition(previous)
            disabled = definition.model_copy(
                update={
                    "status": PipelineStatus.DISABLED,
                    "published_at": None,
                }
            )
            previous.status = PipelineStatus.DISABLED.value
            previous.published_at = None
            previous.definition_payload = disabled.model_dump(mode="json")
            previous.updated_at = now

        definition = pipeline_definition(record)
        published = definition.model_copy(
            update={
                "status": PipelineStatus.PUBLISHED,
                "published_at": now,
            }
        )
        record.status = PipelineStatus.PUBLISHED.value
        record.published_at = now
        record.definition_payload = published.model_dump(mode="json")
        record.updated_at = now
        await session.flush()
        return record

    async def published_candidates(
        self,
        session: AsyncSession,
        *,
        media_category: MediaCategory,
        mime_type: str,
    ) -> list[PipelineRecord]:
        records = list(
            (
                await session.scalars(
                    select(PipelineRecord).where(
                        PipelineRecord.status == PipelineStatus.PUBLISHED.value
                    )
                )
            ).all()
        )
        compatible = []
        for record in records:
            definition = pipeline_definition(record)
            if pipeline_supports_source(
                definition,
                media_category=media_category,
                mime_type=mime_type,
            ):
                compatible.append(record)
        return sorted(
            compatible,
            key=lambda record: (
                pipeline_definition(record).routing_priority,
                record.version,
                record.pipeline_id,
            ),
            reverse=True,
        )


__all__ = [
    "BackendRepository",
    "PipelinePublishError",
    "PipelineRepository",
    "RegistryConflictError",
    "backend_detail",
    "backend_supports_pipeline",
    "backend_supports_source",
    "pipeline_supports_source",
    "mime_patterns_overlap",
    "pipeline_definition",
]
