from __future__ import annotations

import asyncio
import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path

from fastapi.testclient import TestClient
from pydantic import SecretStr

from parser_serve.api import create_app
from parser_serve.persistence import Database
from parser_serve.schema.queue import StageQueueNotice
from parser_serve.schema.artifact import ArtifactListResponse, ArtifactResponse
from parser_serve.schema.authentication import CreateApiKeyResponse
from parser_serve.schema.task import CreateTaskResponse, TaskDetailResponse, TaskStatus
from parser_serve.schema.worker import (
    StageExecutionResponse,
    WorkerDetailResponse,
    WorkerHeartbeatResponse,
    WorkerLeaseResponse,
    WorkerListResponse,
    WorkerReconcileResponse,
    WorkerRegistrationResponse,
)
from parser_serve.settings import Environment, Settings


NOW = datetime(2026, 7, 24, 12, 0, tzinfo=UTC)
ORDINARY_KEY = f"parser_{'o' * 32}"
ORDINARY_HEADERS = {"Authorization": f"Bearer {ORDINARY_KEY}"}
WORKER_ID = "worker_cpuworker"


class RecordingTaskQueue:
    def __init__(self) -> None:
        self.notices: list[StageQueueNotice] = []
        self.waits: list[tuple[str, float]] = []

    async def snapshot(self) -> str:
        return str(len(self.notices))

    async def publish(self, notice: StageQueueNotice) -> None:
        self.notices.append(notice)

    async def wait(self, *, after: str, timeout_seconds: float) -> bool:
        self.waits.append((after, timeout_seconds))
        return len(self.notices) > int(after)

    async def check(self) -> None:
        return None

    async def aclose(self) -> None:
        return None


def backend_payload() -> dict[str, object]:
    return {
        "capability": {
            "name": "text_backend",
            "version": "1.0",
            "media_categories": ["text"],
            "runtimes": ["cpu"],
            "maximum_concurrency": 2,
        },
        "execution_mode": "local",
        "default_timeout_seconds": 60,
    }


def pipeline_payload() -> dict[str, object]:
    return {
        "pipeline_id": "pipeline_textparse",
        "name": "Text Pipeline",
        "media_categories": ["text"],
        "stages": [
            {
                "name": "extract",
                "backend": {"preferred": "text_backend"},
                "timeout_seconds": 60,
            },
            {
                "name": "normalize",
                "backend": {"preferred": "text_backend"},
                "depends_on": ["extract"],
                "timeout_seconds": 60,
            },
        ],
    }


def registration_payload() -> dict[str, object]:
    return {
        "worker_id": WORKER_ID,
        "name": "CPU Worker",
        "version": "0.1.0",
        "hostname": "worker-01",
        "devices": [
            {
                "device_id": "cpu-0",
                "vendor": "generic",
                "runtime": "cpu",
                "model": "Generic CPU",
            }
        ],
        "backends": [backend_payload()["capability"]],
        "labels": {"zone": "local"},
        "maximum_concurrency": 2,
    }


class WorkerApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.now = NOW
        self.temporary_directory = tempfile.TemporaryDirectory()
        database_path = Path(self.temporary_directory.name) / "workers.sqlite3"
        self.database = Database(f"sqlite+aiosqlite:///{database_path}")
        asyncio.run(self.database.create_schema_for_testing())
        self.task_queue = RecordingTaskQueue()
        self.client = TestClient(
            create_app(
                Settings(
                    environment=Environment.TEST,
                    api_keys=[SecretStr(ORDINARY_KEY)],
                    local_storage_path=Path(self.temporary_directory.name) / "objects",
                    worker_heartbeat_interval_seconds=10,
                    worker_offline_after_seconds=30,
                    stage_lease_duration_seconds=20,
                ),
                clock=lambda: self.now,
                database=self.database,
                task_queue=self.task_queue,
            )
        )
        response = self.client.post(
            "/api/v1/management/api-keys",
            headers=ORDINARY_HEADERS,
            json={
                "name": "worker credential",
                "kind": "worker",
                "worker_id": WORKER_ID,
            },
        )
        created = CreateApiKeyResponse.model_validate_json(response.content)
        self.worker_key = created.data.api_key
        self.worker_headers = {
            "Authorization": f"Bearer {self.worker_key}",
        }

    def tearDown(self) -> None:
        self.client.close()
        asyncio.run(self.database.dispose())
        self.temporary_directory.cleanup()

    def prepare_task(self) -> str:
        response = self.client.post(
            "/api/v1/management/backends",
            headers=ORDINARY_HEADERS,
            json=backend_payload(),
        )
        self.assertEqual(response.status_code, 201)
        response = self.client.post(
            "/api/v1/management/pipelines",
            headers=ORDINARY_HEADERS,
            json=pipeline_payload(),
        )
        self.assertEqual(response.status_code, 201)
        response = self.client.post(
            "/api/v1/management/pipelines/pipeline_textparse/versions/1/publish",
            headers=ORDINARY_HEADERS,
        )
        self.assertEqual(response.status_code, 200)
        response = self.client.post(
            "/api/v1/tasks",
            headers=ORDINARY_HEADERS,
            json={"source": {"type": "text", "text": "hello"}},
        )
        task = CreateTaskResponse.model_validate_json(response.content)
        response = self.client.post(
            f"/api/v1/management/tasks/{task.data.task_id}/route",
            headers=ORDINARY_HEADERS,
        )
        self.assertEqual(response.status_code, 200)
        return task.data.task_id

    def register_worker(self) -> WorkerRegistrationResponse:
        response = self.client.post(
            "/internal/v1/workers/register",
            headers=self.worker_headers,
            json=registration_payload(),
        )
        self.assertEqual(response.status_code, 200)
        return WorkerRegistrationResponse.model_validate_json(response.content)

    def test_worker_key_is_isolated_from_ordinary_api_key(self) -> None:
        response = self.client.post(
            "/internal/v1/workers/register",
            headers=ORDINARY_HEADERS,
            json=registration_payload(),
        )
        self.assertEqual(response.status_code, 401)

        response = self.client.post(
            "/api/v1/management/api-keys",
            headers=ORDINARY_HEADERS,
            json={
                "name": "other worker",
                "kind": "worker",
                "worker_id": "worker_otherworker",
            },
        )
        other = CreateApiKeyResponse.model_validate_json(response.content)
        response = self.client.post(
            "/internal/v1/workers/register",
            headers={"Authorization": f"Bearer {other.data.api_key}"},
            json=registration_payload(),
        )
        self.assertEqual(response.status_code, 401)

        response = self.client.get(
            "/api/v1/capabilities",
            headers=self.worker_headers,
        )
        self.assertEqual(response.status_code, 401)

        registered = self.register_worker()
        self.assertTrue(registered.data.accepted)
        self.assertEqual(registered.data.lease_duration_seconds, 20)

    def test_worker_can_mark_itself_draining_before_shutdown(self) -> None:
        self.register_worker()

        response = self.client.post(
            f"/internal/v1/workers/{WORKER_ID}/drain",
            headers=self.worker_headers,
        )
        self.assertEqual(response.status_code, 200)
        detail = WorkerDetailResponse.model_validate_json(response.content)
        self.assertEqual(detail.data.status, "draining")

        response = self.client.post(
            "/internal/v1/workers/lease",
            headers=self.worker_headers,
            json={"worker_id": WORKER_ID, "available_slots": 1},
        )
        self.assertEqual(response.status_code, 409)

    def test_worker_execution_protocol_completes_task(self) -> None:
        task_id = self.prepare_task()
        self.register_worker()

        response = self.client.post(
            "/internal/v1/workers/lease",
            headers=self.worker_headers,
            json={"worker_id": WORKER_ID, "available_slots": 2},
        )
        leases = WorkerLeaseResponse.model_validate_json(response.content)
        self.assertEqual([item.stage_name for item in leases.data.leases], ["extract"])
        first = leases.data.leases[0]

        self.now += timedelta(seconds=1)
        response = self.client.post(
            f"/internal/v1/workers/stages/{first.stage_id}/start",
            headers=self.worker_headers,
            json={"worker_id": WORKER_ID, "lease_token": first.lease_token},
        )
        started = StageExecutionResponse.model_validate_json(response.content)
        self.assertEqual(started.data.task_status, TaskStatus.RUNNING)

        response = self.client.post(
            f"/internal/v1/workers/stages/{first.stage_id}/progress",
            headers=self.worker_headers,
            json={
                "worker_id": WORKER_ID,
                "lease_token": first.lease_token,
                "progress_percent": 50.0,
            },
        )
        progress = StageExecutionResponse.model_validate_json(response.content)
        self.assertEqual(progress.data.progress_percent, 25.0)

        response = self.client.post(
            f"/internal/v1/workers/stages/{first.stage_id}/renew",
            headers=self.worker_headers,
            json={"worker_id": WORKER_ID, "lease_token": first.lease_token},
        )
        self.assertEqual(response.status_code, 200)

        response = self.client.post(
            f"/internal/v1/workers/stages/{first.stage_id}/complete",
            headers=self.worker_headers,
            json={
                "worker_id": WORKER_ID,
                "lease_token": first.lease_token,
                "status": "succeeded",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.task_queue.notices[-1].reason, "stage_completed")

        response = self.client.post(
            "/internal/v1/workers/lease",
            headers=self.worker_headers,
            json={"worker_id": WORKER_ID, "available_slots": 1},
        )
        second = WorkerLeaseResponse.model_validate_json(response.content).data.leases[
            0
        ]
        response = self.client.post(
            f"/internal/v1/workers/stages/{second.stage_id}/start",
            headers=self.worker_headers,
            json={"worker_id": WORKER_ID, "lease_token": second.lease_token},
        )
        self.assertEqual(response.status_code, 200)
        response = self.client.post(
            f"/internal/v1/workers/{WORKER_ID}/stages/{second.stage_id}/artifacts",
            headers=self.worker_headers,
            data={
                "lease_token": second.lease_token,
                "artifact_type": "result_json",
                "idempotency_key": "normalize-result-1",
            },
            files={
                "file": (
                    "result.json",
                    b'{"text":"hello"}',
                    "application/json",
                )
            },
        )
        self.assertEqual(response.status_code, 201, response.text)
        artifact = ArtifactResponse.model_validate_json(response.content)
        response = self.client.post(
            f"/internal/v1/workers/{WORKER_ID}/stages/{second.stage_id}/artifacts",
            headers=self.worker_headers,
            data={
                "lease_token": second.lease_token,
                "artifact_type": "result_json",
                "idempotency_key": "normalize-result-1",
            },
            files={
                "file": (
                    "result.json",
                    b'{"text":"hello"}',
                    "application/json",
                )
            },
        )
        self.assertEqual(response.status_code, 200)
        replay = ArtifactResponse.model_validate_json(response.content)
        self.assertEqual(replay.data.artifact_id, artifact.data.artifact_id)

        response = self.client.post(
            f"/internal/v1/workers/{WORKER_ID}/stages/{second.stage_id}/artifacts",
            headers=self.worker_headers,
            data={
                "lease_token": second.lease_token,
                "artifact_type": "result_json",
                "idempotency_key": "normalize-result-1",
            },
            files={
                "file": (
                    "result.json",
                    b'{"text":"different"}',
                    "application/json",
                )
            },
        )
        self.assertEqual(response.status_code, 409)
        response = self.client.post(
            f"/internal/v1/workers/stages/{second.stage_id}/complete",
            headers=self.worker_headers,
            json={
                "worker_id": WORKER_ID,
                "lease_token": second.lease_token,
                "status": "succeeded",
                "result_uri": artifact.data.storage_uri,
            },
        )
        completed = StageExecutionResponse.model_validate_json(response.content)
        self.assertEqual(completed.data.task_status, TaskStatus.SUCCEEDED)
        response = self.client.post(
            f"/internal/v1/workers/stages/{second.stage_id}/complete",
            headers=self.worker_headers,
            json={
                "worker_id": WORKER_ID,
                "lease_token": second.lease_token,
                "status": "succeeded",
                "result_uri": artifact.data.storage_uri,
            },
        )
        replayed_completion = StageExecutionResponse.model_validate_json(
            response.content
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(replayed_completion.data.task_status, TaskStatus.SUCCEEDED)

        response = self.client.post(
            f"/internal/v1/workers/stages/{second.stage_id}/complete",
            headers=self.worker_headers,
            json={
                "worker_id": WORKER_ID,
                "lease_token": second.lease_token,
                "status": "succeeded",
                "result_uri": "local:///different",
            },
        )
        self.assertEqual(response.status_code, 409)

        response = self.client.get(
            f"/api/v1/tasks/{task_id}",
            headers=ORDINARY_HEADERS,
        )
        task = TaskDetailResponse.model_validate_json(response.content)
        self.assertEqual(task.data.status, TaskStatus.SUCCEEDED)
        self.assertEqual(task.data.result_uri, artifact.data.storage_uri)

        response = self.client.get(
            f"/api/v1/tasks/{task_id}/artifacts",
            headers=ORDINARY_HEADERS,
        )
        artifacts = ArtifactListResponse.model_validate_json(response.content)
        self.assertEqual(
            [item.artifact_id for item in artifacts.items], [artifact.data.artifact_id]
        )
        self.assertEqual(artifacts.items[0].metadata["stage_id"], second.stage_id)
        response = self.client.get(
            (f"/api/v1/tasks/{task_id}/artifacts/{artifact.data.artifact_id}/content"),
            headers=ORDINARY_HEADERS,
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, b'{"text":"hello"}')

    def test_empty_lease_request_uses_bounded_queue_wait(self) -> None:
        self.register_worker()

        response = self.client.post(
            "/internal/v1/workers/lease",
            headers=self.worker_headers,
            json={
                "worker_id": WORKER_ID,
                "available_slots": 1,
                "wait_seconds": 3.0,
            },
        )

        self.assertEqual(response.status_code, 200)
        leases = WorkerLeaseResponse.model_validate_json(response.content)
        self.assertEqual(leases.data.leases, [])
        self.assertEqual(self.task_queue.waits, [("0", 3.0)])

    def test_worker_can_only_download_source_for_an_active_lease(self) -> None:
        response = self.client.post(
            "/api/v1/management/backends",
            headers=ORDINARY_HEADERS,
            json=backend_payload(),
        )
        self.assertEqual(response.status_code, 201)
        response = self.client.post(
            "/api/v1/management/pipelines",
            headers=ORDINARY_HEADERS,
            json=pipeline_payload(),
        )
        self.assertEqual(response.status_code, 201)
        response = self.client.post(
            "/api/v1/management/pipelines/pipeline_textparse/versions/1/publish",
            headers=ORDINARY_HEADERS,
        )
        self.assertEqual(response.status_code, 200)

        content = b"worker source"
        response = self.client.post(
            "/api/v1/files",
            headers=ORDINARY_HEADERS,
            files={"file": ("source.txt", content, "text/plain")},
        )
        self.assertEqual(response.status_code, 201)
        file_id = response.json()["data"]["file_id"]
        response = self.client.post(
            "/api/v1/tasks",
            headers=ORDINARY_HEADERS,
            json={
                "source": {
                    "type": "uploaded_file",
                    "file_id": file_id,
                }
            },
        )
        task = CreateTaskResponse.model_validate_json(response.content)
        response = self.client.post(
            f"/api/v1/management/tasks/{task.data.task_id}/route",
            headers=ORDINARY_HEADERS,
        )
        self.assertEqual(response.status_code, 200)
        self.register_worker()

        content_url = f"/internal/v1/workers/{WORKER_ID}/files/{file_id}/content"
        response = self.client.get(content_url, headers=self.worker_headers)
        self.assertEqual(response.status_code, 403)

        response = self.client.post(
            "/internal/v1/workers/lease",
            headers=self.worker_headers,
            json={"worker_id": WORKER_ID, "available_slots": 1},
        )
        leases = WorkerLeaseResponse.model_validate_json(response.content)
        self.assertEqual(len(leases.data.leases), 1)

        response = self.client.get(content_url, headers=self.worker_headers)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, content)

        response = self.client.get(
            f"/internal/v1/workers/worker_otherworker/files/{file_id}/content",
            headers=self.worker_headers,
        )
        self.assertEqual(response.status_code, 403)

    def test_heartbeat_management_drain_and_reconcile(self) -> None:
        self.register_worker()
        heartbeat = {
            "worker_id": WORKER_ID,
            "sequence": 0,
            "status": "online",
            "resources": {
                "cpu_percent": 10.0,
                "memory_used_bytes": 100,
                "memory_total_bytes": 1000,
                "running_tasks": 0,
                "leased_tasks": 0,
                "health_checks": [
                    {
                        "name": "ffmpeg",
                        "healthy": True,
                    }
                ],
            },
            "timestamp": self.now.isoformat(),
        }
        response = self.client.post(
            "/internal/v1/workers/heartbeat",
            headers=self.worker_headers,
            json=heartbeat,
        )
        accepted = WorkerHeartbeatResponse.model_validate_json(response.content)
        self.assertTrue(accepted.data.accepted)

        response = self.client.post(
            "/internal/v1/workers/heartbeat",
            headers=self.worker_headers,
            json=heartbeat,
        )
        self.assertEqual(response.status_code, 409)

        invalid_device = {
            **heartbeat,
            "sequence": 1,
            "devices": [{"device_id": "cuda-unknown"}],
        }
        response = self.client.post(
            "/internal/v1/workers/heartbeat",
            headers=self.worker_headers,
            json=invalid_device,
        )
        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json()["error"]["code"], "VALIDATION_ERROR")

        response = self.client.get(
            "/api/v1/management/workers",
            headers=ORDINARY_HEADERS,
            params={"runtimes": "cpu", "labels": "zone=local"},
        )
        workers = WorkerListResponse.model_validate_json(response.content)
        self.assertEqual(len(workers.items), 1)
        self.assertEqual(
            workers.items[0].resources.health_checks[0].name
            if workers.items[0].resources is not None
            else None,
            "ffmpeg",
        )

        response = self.client.patch(
            f"/api/v1/management/workers/{WORKER_ID}",
            headers=ORDINARY_HEADERS,
            json={"draining": True},
        )
        detail = WorkerDetailResponse.model_validate_json(response.content)
        self.assertEqual(detail.data.status, "draining")

        response = self.client.post(
            "/internal/v1/workers/lease",
            headers=self.worker_headers,
            json={"worker_id": WORKER_ID, "available_slots": 1},
        )
        self.assertEqual(response.status_code, 409)

        self.client.patch(
            f"/api/v1/management/workers/{WORKER_ID}",
            headers=ORDINARY_HEADERS,
            json={"draining": False},
        )
        self.now += timedelta(seconds=31)
        response = self.client.post(
            "/api/v1/management/workers/reconcile",
            headers=ORDINARY_HEADERS,
        )
        reconciled = WorkerReconcileResponse.model_validate_json(response.content)
        self.assertEqual(reconciled.data.offline_worker_ids, [WORKER_ID])


if __name__ == "__main__":
    unittest.main()
