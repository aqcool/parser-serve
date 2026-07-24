from __future__ import annotations

import asyncio
import os
import unittest
from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import inspect

from parser_serve.control import StageScheduler, TaskRouter
from parser_serve.persistence import Database
from parser_serve.persistence.registry import BackendRepository, PipelineRepository
from parser_serve.persistence.tasks import TaskRepository
from parser_serve.persistence.workers import WorkerRepository
from parser_serve.schema.backend import (
    BackendCapability,
    BackendExecutionMode,
    CreateBackendRequest,
)
from parser_serve.schema.common import MediaCategory
from parser_serve.schema.hardware import DeviceInfo, DeviceRuntime, HardwareVendor
from parser_serve.schema.pipeline import (
    BackendSelector,
    CreatePipelineRequest,
    PipelineStageDefinition,
)
from parser_serve.schema.task import CreateTaskRequest
from parser_serve.schema.worker import WorkerLeaseRequest, WorkerRegistrationRequest


POSTGRES_URL = os.environ.get("PARSER_SERVE_TEST_POSTGRES_URL")
NOW = datetime(2026, 7, 24, 12, 0, tzinfo=UTC)


@unittest.skipUnless(
    POSTGRES_URL,
    "PARSER_SERVE_TEST_POSTGRES_URL is required for PostgreSQL integration",
)
class PostgresIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        if POSTGRES_URL is None:
            self.fail("PostgreSQL URL disappeared after test discovery")
        self.database = Database(POSTGRES_URL)

    async def asyncTearDown(self) -> None:
        await self.database.dispose()

    async def test_migrated_schema_contains_control_plane_tables(self) -> None:
        async with self.database.engine.connect() as connection:
            tables = await connection.run_sync(
                lambda sync_connection: set(inspect(sync_connection).get_table_names())
            )

        self.assertTrue(
            {
                "api_keys",
                "artifacts",
                "backends",
                "callback_attempts",
                "callback_deliveries",
                "events",
                "pipelines",
                "stages",
                "tasks",
                "uploaded_files",
                "workers",
            }.issubset(tables)
        )

    async def test_skip_locked_allows_only_one_worker_to_claim_stage(self) -> None:
        backends = BackendRepository()
        pipelines = PipelineRepository()
        tasks = TaskRepository()
        workers = WorkerRepository()
        scheduler = StageScheduler(lease_duration_seconds=30)
        suffix = uuid4().hex[:8]
        backend_name = f"postgres_text_{suffix}"
        pipeline_id = f"pipeline_postgres{suffix}"
        capability = BackendCapability(
            name=backend_name,
            version="1.0",
            media_categories=[MediaCategory.TEXT],
            runtimes=[DeviceRuntime.CPU],
            maximum_concurrency=4,
        )

        async with self.database.session_factory() as session:
            await backends.create(
                session,
                request=CreateBackendRequest(
                    capability=capability,
                    execution_mode=BackendExecutionMode.LOCAL,
                    default_timeout_seconds=60,
                ),
                now=NOW,
            )
            pipeline = await pipelines.create(
                session,
                request=CreatePipelineRequest(
                    pipeline_id=pipeline_id,
                    name="PostgreSQL Test Pipeline",
                    media_categories=[MediaCategory.TEXT],
                    stages=[
                        PipelineStageDefinition(
                            name="extract",
                            backend=BackendSelector(preferred=backend_name),
                            timeout_seconds=60,
                        )
                    ],
                ),
                now=NOW,
            )
            await pipelines.publish(
                session,
                pipeline_id=pipeline.pipeline_id,
                version=pipeline.version,
                now=NOW,
            )
            task, _ = await tasks.create(
                session,
                request=CreateTaskRequest.model_validate(
                    {"source": {"type": "text", "text": "postgres lock"}}
                ),
                idempotency_key=None,
                now=NOW,
            )
            await TaskRouter().route(
                session,
                task_id=task.task_id,
                now=NOW,
            )
            for suffix in ("alpha", "bravo"):
                worker_id = f"worker_postgres{suffix}"
                await workers.register(
                    session,
                    request=WorkerRegistrationRequest(
                        worker_id=worker_id,
                        name=f"PostgreSQL Worker {suffix}",
                        version="0.1.0",
                        hostname=f"postgres-{suffix}",
                        devices=[
                            DeviceInfo(
                                device_id="cpu-0",
                                vendor=HardwareVendor.GENERIC,
                                runtime=DeviceRuntime.CPU,
                                model="Test CPU",
                                total_memory_bytes=1_000_000,
                            )
                        ],
                        backends=[capability],
                        maximum_concurrency=1,
                    ),
                    now=NOW,
                )
            await session.commit()

        first_has_lock = asyncio.Event()

        async def claim(worker_id: str, *, hold_lock: bool) -> int:
            async with self.database.session_factory() as session:
                leases = await scheduler.lease(
                    session,
                    request=WorkerLeaseRequest(
                        worker_id=worker_id,
                        available_slots=1,
                    ),
                    now=NOW,
                )
                if hold_lock:
                    first_has_lock.set()
                    await asyncio.sleep(0.2)
                await session.commit()
                return len(leases)

        first = asyncio.create_task(claim("worker_postgresalpha", hold_lock=True))
        await first_has_lock.wait()
        second = asyncio.create_task(claim("worker_postgresbravo", hold_lock=False))
        claimed = await asyncio.gather(first, second)

        self.assertEqual(sum(claimed), 1)
        self.assertEqual(claimed[0], 1)
        self.assertEqual(claimed[1], 0)


if __name__ == "__main__":
    unittest.main()
