from __future__ import annotations

import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path

import httpx
from pydantic import SecretStr

from parser_serve.api import create_app
from parser_serve.backends import builtin_cpu_backends
from parser_serve.persistence import Database
from parser_serve.schema.artifact import ArtifactListResponse
from parser_serve.schema.hardware import DeviceInfo, DeviceRuntime, HardwareVendor
from parser_serve.schema.result import ParseResultResponse
from parser_serve.schema.stage import StageDetailResponse, StageListResponse
from parser_serve.schema.task import CreateTaskResponse, TaskDetailResponse, TaskStatus
from parser_serve.schema.worker import WorkerRegistrationRequest
from parser_serve.settings import Environment, Settings
from parser_serve.storage import LocalFileStorage
from parser_serve.worker import HttpWorkerControlClient, WorkerAgent


NOW = datetime(2026, 7, 24, 12, 0, tzinfo=UTC)
ORDINARY_KEY = f"parser_{'e' * 32}"
WORKER_KEY = f"parser_{'w' * 32}"
ORDINARY_HEADERS = {"Authorization": f"Bearer {ORDINARY_KEY}"}
WORKER_ID = "worker_httpe2e12"


class WorkerHttpEndToEndTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        root = Path(self.temporary_directory.name)
        self.database = Database(f"sqlite+aiosqlite:///{root / 'worker-e2e.sqlite3'}")
        await self.database.create_schema_for_testing()
        app = create_app(
            Settings(
                environment=Environment.TEST,
                api_keys=[SecretStr(ORDINARY_KEY)],
                worker_api_keys=[SecretStr(WORKER_KEY)],
                stage_lease_duration_seconds=60,
            ),
            clock=lambda: NOW,
            database=self.database,
            storage=LocalFileStorage(root / "objects"),
        )
        self.http = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://testserver",
            headers={"Authorization": f"Bearer {WORKER_KEY}"},
        )
        self.worker_client = HttpWorkerControlClient(
            base_url="http://testserver",
            api_key=WORKER_KEY,
            client=self.http,
        )

    async def asyncTearDown(self) -> None:
        await self.http.aclose()
        await self.database.dispose()
        self.temporary_directory.cleanup()

    async def test_text_task_executes_through_worker_http_protocol(self) -> None:
        registry = builtin_cpu_backends()
        text_capability = registry.get("builtin_text", "1.0").capability
        response = await self.http.post(
            "/api/v1/management/backends",
            headers=ORDINARY_HEADERS,
            json={
                "capability": text_capability.model_dump(mode="json"),
                "execution_mode": "local",
                "default_timeout_seconds": 30,
                "maximum_attempts": 2,
            },
        )
        self.assertEqual(response.status_code, 201, response.text)
        response = await self.http.post(
            "/api/v1/management/pipelines",
            headers=ORDINARY_HEADERS,
            json={
                "pipeline_id": "pipeline_httpe2e12",
                "name": "Built-in text",
                "media_categories": ["text"],
                "stages": [
                    {
                        "name": "parse",
                        "backend": {"preferred": "builtin_text"},
                        "timeout_seconds": 30,
                    }
                ],
            },
        )
        self.assertEqual(response.status_code, 201, response.text)
        response = await self.http.post(
            "/api/v1/management/pipelines/pipeline_httpe2e12/versions/1/publish",
            headers=ORDINARY_HEADERS,
        )
        self.assertEqual(response.status_code, 200, response.text)

        response = await self.http.post(
            "/api/v1/tasks",
            headers=ORDINARY_HEADERS,
            json={
                "source": {
                    "type": "text",
                    "text": "# End to end\n\nWorker output",
                    "mime_type": "text/markdown",
                    "filename": "input.md",
                }
            },
        )
        task = CreateTaskResponse.model_validate_json(response.content)
        response = await self.http.post(
            f"/api/v1/management/tasks/{task.data.task_id}/route",
            headers=ORDINARY_HEADERS,
        )
        self.assertEqual(response.status_code, 200, response.text)

        registration = WorkerRegistrationRequest(
            worker_id=WORKER_ID,
            name="HTTP E2E Worker",
            version="0.1.0",
            hostname="worker-e2e",
            devices=[
                DeviceInfo(
                    device_id="cpu-0",
                    vendor=HardwareVendor.GENERIC,
                    runtime=DeviceRuntime.CPU,
                    model="Test CPU",
                )
            ],
            backends=list(registry.capabilities),
            maximum_concurrency=1,
        )
        registered = await self.worker_client.register(registration)
        self.assertTrue(registered.data.accepted)

        executed = await WorkerAgent(
            worker_id=WORKER_ID,
            client=self.worker_client,
            backends=registry,
            maximum_concurrency=1,
            lease_renew_interval_seconds=20,
        ).run_once()
        self.assertEqual(executed, 1)

        response = await self.http.get(
            f"/api/v1/tasks/{task.data.task_id}",
            headers=ORDINARY_HEADERS,
        )
        detail = TaskDetailResponse.model_validate_json(response.content)
        self.assertEqual(detail.data.status, TaskStatus.SUCCEEDED)
        self.assertIsNotNone(detail.data.result_uri)

        response = await self.http.get(
            f"/api/v1/tasks/{task.data.task_id}/stages",
            headers=ORDINARY_HEADERS,
        )
        stages = StageListResponse.model_validate_json(response.content)
        self.assertEqual(len(stages.items), 1)
        self.assertEqual(stages.items[0].status, "succeeded")
        response = await self.http.get(
            (f"/api/v1/tasks/{task.data.task_id}/stages/{stages.items[0].stage_id}"),
            headers=ORDINARY_HEADERS,
        )
        stage = StageDetailResponse.model_validate_json(response.content)
        self.assertEqual(stage.data.stage_id, stages.items[0].stage_id)

        response = await self.http.get(
            f"/api/v1/tasks/{task.data.task_id}/result",
            headers=ORDINARY_HEADERS,
        )
        result = ParseResultResponse.model_validate_json(response.content)
        self.assertEqual(result.data.task_id, task.data.task_id)
        self.assertIn("End to end", result.data.model_dump_json())
        response = await self.http.get(
            f"/api/v1/tasks/{task.data.task_id}/result/content",
            headers=ORDINARY_HEADERS,
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["content-type"], "application/json")
        self.assertIn(b"End to end", response.content)

        response = await self.http.get(
            f"/api/v1/tasks/{task.data.task_id}/artifacts",
            headers=ORDINARY_HEADERS,
        )
        artifacts = ArtifactListResponse.model_validate_json(response.content)
        self.assertEqual(len(artifacts.items), 1)
        self.assertEqual(artifacts.items[0].filename, "result.json")
        response = await self.http.get(
            (
                f"/api/v1/tasks/{task.data.task_id}/artifacts/"
                f"{artifacts.items[0].artifact_id}/content"
            ),
            headers=ORDINARY_HEADERS,
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"End to end", response.content)


if __name__ == "__main__":
    unittest.main()
