from __future__ import annotations

import asyncio
import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path

from fastapi.testclient import TestClient
from pydantic import SecretStr

from parser_serve.api import create_app
from parser_serve.persistence import Database
from parser_serve.schema.error import ErrorCode
from parser_serve.schema.task import (
    CreateTaskResponse,
    TaskDetailResponse,
    TaskListResponse,
    TaskStatus,
)
from parser_serve.settings import Environment, Settings


NOW = datetime(2026, 7, 24, 12, 0, tzinfo=UTC)
API_KEY = f"parser_{'t' * 32}"
AUTH_HEADERS = {"Authorization": f"Bearer {API_KEY}"}


def task_payload(text: str = "hello") -> dict[str, object]:
    return {
        "source": {
            "type": "text",
            "text": text,
            "filename": "note.txt",
        },
        "client_reference": "external-42",
    }


class TaskApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        database_path = Path(self.temporary_directory.name) / "tasks.sqlite3"
        self.database = Database(f"sqlite+aiosqlite:///{database_path}")
        asyncio.run(self.database.create_schema_for_testing())
        settings = Settings(
            environment=Environment.TEST,
            api_keys=[SecretStr(API_KEY)],
        )
        self.client = TestClient(
            create_app(
                settings,
                clock=lambda: NOW,
                database=self.database,
            )
        )

    def tearDown(self) -> None:
        self.client.close()
        asyncio.run(self.database.dispose())
        self.temporary_directory.cleanup()

    def create_task(
        self,
        text: str = "hello",
        *,
        idempotency_key: str | None = None,
    ) -> CreateTaskResponse:
        headers = dict(AUTH_HEADERS)
        if idempotency_key is not None:
            headers["Idempotency-Key"] = idempotency_key
        response = self.client.post(
            "/api/v1/tasks",
            headers=headers,
            json=task_payload(text),
        )
        self.assertEqual(response.status_code, 201)
        return CreateTaskResponse.model_validate_json(response.content)

    def test_create_get_cancel_and_retry(self) -> None:
        created = self.create_task()
        self.assertEqual(created.data.status, TaskStatus.PENDING)

        response = self.client.get(
            f"/api/v1/tasks/{created.data.task_id}",
            headers=AUTH_HEADERS,
        )
        detail = TaskDetailResponse.model_validate_json(response.content)
        self.assertEqual(detail.data.source.type, "text")
        self.assertIsNotNone(detail.data.source_metadata)
        self.assertIsNone(detail.data.pipeline_id)

        response = self.client.post(
            f"/api/v1/tasks/{created.data.task_id}/cancel",
            headers=AUTH_HEADERS,
        )
        cancelled = TaskDetailResponse.model_validate_json(response.content)
        self.assertEqual(cancelled.data.status, TaskStatus.CANCELLED)
        self.assertEqual(cancelled.data.completed_at, NOW)

        response = self.client.post(
            f"/api/v1/tasks/{created.data.task_id}/cancel",
            headers=AUTH_HEADERS,
        )
        self.assertEqual(response.status_code, 409)
        self.assertEqual(
            response.json()["error"]["code"],
            ErrorCode.TASK_NOT_CANCELLABLE,
        )

        response = self.client.post(
            f"/api/v1/tasks/{created.data.task_id}/retry",
            headers=AUTH_HEADERS,
        )
        retried = TaskDetailResponse.model_validate_json(response.content)
        self.assertEqual(retried.data.status, TaskStatus.PENDING)
        self.assertIsNone(retried.data.completed_at)

    def test_idempotency_replays_and_detects_conflict(self) -> None:
        first = self.create_task(idempotency_key="external-submission-1")
        replay = self.create_task(idempotency_key="external-submission-1")
        self.assertEqual(first.data.task_id, replay.data.task_id)

        response = self.client.post(
            "/api/v1/tasks",
            headers={
                **AUTH_HEADERS,
                "Idempotency-Key": "external-submission-1",
            },
            json=task_payload("different"),
        )
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["error"]["code"], ErrorCode.CONFLICT)

    def test_html_text_source_is_classified_as_web_content(self) -> None:
        response = self.client.post(
            "/api/v1/tasks",
            headers=AUTH_HEADERS,
            json={
                "source": {
                    "type": "text",
                    "text": "<html><body>Hello</body></html>",
                    "mime_type": "text/html",
                    "filename": "page.html",
                }
            },
        )
        task = CreateTaskResponse.model_validate_json(response.content)
        response = self.client.get(
            f"/api/v1/tasks/{task.data.task_id}",
            headers=AUTH_HEADERS,
        )
        detail = TaskDetailResponse.model_validate_json(response.content)

        self.assertIsNotNone(detail.data.source_metadata)
        if detail.data.source_metadata is not None:
            self.assertEqual(detail.data.source_metadata.media_category, "web")

    def test_url_source_gets_routable_web_metadata(self) -> None:
        response = self.client.post(
            "/api/v1/tasks",
            headers=AUTH_HEADERS,
            json={
                "source": {
                    "type": "url",
                    "url": "https://example.com/docs/index.html",
                }
            },
        )
        self.assertEqual(response.status_code, 201, response.text)
        task = CreateTaskResponse.model_validate_json(response.content)
        response = self.client.get(
            f"/api/v1/tasks/{task.data.task_id}",
            headers=AUTH_HEADERS,
        )
        detail = TaskDetailResponse.model_validate_json(response.content)
        self.assertIsNotNone(detail.data.source_metadata)
        if detail.data.source_metadata is not None:
            self.assertEqual(detail.data.source_metadata.filename, "index.html")
            self.assertEqual(detail.data.source_metadata.mime_type, "text/html")
            self.assertEqual(detail.data.source_metadata.media_category, "web")

    def test_object_storage_source_gets_routable_metadata(self) -> None:
        response = self.client.post(
            "/api/v1/tasks",
            headers=AUTH_HEADERS,
            json={
                "source": {
                    "type": "object_storage",
                    "uri": "s3://documents/reports/report.docx",
                    "version_id": "version-42",
                }
            },
        )
        self.assertEqual(response.status_code, 201, response.text)
        task = CreateTaskResponse.model_validate_json(response.content)
        response = self.client.get(
            f"/api/v1/tasks/{task.data.task_id}",
            headers=AUTH_HEADERS,
        )
        detail = TaskDetailResponse.model_validate_json(response.content)
        self.assertIsNotNone(detail.data.source_metadata)
        if detail.data.source_metadata is not None:
            self.assertEqual(detail.data.source_metadata.filename, "report.docx")
            self.assertEqual(detail.data.source_metadata.media_category, "document")
            self.assertEqual(
                detail.data.source_metadata.attributes["version_id"],
                "version-42",
            )

        response = self.client.post(
            "/api/v1/tasks",
            headers=AUTH_HEADERS,
            json={
                "source": {
                    "type": "object_storage",
                    "uri": "s3://documents/unknown.binary",
                }
            },
        )
        self.assertEqual(response.status_code, 415)

    def test_list_uses_typed_filters_and_cursor(self) -> None:
        first = self.create_task("first")
        second = self.create_task("second")

        response = self.client.get(
            "/api/v1/tasks",
            headers=AUTH_HEADERS,
            params={
                "statuses": "pending",
                "media_category": "text",
                "limit": 1,
            },
        )
        self.assertEqual(response.status_code, 200)
        page_one = TaskListResponse.model_validate_json(response.content)
        self.assertEqual(len(page_one.items), 1)
        self.assertTrue(page_one.page.has_more)
        self.assertIsNotNone(page_one.page.next_cursor)

        response = self.client.get(
            "/api/v1/tasks",
            headers=AUTH_HEADERS,
            params={
                "statuses": "pending",
                "media_category": "text",
                "limit": 1,
                "cursor": page_one.page.next_cursor,
            },
        )
        page_two = TaskListResponse.model_validate_json(response.content)
        self.assertEqual(len(page_two.items), 1)
        self.assertEqual(
            {page_one.items[0].task_id, page_two.items[0].task_id},
            {first.data.task_id, second.data.task_id},
        )

        response = self.client.get(
            "/api/v1/tasks",
            headers=AUTH_HEADERS,
            params={
                "cursor": page_one.page.next_cursor,
                "sort_by": "priority",
            },
        )
        self.assertEqual(response.status_code, 422)

    def test_unknown_pipeline_and_task_are_typed_errors(self) -> None:
        payload = task_payload()
        payload["options"] = {
            "pipeline_id": "pipeline_abcdefgh",
            "pipeline_version": 1,
        }
        response = self.client.post(
            "/api/v1/tasks",
            headers=AUTH_HEADERS,
            json=payload,
        )
        self.assertEqual(response.status_code, 409)

        response = self.client.get(
            "/api/v1/tasks/task_doesnotexist",
            headers=AUTH_HEADERS,
        )
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["error"]["code"], ErrorCode.NOT_FOUND)

    def test_pending_task_has_empty_stages_and_result_is_not_ready(self) -> None:
        created = self.create_task()
        response = self.client.get(
            f"/api/v1/tasks/{created.data.task_id}/stages",
            headers=AUTH_HEADERS,
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["items"], [])

        response = self.client.get(
            f"/api/v1/tasks/{created.data.task_id}/result",
            headers=AUTH_HEADERS,
        )
        self.assertEqual(response.status_code, 409)
        self.assertTrue(response.json()["error"]["retryable"])

        response = self.client.get(
            f"/api/v1/tasks/{created.data.task_id}/result/content",
            headers=AUTH_HEADERS,
        )
        self.assertEqual(response.status_code, 409)

        response = self.client.get(
            f"/api/v1/tasks/{created.data.task_id}/stages/stage_unknown1",
            headers=AUTH_HEADERS,
        )
        self.assertEqual(response.status_code, 404)


if __name__ == "__main__":
    unittest.main()
