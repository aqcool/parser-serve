from __future__ import annotations

import asyncio
import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path

from fastapi.testclient import TestClient
from pydantic import SecretStr, ValidationError

from parser_serve.api import create_app
from parser_serve.persistence import Database
from parser_serve.persistence.models import (
    ArtifactRecord,
    CallbackDeliveryRecord,
    StageRecord,
    TaskRecord,
    UploadedFileRecord,
    WorkerRecord,
)
from parser_serve.schema.dashboard import (
    DashboardQuery,
    DashboardResponse,
    MetricInterval,
)
from parser_serve.settings import Environment, Settings
from parser_serve.storage import LocalFileStorage


NOW = datetime(2026, 7, 24, 12, 0, tzinfo=UTC)
API_KEY = f"parser_{'d' * 32}"
HEADERS = {"Authorization": f"Bearer {API_KEY}"}


def task(
    task_id: str,
    status: str,
    created_at: datetime,
    *,
    media_category: str,
    started_at: datetime | None = None,
    completed_at: datetime | None = None,
) -> TaskRecord:
    return TaskRecord(
        task_id=task_id,
        status=status,
        progress_percent=100.0 if completed_at else 0.0,
        source_payload={"type": "text", "text": "dashboard"},
        source_metadata_payload={
            "mime_type": "text/plain",
            "media_category": media_category,
            "attributes": {},
        },
        media_category=media_category,
        options_payload={},
        pipeline_id="pipeline_dashboard1",
        pipeline_version=1,
        priority=0,
        started_at=started_at,
        completed_at=completed_at,
        created_at=created_at,
        updated_at=completed_at or created_at,
    )


class DashboardApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        root = Path(self.temporary_directory.name)
        self.database = Database(f"sqlite+aiosqlite:///{root / 'dashboard.sqlite3'}")
        asyncio.run(self.database.create_schema_for_testing())
        asyncio.run(self._seed())
        self.client = TestClient(
            create_app(
                Settings(
                    environment=Environment.TEST,
                    api_keys=[SecretStr(API_KEY)],
                ),
                clock=lambda: NOW,
                database=self.database,
                storage=LocalFileStorage(root / "storage"),
            )
        )

    def tearDown(self) -> None:
        self.client.close()
        asyncio.run(self.database.dispose())
        self.temporary_directory.cleanup()

    async def _seed(self) -> None:
        succeeded = task(
            "task_dashboard1",
            "succeeded",
            NOW - timedelta(hours=2),
            media_category="document",
            started_at=NOW - timedelta(minutes=90),
            completed_at=NOW - timedelta(minutes=60),
        )
        failed = task(
            "task_dashboard2",
            "failed",
            NOW - timedelta(hours=1),
            media_category="document",
            started_at=NOW - timedelta(minutes=50),
            completed_at=NOW - timedelta(minutes=30),
        )
        pending = task(
            "task_dashboard3",
            "pending",
            NOW - timedelta(minutes=20),
            media_category="image",
        )
        stages = [
            StageRecord(
                stage_id="stage_dashboard1",
                task_id=succeeded.task_id,
                name="parse",
                position=0,
                depends_on_payload=[],
                optional=False,
                timeout_seconds=60,
                status="succeeded",
                progress_percent=100.0,
                backend_id="backend_dashboard1",
                backend_version="1.0",
                backend_candidates_payload=["backend_dashboard1"],
                required_runtimes_payload=["cuda"],
                worker_id="worker_dashboard1",
                runtime="cuda",
                attempt=1,
                maximum_attempts=2,
                parameters={},
                retry_policy_payload={},
                available_at=succeeded.created_at,
                started_at=succeeded.started_at,
                completed_at=succeeded.completed_at,
                created_at=succeeded.created_at,
                updated_at=succeeded.completed_at,
            ),
            StageRecord(
                stage_id="stage_dashboard2",
                task_id=failed.task_id,
                name="parse",
                position=0,
                depends_on_payload=[],
                optional=False,
                timeout_seconds=60,
                status="failed",
                progress_percent=30.0,
                backend_id="backend_dashboard1",
                backend_version="1.0",
                backend_candidates_payload=[
                    "backend_preferred1",
                    "backend_dashboard1",
                ],
                required_runtimes_payload=["cuda"],
                worker_id="worker_dashboard1",
                runtime="cuda",
                attempt=1,
                maximum_attempts=2,
                parameters={},
                retry_policy_payload={},
                available_at=failed.created_at,
                error_payload={
                    "code": "TIMEOUT",
                    "message": "timed out",
                    "retryable": False,
                    "field_violations": [],
                    "context": {},
                },
                started_at=failed.started_at,
                completed_at=failed.completed_at,
                created_at=failed.created_at,
                updated_at=failed.completed_at,
            ),
        ]
        worker = WorkerRecord(
            worker_id="worker_dashboard1",
            name="Dashboard GPU",
            version="1.0",
            hostname="gpu-1",
            status="online",
            enabled=True,
            maximum_concurrency=2,
            scheduling_weight=100,
            devices_payload=[
                {
                    "device_id": "cuda-0",
                    "vendor": "nvidia",
                    "runtime": "cuda",
                    "model": "Test GPU",
                    "total_memory_bytes": 1000,
                    "driver_version": None,
                    "runtime_version": None,
                }
            ],
            device_usage_payload=[
                {
                    "device_id": "cuda-0",
                    "utilization_percent": 50.0,
                    "memory_used_bytes": 400,
                    "memory_total_bytes": 1000,
                    "temperature_celsius": 45.0,
                }
            ],
            backends_payload=[],
            labels_payload={},
            resource_payload={
                "cpu_percent": 20.0,
                "memory_used_bytes": 100,
                "memory_total_bytes": 1000,
                "running_tasks": 1,
                "leased_tasks": 1,
            },
            heartbeat_sequence=1,
            last_heartbeat_at=NOW,
            created_at=NOW - timedelta(days=1),
            updated_at=NOW,
        )
        callbacks = [
            CallbackDeliveryRecord(
                delivery_id="delivery_dash001",
                event_id="event_dashboard1",
                event_type="task.succeeded",
                task_id=succeeded.task_id,
                target_url="https://callback.example/hook",
                status="succeeded",
                attempt=1,
                maximum_attempts=3,
                event_payload={},
                created_at=NOW - timedelta(minutes=59),
                updated_at=NOW - timedelta(minutes=59),
            ),
            CallbackDeliveryRecord(
                delivery_id="delivery_dash002",
                event_id="event_dashboard2",
                event_type="task.failed",
                task_id=failed.task_id,
                target_url="https://callback.example/hook",
                status="retry_wait",
                attempt=1,
                maximum_attempts=3,
                event_payload={},
                next_attempt_at=NOW + timedelta(minutes=1),
                created_at=NOW - timedelta(minutes=29),
                updated_at=NOW - timedelta(minutes=29),
            ),
        ]
        upload = UploadedFileRecord(
            file_id="file_dashboard1",
            filename="source.pdf",
            mime_type="application/pdf",
            media_category="document",
            size_bytes=100,
            sha256="a" * 64,
            storage_key="uploads/dashboard",
            storage_uri="local:///uploads/dashboard",
            created_at=NOW - timedelta(minutes=100),
        )
        artifacts = [
            ArtifactRecord(
                artifact_id="artifact_dash001",
                task_id=succeeded.task_id,
                artifact_type="result_json",
                filename="result.json",
                mime_type="application/json",
                size_bytes=20,
                sha256="b" * 64,
                storage_key="artifacts/result",
                storage_uri="local:///artifacts/result",
                artifact_metadata={},
                created_at=NOW - timedelta(minutes=59),
            ),
            ArtifactRecord(
                artifact_id="artifact_dash002",
                task_id=succeeded.task_id,
                artifact_type="extracted_image",
                filename="page.png",
                mime_type="image/png",
                size_bytes=30,
                sha256="c" * 64,
                storage_key="artifacts/page",
                storage_uri="local:///artifacts/page",
                artifact_metadata={},
                created_at=NOW - timedelta(minutes=58),
            ),
        ]
        async with self.database.session_factory() as session:
            session.add_all(
                [
                    succeeded,
                    failed,
                    pending,
                    *stages,
                    worker,
                    *callbacks,
                    upload,
                    *artifacts,
                ]
            )
            await session.commit()

    def test_summary_aggregates_all_operational_sections(self) -> None:
        response = self.client.get(
            "/api/v1/management/dashboard/summary",
            headers=HEADERS,
        )

        self.assertEqual(response.status_code, 200, response.text)
        dashboard = DashboardResponse.model_validate_json(response.content).data
        self.assertEqual(dashboard.tasks.total_tasks, 3)
        self.assertEqual(dashboard.tasks.succeeded_tasks, 1)
        self.assertEqual(dashboard.tasks.failed_tasks, 1)
        self.assertAlmostEqual(dashboard.tasks.success_rate, 1 / 3)
        self.assertEqual(dashboard.tasks.average_wait_ms, 20 * 60 * 1000)
        self.assertEqual(dashboard.workers.total_workers, 1)
        self.assertEqual(dashboard.workers.used_concurrency, 1)
        self.assertEqual(dashboard.callbacks.total_deliveries, 2)
        self.assertEqual(dashboard.callbacks.pending_retries, 1)
        self.assertEqual(dashboard.storage.objects, 3)
        self.assertEqual(dashboard.storage.original_bytes, 100)
        self.assertEqual(dashboard.storage.artifact_bytes, 30)
        self.assertEqual(dashboard.storage.result_bytes, 20)
        self.assertEqual(dashboard.backends[0].calls, 2)
        self.assertEqual(dashboard.backends[0].failures, 1)
        self.assertEqual(dashboard.backends[0].timeouts, 1)
        self.assertEqual(dashboard.backends[0].fallbacks, 1)
        self.assertEqual(dashboard.runtimes[0].runtime, "cuda")
        self.assertEqual(dashboard.runtimes[0].average_utilization_percent, 50.0)
        self.assertEqual(len(dashboard.series), 3)
        self.assertEqual(len(dashboard.series[0].points), 24)

    def test_summary_filters_tasks_backend_runtime_and_media(self) -> None:
        response = self.client.get(
            "/api/v1/management/dashboard/summary",
            headers=HEADERS,
            params={
                "media_category": "document",
                "runtime": "cuda",
                "backend_id": "backend_dashboard1",
            },
        )

        self.assertEqual(response.status_code, 200, response.text)
        dashboard = DashboardResponse.model_validate_json(response.content).data
        self.assertEqual(dashboard.tasks.total_tasks, 2)
        self.assertEqual(dashboard.backends[0].calls, 2)
        self.assertEqual(dashboard.workers.total_workers, 1)

    def test_empty_window_and_invalid_range_are_typed(self) -> None:
        response = self.client.get(
            "/api/v1/management/dashboard/summary",
            headers=HEADERS,
            params={
                "start_time": (NOW - timedelta(days=3)).isoformat(),
                "end_time": (NOW - timedelta(days=2)).isoformat(),
            },
        )
        dashboard = DashboardResponse.model_validate_json(response.content).data
        self.assertEqual(dashboard.tasks.total_tasks, 0)
        self.assertEqual(dashboard.tasks.success_rate, 0.0)

        response = self.client.get(
            "/api/v1/management/dashboard/summary",
            headers=HEADERS,
            params={
                "start_time": NOW.isoformat(),
                "end_time": (NOW - timedelta(hours=1)).isoformat(),
            },
        )
        self.assertEqual(response.status_code, 422)

    def test_schema_limits_number_of_series_points(self) -> None:
        with self.assertRaisesRegex(ValidationError, "10000 intervals"):
            DashboardQuery(
                start_time=NOW - timedelta(days=8),
                end_time=NOW,
                interval=MetricInterval.MINUTE,
            )


if __name__ == "__main__":
    unittest.main()
