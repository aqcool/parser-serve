"""Resolve a pending task into an immutable Pipeline and Stage execution plan."""

from __future__ import annotations

import json
from datetime import datetime
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ..persistence.events import DatabaseEventBus, TransactionalEventPublisher
from ..persistence.models import StageRecord, TaskRecord
from ..persistence.registry import (
    BackendRepository,
    PipelineRepository,
    backend_supports_source,
    pipeline_definition,
    pipeline_supports_source,
)
from ..schema.event import TaskRoutedEvent
from ..schema.hardware import DeviceRuntime, SchedulingStrategy
from ..schema.source import SourceMetadata
from ..schema.stage import StageStatus
from ..schema.task import TaskOptions, TaskStatus


class TaskSourceUnresolvedError(Exception):
    """The task source has not been normalized enough to select a Pipeline."""


class TaskRoutingUnavailableError(Exception):
    """No compatible published Pipeline or Backend can execute the task."""


class TaskAlreadyRoutedError(Exception):
    """The task is not in a state where routing is allowed."""


class TaskRouter:
    def __init__(
        self,
        *,
        pipelines: PipelineRepository | None = None,
        backends: BackendRepository | None = None,
        events: TransactionalEventPublisher | None = None,
    ) -> None:
        self.pipelines = pipelines or PipelineRepository()
        self.backends = backends or BackendRepository()
        self.events = events or DatabaseEventBus()

    async def route(
        self,
        session: AsyncSession,
        *,
        task_id: str,
        now: datetime,
        allow_unpublished_pipeline: bool = False,
    ) -> TaskRecord | None:
        task = await session.scalar(
            select(TaskRecord)
            .where(TaskRecord.task_id == task_id)
            .options(selectinload(TaskRecord.stages))
            .with_for_update()
        )
        if task is None:
            return None
        if TaskStatus(task.status) is not TaskStatus.PENDING:
            raise TaskAlreadyRoutedError
        if task.stages:
            return task
        if task.source_metadata_payload is None:
            raise TaskSourceUnresolvedError

        metadata = SourceMetadata.model_validate_json(
            json.dumps(task.source_metadata_payload)
        )
        options = TaskOptions.model_validate_json(json.dumps(task.options_payload))
        pipeline = await self._select_pipeline(
            session,
            task=task,
            metadata=metadata,
            allow_unpublished=allow_unpublished_pipeline,
        )
        definition = pipeline_definition(pipeline)

        created_stages: list[StageRecord] = []
        for position, stage_definition in enumerate(definition.stages):
            names = [
                stage_definition.backend.preferred,
                *stage_definition.backend.fallbacks,
            ]
            if options.backend_name is not None:
                if options.backend_name not in names:
                    raise TaskRoutingUnavailableError
                names = [options.backend_name]
            available = await self.backends.enabled_by_names(session, names)
            candidates = [
                backend
                for backend in available
                if backend_supports_source(
                    backend,
                    media_category=metadata.media_category,
                    mime_type=metadata.mime_type,
                )
                and self._runtime_compatible(
                    backend.capability.runtimes,
                    stage_definition.backend.required_runtimes,
                    options.device.runtimes,
                    options.device.strategy,
                )
            ]
            if (
                options.device.strategy is SchedulingStrategy.PREFER
                and options.device.runtimes
            ):
                preferred_runtimes = set(options.device.runtimes)
                candidates.sort(
                    key=lambda backend: bool(
                        set(backend.capability.runtimes) & preferred_runtimes
                    ),
                    reverse=True,
                )
            if not candidates:
                raise TaskRoutingUnavailableError

            required_runtimes = self._allowed_runtimes(
                candidates=[
                    runtime
                    for item in candidates
                    for runtime in item.capability.runtimes
                ],
                stage_required=stage_definition.backend.required_runtimes,
                task_required=options.device.runtimes,
                task_strategy=options.device.strategy,
            )
            selected = candidates[0]
            stage = StageRecord(
                stage_id=f"stage_{uuid4().hex}",
                task_id=task.task_id,
                name=stage_definition.name,
                position=position,
                depends_on_payload=list(stage_definition.depends_on),
                optional=stage_definition.optional,
                timeout_seconds=stage_definition.timeout_seconds,
                status=StageStatus.PENDING.value,
                progress_percent=0.0,
                backend_id=selected.backend_id,
                backend_version=selected.capability.version,
                backend_candidates_payload=[
                    backend.backend_id for backend in candidates
                ],
                required_runtimes_payload=[
                    runtime.value for runtime in required_runtimes
                ],
                attempt=0,
                maximum_attempts=stage_definition.retry.maximum_attempts,
                parameters=stage_definition.parameters,
                retry_policy_payload=stage_definition.retry.model_dump(mode="json"),
                available_at=now,
                created_at=now,
                updated_at=now,
            )
            task.stages.append(stage)
            created_stages.append(stage)

        task.pipeline_id = definition.pipeline_id
        task.pipeline_version = definition.version
        task.updated_at = now
        payload = TaskRoutedEvent(
            type="task.routed",
            task_id=task.task_id,
            pipeline_id=definition.pipeline_id,
            pipeline_version=definition.version,
            stage_ids=[stage.stage_id for stage in created_stages],
        )
        self.events.publish(session, payload=payload, now=now)
        await session.flush()
        return task

    async def _select_pipeline(
        self,
        session: AsyncSession,
        *,
        task: TaskRecord,
        metadata: SourceMetadata,
        allow_unpublished: bool = False,
    ):
        if task.pipeline_id is not None and task.pipeline_version is not None:
            pipeline = await self.pipelines.get(
                session,
                pipeline_id=task.pipeline_id,
                version=task.pipeline_version,
            )
            allowed_statuses = (
                {"draft", "published"} if allow_unpublished else {"published"}
            )
            if pipeline is None or pipeline.status not in allowed_statuses:
                raise TaskRoutingUnavailableError
            if not pipeline_supports_source(
                pipeline_definition(pipeline),
                media_category=metadata.media_category,
                mime_type=metadata.mime_type,
            ):
                raise TaskRoutingUnavailableError
            return pipeline
        candidates = await self.pipelines.published_candidates(
            session,
            media_category=metadata.media_category,
            mime_type=metadata.mime_type,
        )
        if not candidates:
            raise TaskRoutingUnavailableError
        return candidates[0]

    @staticmethod
    def _runtime_compatible(
        backend_runtimes: list[DeviceRuntime],
        stage_required: list[DeviceRuntime],
        task_required: list[DeviceRuntime],
        task_strategy: SchedulingStrategy,
    ) -> bool:
        allowed = set(backend_runtimes)
        if stage_required:
            allowed &= set(stage_required)
        if task_strategy is SchedulingStrategy.REQUIRE and task_required:
            allowed &= set(task_required)
        return bool(allowed)

    @staticmethod
    def _allowed_runtimes(
        *,
        candidates: list[DeviceRuntime],
        stage_required: list[DeviceRuntime],
        task_required: list[DeviceRuntime],
        task_strategy: SchedulingStrategy,
    ) -> list[DeviceRuntime]:
        ordered = list(dict.fromkeys(candidates))
        if stage_required:
            ordered = [runtime for runtime in ordered if runtime in stage_required]
        if task_strategy is SchedulingStrategy.REQUIRE and task_required:
            ordered = [runtime for runtime in ordered if runtime in task_required]
        elif task_strategy is SchedulingStrategy.PREFER and task_required:
            preferred = [runtime for runtime in task_required if runtime in ordered]
            ordered = preferred + [
                runtime for runtime in ordered if runtime not in preferred
            ]
        return ordered


__all__ = [
    "TaskAlreadyRoutedError",
    "TaskRouter",
    "TaskRoutingUnavailableError",
    "TaskSourceUnresolvedError",
]
