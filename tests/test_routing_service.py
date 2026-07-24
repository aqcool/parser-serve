from __future__ import annotations

import unittest
from datetime import UTC, datetime, timedelta

from parser_serve.control import TaskRouter, TaskRoutingService
from parser_serve.persistence import Database
from parser_serve.persistence.registry import BackendRepository, PipelineRepository
from parser_serve.persistence.tasks import TaskRepository, task_detail
from parser_serve.queue import TaskQueueNotifier
from parser_serve.schema.queue import StageQueueNotice
from parser_serve.schema.backend import (
    BackendCapability,
    BackendExecutionMode,
    CreateBackendRequest,
)
from parser_serve.schema.common import MediaCategory
from parser_serve.schema.hardware import DeviceRuntime
from parser_serve.schema.pipeline import (
    BackendSelector,
    CreatePipelineRequest,
    PipelineStageDefinition,
)
from parser_serve.schema.task import CreateTaskRequest


NOW = datetime(2026, 7, 24, 12, 0, tzinfo=UTC)


class RecordingTaskQueue:
    def __init__(self) -> None:
        self.notices: list[StageQueueNotice] = []

    async def snapshot(self) -> str:
        return str(len(self.notices))

    async def publish(self, notice: StageQueueNotice) -> None:
        self.notices.append(notice)

    async def wait(self, *, after: str, timeout_seconds: float) -> bool:
        return len(self.notices) > int(after)

    async def check(self) -> None:
        return None

    async def aclose(self) -> None:
        return None


class TaskRoutingServiceTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.database = Database("sqlite+aiosqlite:///:memory:")
        await self.database.create_schema_for_testing()
        self.tasks = TaskRepository()
        self.backends = BackendRepository()
        self.pipelines = PipelineRepository()
        self.router = TaskRouter(
            pipelines=self.pipelines,
            backends=self.backends,
        )
        self.queue = RecordingTaskQueue()
        self.service = TaskRoutingService(
            database=self.database,
            router=self.router,
            queue_notifier=TaskQueueNotifier(self.queue),
        )

    async def asyncTearDown(self) -> None:
        await self.database.dispose()

    async def test_routes_pending_task_after_capabilities_become_available(
        self,
    ) -> None:
        async with self.database.session_factory() as session:
            task, _ = await self.tasks.create(
                session,
                request=CreateTaskRequest.model_validate(
                    {"source": {"type": "text", "text": "route later"}}
                ),
                idempotency_key=None,
                now=NOW,
            )
            task_id = task.task_id
            await session.commit()

        self.assertEqual(await self.service.run_once(now=NOW), 0)

        async with self.database.session_factory() as session:
            await self.backends.create(
                session,
                request=CreateBackendRequest(
                    capability=BackendCapability(
                        name="builtin_text",
                        version="1.0",
                        media_categories=[MediaCategory.TEXT],
                        mime_types=["text/*"],
                        runtimes=[DeviceRuntime.CPU],
                        maximum_concurrency=4,
                    ),
                    execution_mode=BackendExecutionMode.LOCAL,
                    default_timeout_seconds=60,
                ),
                now=NOW + timedelta(seconds=1),
            )
            pipeline = await self.pipelines.create(
                session,
                request=CreatePipelineRequest(
                    pipeline_id="pipeline_textdefault",
                    name="text.default",
                    media_categories=[MediaCategory.TEXT],
                    routing_priority=100,
                    stages=[
                        PipelineStageDefinition(
                            name="parse",
                            backend=BackendSelector(preferred="builtin_text"),
                            timeout_seconds=60,
                        )
                    ],
                ),
                now=NOW + timedelta(seconds=1),
            )
            await self.pipelines.publish(
                session,
                pipeline_id=pipeline.pipeline_id,
                version=pipeline.version,
                now=NOW + timedelta(seconds=2),
            )
            await session.commit()

        self.assertEqual(
            await self.service.run_once(now=NOW + timedelta(seconds=3)),
            1,
        )
        self.assertEqual(len(self.queue.notices), 1)
        self.assertEqual(self.queue.notices[0].reason, "task_routed")
        self.assertEqual(self.queue.notices[0].task_id, task_id)
        async with self.database.session_factory() as session:
            record = await self.tasks.get(session, task_id)
            self.assertIsNotNone(record)
            if record is not None:
                detail = task_detail(record)
                self.assertEqual(detail.pipeline_id, "pipeline_textdefault")
                self.assertEqual(len(detail.stages), 1)

        self.assertEqual(
            await self.service.run_once(now=NOW + timedelta(seconds=4)),
            0,
        )


if __name__ == "__main__":
    unittest.main()
