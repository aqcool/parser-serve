from __future__ import annotations

import asyncio
import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient
from pydantic import SecretStr

from parser_serve.api import create_app
from parser_serve.persistence import Database
from parser_serve.persistence.models import (
    ArtifactRecord,
    EventRecord,
    TaskRecord,
    UploadedFileRecord,
)
from parser_serve.schema.maintenance import RetentionRunResponse
from parser_serve.settings import Environment, Settings
from parser_serve.storage import LocalFileStorage


NOW = datetime(2026, 7, 24, 12, 0, tzinfo=UTC)
API_KEY = f"parser_{'l' * 32}"
HEADERS = {"Authorization": f"Bearer {API_KEY}"}


class RetentionApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        root = Path(self.temporary_directory.name)
        self.storage_root = root / "storage"
        self.database = Database(f"sqlite+aiosqlite:///{root / 'retention.sqlite3'}")
        asyncio.run(self.database.create_schema_for_testing())
        self.storage = LocalFileStorage(self.storage_root)
        asyncio.run(self._seed())
        self.client = TestClient(
            create_app(
                Settings(
                    environment=Environment.TEST,
                    api_keys=[SecretStr(API_KEY)],
                    uploaded_file_retention_seconds=3600,
                    artifact_retention_seconds=3600,
                    event_retention_seconds=3600,
                    retention_cleanup_enabled=False,
                ),
                clock=lambda: NOW,
                database=self.database,
                storage=self.storage,
            )
        )

    def tearDown(self) -> None:
        self.client.close()
        asyncio.run(self.database.dispose())
        self.temporary_directory.cleanup()

    def _object(self, key: str) -> None:
        path = self.storage_root.joinpath(*key.split("/"))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(key.encode())

    async def _seed(self) -> None:
        old = NOW - timedelta(hours=2)
        expired = NOW - timedelta(minutes=1)
        active_key = "uploads/active"
        unused_key = "uploads/unused"
        artifact_key = "artifacts/result"
        active_artifact_key = "artifacts/active"
        for key in (active_key, unused_key, artifact_key, active_artifact_key):
            self._object(key)

        async with self.database.session_factory() as session:
            active_task = TaskRecord(
                task_id="task_retentionactive",
                status="running",
                progress_percent=10.0,
                source_payload={
                    "type": "uploaded_file",
                    "file_id": "file_retentionactive",
                },
                options_payload={},
                priority=0,
                created_at=old,
                updated_at=old,
            )
            completed_task = TaskRecord(
                task_id="task_retentiondone",
                status="succeeded",
                progress_percent=100.0,
                source_payload={"type": "text", "text": "done"},
                options_payload={},
                priority=0,
                result_uri="local:///artifacts/result",
                created_at=old,
                updated_at=old,
                completed_at=old,
            )
            session.add_all(
                [
                    active_task,
                    completed_task,
                    UploadedFileRecord(
                        file_id="file_retentionactive",
                        filename="active.txt",
                        mime_type="text/plain",
                        media_category="text",
                        size_bytes=1,
                        sha256="a" * 64,
                        storage_key=active_key,
                        storage_uri="local:///uploads/active",
                        created_at=old,
                        expires_at=expired,
                    ),
                    UploadedFileRecord(
                        file_id="file_retentionunused",
                        filename="unused.txt",
                        mime_type="text/plain",
                        media_category="text",
                        size_bytes=1,
                        sha256="b" * 64,
                        storage_key=unused_key,
                        storage_uri="local:///uploads/unused",
                        created_at=old,
                        expires_at=expired,
                    ),
                    ArtifactRecord(
                        artifact_id="artifact_retentionresult",
                        task_id=completed_task.task_id,
                        artifact_type="result_json",
                        filename="result.json",
                        mime_type="application/json",
                        size_bytes=1,
                        sha256="c" * 64,
                        storage_key=artifact_key,
                        storage_uri="local:///artifacts/result",
                        artifact_metadata={},
                        created_at=old,
                        expires_at=expired,
                    ),
                    ArtifactRecord(
                        artifact_id="artifact_retentionactive",
                        task_id=active_task.task_id,
                        artifact_type="intermediate",
                        filename="active.json",
                        mime_type="application/json",
                        size_bytes=1,
                        sha256="d" * 64,
                        storage_key=active_artifact_key,
                        storage_uri="local:///artifacts/active",
                        artifact_metadata={},
                        created_at=old,
                        expires_at=expired,
                    ),
                    EventRecord(
                        event_id="event_retentionworker",
                        event_type="worker.status_changed",
                        worker_id="worker_retention1",
                        payload={
                            "type": "worker.status_changed",
                            "worker_id": "worker_retention1",
                            "previous_status": "online",
                            "current_status": "offline",
                        },
                        callback_processed=False,
                        occurred_at=old,
                    ),
                    EventRecord(
                        event_id="event_retentionprocessed",
                        event_type="task.created",
                        task_id=completed_task.task_id,
                        payload={
                            "type": "task.created",
                            "task_id": completed_task.task_id,
                        },
                        callback_processed=True,
                        occurred_at=old,
                    ),
                    EventRecord(
                        event_id="event_retentionpending",
                        event_type="task.created",
                        task_id=completed_task.task_id,
                        payload={
                            "type": "task.created",
                            "task_id": completed_task.task_id,
                        },
                        callback_processed=False,
                        occurred_at=old,
                    ),
                ]
            )
            await session.commit()

    def test_dry_run_then_cleanup_preserves_active_sources_and_callback_work(
        self,
    ) -> None:
        dry_response = self.client.post(
            "/api/v1/management/maintenance/retention/run",
            headers=HEADERS,
            json={"dry_run": True, "maximum_records": 100},
        )
        dry = RetentionRunResponse.model_validate_json(dry_response.content)

        self.assertEqual(dry_response.status_code, 200)
        self.assertTrue(dry.data.dry_run)
        self.assertEqual(dry.data.uploaded_files_selected, 1)
        self.assertEqual(dry.data.uploaded_files_skipped_active, 1)
        self.assertEqual(dry.data.artifacts_selected, 1)
        self.assertEqual(dry.data.artifacts_skipped_active, 1)
        self.assertEqual(dry.data.events_selected, 2)
        self.assertTrue((self.storage_root / "uploads/unused").is_file())

        response = self.client.post(
            "/api/v1/management/maintenance/retention/run",
            headers=HEADERS,
            json={"dry_run": False, "maximum_records": 100},
        )
        result = RetentionRunResponse.model_validate_json(response.content)

        self.assertEqual(response.status_code, 200)
        self.assertFalse(result.data.dry_run)
        self.assertEqual(result.data.storage_delete_failures, 0)
        self.assertFalse((self.storage_root / "uploads/unused").exists())
        self.assertFalse((self.storage_root / "artifacts/result").exists())
        self.assertTrue((self.storage_root / "artifacts/active").is_file())
        self.assertTrue((self.storage_root / "uploads/active").is_file())
        asyncio.run(self._assert_persistent_state())

    async def _assert_persistent_state(self) -> None:
        async with self.database.session_factory() as session:
            self.assertIsNotNone(
                await session.get(UploadedFileRecord, "file_retentionactive")
            )
            self.assertIsNone(
                await session.get(UploadedFileRecord, "file_retentionunused")
            )
            self.assertIsNone(
                await session.get(ArtifactRecord, "artifact_retentionresult")
            )
            self.assertIsNotNone(
                await session.get(ArtifactRecord, "artifact_retentionactive")
            )
            task = await session.get(TaskRecord, "task_retentiondone")
            self.assertIsNotNone(task)
            if task is not None:
                self.assertIsNone(task.result_uri)
            self.assertIsNone(await session.get(EventRecord, "event_retentionworker"))
            self.assertIsNone(
                await session.get(EventRecord, "event_retentionprocessed")
            )
            self.assertIsNotNone(
                await session.get(EventRecord, "event_retentionpending")
            )

    def test_retention_requires_api_key(self) -> None:
        response = self.client.post(
            "/api/v1/management/maintenance/retention/run",
            json={},
        )

        self.assertEqual(response.status_code, 401)

    def test_storage_failure_preserves_metadata_for_retry(self) -> None:
        with patch.object(
            self.storage,
            "delete",
            AsyncMock(side_effect=RuntimeError("storage unavailable")),
        ):
            response = self.client.post(
                "/api/v1/management/maintenance/retention/run",
                headers=HEADERS,
                json={"dry_run": False, "maximum_records": 100},
            )
        result = RetentionRunResponse.model_validate_json(response.content)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(result.data.storage_delete_failures, 2)
        asyncio.run(self._assert_failed_deletions_remain())

    async def _assert_failed_deletions_remain(self) -> None:
        async with self.database.session_factory() as session:
            self.assertIsNotNone(
                await session.get(UploadedFileRecord, "file_retentionunused")
            )
            self.assertIsNotNone(
                await session.get(ArtifactRecord, "artifact_retentionresult")
            )


if __name__ == "__main__":
    unittest.main()
