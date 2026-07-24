from __future__ import annotations

import unittest
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from parser_serve.control.router import (
    TaskRouter,
    TaskRoutingUnavailableError,
)
from parser_serve.persistence import Database
from parser_serve.persistence.models import EventRecord
from parser_serve.persistence.registry import (
    BackendRepository,
    PipelinePublishError,
    PipelineRepository,
    backend_detail,
    pipeline_definition,
)
from parser_serve.persistence.tasks import TaskRepository, task_detail
from parser_serve.schema.backend import (
    BackendCapability,
    BackendExecutionMode,
    BackendListQuery,
    BackendStatus,
    CreateBackendRequest,
    UpdateBackendRequest,
)
from parser_serve.schema.common import MediaCategory
from parser_serve.schema.hardware import DeviceRuntime
from parser_serve.schema.pipeline import (
    BackendSelector,
    CreatePipelineRequest,
    PipelineListQuery,
    PipelineStageDefinition,
    PipelineStatus,
)
from parser_serve.schema.task import CreateTaskRequest


NOW = datetime(2026, 7, 24, 12, 0, tzinfo=UTC)


def backend_request(
    name: str,
    *,
    runtime: DeviceRuntime = DeviceRuntime.CPU,
) -> CreateBackendRequest:
    return CreateBackendRequest(
        capability=BackendCapability(
            name=name,
            version="1.0",
            media_categories=[MediaCategory.TEXT],
            runtimes=[runtime],
            maximum_concurrency=4,
        ),
        execution_mode=BackendExecutionMode.LOCAL,
        default_timeout_seconds=60,
    )


def pipeline_request(
    *,
    pipeline_id: str = "pipeline_textparse",
    backend_name: str = "text_backend",
    priority: int = 0,
) -> CreatePipelineRequest:
    return CreatePipelineRequest(
        pipeline_id=pipeline_id,
        name="Text Pipeline",
        media_categories=[MediaCategory.TEXT],
        routing_priority=priority,
        stages=[
            PipelineStageDefinition(
                name="extract",
                backend=BackendSelector(preferred=backend_name),
                timeout_seconds=60,
            ),
            PipelineStageDefinition(
                name="normalize",
                backend=BackendSelector(preferred=backend_name),
                depends_on=["extract"],
                timeout_seconds=30,
            ),
        ],
    )


def text_task(*, require_cpu: bool = False) -> CreateTaskRequest:
    payload: dict[str, object] = {"source": {"type": "text", "text": "hello"}}
    if require_cpu:
        payload["options"] = {"device": {"strategy": "require", "runtimes": ["cpu"]}}
    return CreateTaskRequest.model_validate_json(__import__("json").dumps(payload))


class RegistryTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.database = Database("sqlite+aiosqlite:///:memory:")
        await self.database.create_schema_for_testing()
        self.backends = BackendRepository()
        self.pipelines = PipelineRepository()
        self.tasks = TaskRepository()

    async def asyncTearDown(self) -> None:
        await self.database.dispose()

    async def create_backend(
        self,
        name: str = "text_backend",
        *,
        runtime: DeviceRuntime = DeviceRuntime.CPU,
    ):
        async with self.database.session_factory() as session:
            record = await self.backends.create(
                session,
                request=backend_request(name, runtime=runtime),
                now=NOW,
            )
            await session.commit()
            return record.backend_id

    async def create_pipeline(
        self,
        *,
        pipeline_id: str = "pipeline_textparse",
        backend_name: str = "text_backend",
        priority: int = 0,
    ):
        async with self.database.session_factory() as session:
            record = await self.pipelines.create(
                session,
                request=pipeline_request(
                    pipeline_id=pipeline_id,
                    backend_name=backend_name,
                    priority=priority,
                ),
                now=NOW,
            )
            await session.commit()
            return record.pipeline_id, record.version

    async def publish(self, pipeline_id: str, version: int) -> None:
        async with self.database.session_factory() as session:
            await self.pipelines.publish(
                session,
                pipeline_id=pipeline_id,
                version=version,
                now=NOW + timedelta(seconds=1),
            )
            await session.commit()

    async def test_pipeline_publish_requires_compatible_backend(self) -> None:
        pipeline_id, version = await self.create_pipeline()

        async with self.database.session_factory() as session:
            record = await self.pipelines.get(
                session,
                pipeline_id=pipeline_id,
                version=version,
            )
            self.assertIsNotNone(record)
            if record is not None:
                validation = await self.pipelines.validate(session, record)
                self.assertFalse(validation.valid)
                with self.assertRaises(PipelinePublishError):
                    await self.pipelines.publish(
                        session,
                        pipeline_id=pipeline_id,
                        version=version,
                        now=NOW,
                    )

        await self.create_backend()
        await self.publish(pipeline_id, version)

        async with self.database.session_factory() as session:
            published = await self.pipelines.get(
                session,
                pipeline_id=pipeline_id,
                version=version,
            )
        self.assertIsNotNone(published)
        if published is not None:
            self.assertEqual(
                pipeline_definition(published).status,
                PipelineStatus.PUBLISHED,
            )

    async def test_publishing_prior_version_rolls_back_active_version(self) -> None:
        await self.create_backend()
        pipeline_id, first_version = await self.create_pipeline()
        _, second_version = await self.create_pipeline()
        await self.publish(pipeline_id, second_version)
        await self.publish(pipeline_id, first_version)

        async with self.database.session_factory() as session:
            first = await self.pipelines.get(
                session,
                pipeline_id=pipeline_id,
                version=first_version,
            )
            second = await self.pipelines.get(
                session,
                pipeline_id=pipeline_id,
                version=second_version,
            )

        self.assertIsNotNone(first)
        self.assertIsNotNone(second)
        if first is not None and second is not None:
            self.assertEqual(first.status, PipelineStatus.PUBLISHED)
            self.assertEqual(second.status, PipelineStatus.DISABLED)

    async def test_backend_update_and_capability_filter(self) -> None:
        backend_id = await self.create_backend()
        async with self.database.session_factory() as session:
            updated = await self.backends.update(
                session,
                backend_id=backend_id,
                update=UpdateBackendRequest(enabled=False),
                now=NOW + timedelta(seconds=1),
            )
            await session.commit()
        self.assertIsNotNone(updated)
        if updated is not None:
            self.assertEqual(backend_detail(updated).status, BackendStatus.DISABLED)

        async with self.database.session_factory() as session:
            records = await self.backends.list(
                session,
                query=BackendListQuery(
                    statuses=[BackendStatus.DISABLED],
                    runtimes=[DeviceRuntime.CPU],
                ),
            )
        self.assertEqual([record.backend_id for record in records], [backend_id])

    async def test_router_materializes_pipeline_and_stage_constraints(self) -> None:
        backend_id = await self.create_backend()
        pipeline_id, version = await self.create_pipeline()
        await self.publish(pipeline_id, version)
        async with self.database.session_factory() as session:
            task, _ = await self.tasks.create(
                session,
                request=text_task(require_cpu=True),
                idempotency_key=None,
                now=NOW,
            )
            await session.commit()

        async with self.database.session_factory() as session:
            routed = await TaskRouter().route(
                session,
                task_id=task.task_id,
                now=NOW + timedelta(seconds=2),
            )
            await session.commit()

        self.assertIsNotNone(routed)
        async with self.database.session_factory() as session:
            loaded = await self.tasks.get(session, task.task_id)
            routed_events = list(
                await session.scalars(
                    select(EventRecord).where(EventRecord.event_type == "task.routed")
                )
            )
        self.assertIsNotNone(loaded)
        if loaded is not None:
            detail = task_detail(loaded)
            self.assertEqual(detail.pipeline_id, pipeline_id)
            self.assertEqual(detail.pipeline_version, version)
            self.assertEqual(len(detail.stages), 2)
            self.assertEqual(detail.stages[1].depends_on, ["extract"])
            self.assertEqual(detail.stages[0].backend_id, backend_id)
            self.assertEqual(detail.stages[0].required_runtimes, ["cpu"])
            self.assertEqual(detail.stages[0].timeout_seconds, 60)
        self.assertEqual(len(routed_events), 1)

    async def test_router_rejects_incompatible_task_runtime(self) -> None:
        await self.create_backend(runtime=DeviceRuntime.CUDA)
        pipeline_id, version = await self.create_pipeline()
        await self.publish(pipeline_id, version)
        async with self.database.session_factory() as session:
            task, _ = await self.tasks.create(
                session,
                request=text_task(require_cpu=True),
                idempotency_key=None,
                now=NOW,
            )
            await session.commit()

        async with self.database.session_factory() as session:
            with self.assertRaises(TaskRoutingUnavailableError):
                await TaskRouter().route(
                    session,
                    task_id=task.task_id,
                    now=NOW,
                )

    async def test_preferred_runtime_falls_back_when_unavailable(self) -> None:
        await self.create_backend(runtime=DeviceRuntime.CUDA)
        pipeline_id, version = await self.create_pipeline()
        await self.publish(pipeline_id, version)
        request = CreateTaskRequest.model_validate(
            {
                "source": {"type": "text", "text": "hello"},
                "options": {
                    "device": {
                        "strategy": "prefer",
                        "runtimes": ["cpu"],
                    }
                },
            }
        )
        async with self.database.session_factory() as session:
            task, _ = await self.tasks.create(
                session,
                request=request,
                idempotency_key=None,
                now=NOW,
            )
            routed = await TaskRouter().route(
                session,
                task_id=task.task_id,
                now=NOW,
            )
            await session.commit()
        self.assertIsNotNone(routed)
        if routed is not None:
            self.assertEqual(routed.stages[0].required_runtimes_payload, ["cuda"])

    async def test_pipeline_list_filters_media_category(self) -> None:
        await self.create_pipeline()
        async with self.database.session_factory() as session:
            records = await self.pipelines.list(
                session,
                query=PipelineListQuery(media_category=MediaCategory.TEXT),
            )
        self.assertEqual(len(records), 1)


if __name__ == "__main__":
    unittest.main()
