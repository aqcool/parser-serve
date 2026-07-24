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
from parser_serve.schema.backend import (
    BackendDetailResponse,
    BackendListResponse,
    BackendStatus,
)
from parser_serve.schema.error import ErrorCode
from parser_serve.schema.defaults import (
    DefaultCatalogAction,
    DefaultCatalogInitializationResponse,
)
from parser_serve.schema.pipeline import (
    PipelineDetailResponse,
    PipelineListResponse,
    PipelineStatus,
    PipelineValidationResponse,
)
from parser_serve.schema.stage import StageListResponse
from parser_serve.schema.task import CreateTaskResponse, TaskDetailResponse
from parser_serve.settings import Environment, Settings


NOW = datetime(2026, 7, 24, 12, 0, tzinfo=UTC)
API_KEY = f"parser_{'r' * 32}"
AUTH_HEADERS = {"Authorization": f"Bearer {API_KEY}"}


def backend_payload(name: str = "text_backend") -> dict[str, object]:
    return {
        "capability": {
            "name": name,
            "version": "1.0",
            "media_categories": ["text"],
            "runtimes": ["cpu"],
            "maximum_concurrency": 4,
        },
        "execution_mode": "local",
        "default_timeout_seconds": 60,
    }


def pipeline_payload(
    backend_name: str = "text_backend",
) -> dict[str, object]:
    return {
        "pipeline_id": "pipeline_textparse",
        "name": "Text Pipeline",
        "media_categories": ["text"],
        "routing_priority": 100,
        "stages": [
            {
                "name": "extract",
                "backend": {"preferred": backend_name},
                "timeout_seconds": 60,
            },
            {
                "name": "normalize",
                "backend": {"preferred": backend_name},
                "depends_on": ["extract"],
                "timeout_seconds": 30,
            },
        ],
    }


class RegistryApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        database_path = Path(self.temporary_directory.name) / "registry.sqlite3"
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

    def create_backend(self, name: str = "text_backend") -> BackendDetailResponse:
        response = self.client.post(
            "/api/v1/management/backends",
            headers=AUTH_HEADERS,
            json=backend_payload(name),
        )
        self.assertEqual(response.status_code, 201)
        return BackendDetailResponse.model_validate_json(response.content)

    def create_pipeline(self) -> PipelineDetailResponse:
        response = self.client.post(
            "/api/v1/management/pipelines",
            headers=AUTH_HEADERS,
            json=pipeline_payload(),
        )
        self.assertEqual(response.status_code, 201)
        return PipelineDetailResponse.model_validate_json(response.content)

    def publish(self, version: int) -> PipelineDetailResponse:
        response = self.client.post(
            f"/api/v1/management/pipelines/pipeline_textparse/versions/{version}/publish",
            headers=AUTH_HEADERS,
        )
        self.assertEqual(response.status_code, 200)
        return PipelineDetailResponse.model_validate_json(response.content)

    def test_default_catalog_initialization_is_idempotent(self) -> None:
        first_response = self.client.post(
            "/api/v1/management/defaults/initialize",
            headers=AUTH_HEADERS,
            json={},
        )

        self.assertEqual(first_response.status_code, 200)
        first = DefaultCatalogInitializationResponse.model_validate_json(
            first_response.content
        )
        self.assertEqual(len(first.data.backend_ids_created), 6)
        self.assertEqual(len(first.data.backend_ids_existing), 0)
        self.assertEqual(
            [pipeline.pipeline_id for pipeline in first.data.pipelines],
            [
                "pipeline_document_auto",
                "pipeline_web_static",
                "pipeline_web_rendered",
                "pipeline_image_ocr",
                "pipeline_image_multimodal",
                "pipeline_audio_transcription",
                "pipeline_video_multimodal",
            ],
        )
        document, web_static, *model_pipelines = first.data.pipelines
        self.assertEqual(document.status, PipelineStatus.PUBLISHED)
        self.assertEqual(document.action, DefaultCatalogAction.PUBLISHED)
        self.assertEqual(web_static.status, PipelineStatus.PUBLISHED)
        self.assertEqual(web_static.action, DefaultCatalogAction.PUBLISHED)
        self.assertTrue(
            all(
                pipeline.action is DefaultCatalogAction.DRAFT_UNAVAILABLE
                and pipeline.violations
                for pipeline in model_pipelines
            )
        )

        second_response = self.client.post(
            "/api/v1/management/defaults/initialize",
            headers=AUTH_HEADERS,
            json={},
        )
        second = DefaultCatalogInitializationResponse.model_validate_json(
            second_response.content
        )

        self.assertEqual(second_response.status_code, 200)
        self.assertEqual(second.data.backend_ids_created, [])
        self.assertEqual(len(second.data.backend_ids_existing), 6)
        self.assertTrue(
            all(pipeline.version == 1 for pipeline in second.data.pipelines)
        )
        self.assertEqual(
            [
                second.data.pipelines[0].action,
                second.data.pipelines[1].action,
            ],
            [
                DefaultCatalogAction.UNCHANGED,
                DefaultCatalogAction.UNCHANGED,
            ],
        )

    def test_default_draft_publishes_after_model_backend_is_registered(
        self,
    ) -> None:
        initialized = self.client.post(
            "/api/v1/management/defaults/initialize",
            headers=AUTH_HEADERS,
            json={},
        )
        self.assertEqual(initialized.status_code, 200)
        create_backend = self.client.post(
            "/api/v1/management/backends",
            headers=AUTH_HEADERS,
            json={
                "capability": {
                    "name": "paddleocr",
                    "version": "1.0",
                    "media_categories": ["image"],
                    "mime_types": ["image/*"],
                    "runtimes": ["cuda"],
                    "maximum_concurrency": 2,
                },
                "execution_mode": "local",
                "default_timeout_seconds": 300,
            },
        )
        self.assertEqual(create_backend.status_code, 201)

        retried = self.client.post(
            "/api/v1/management/defaults/initialize",
            headers=AUTH_HEADERS,
            json={},
        )
        catalog = DefaultCatalogInitializationResponse.model_validate_json(
            retried.content
        )

        image_ocr = next(
            item
            for item in catalog.data.pipelines
            if item.pipeline_id == "pipeline_image_ocr"
        )
        self.assertEqual(image_ocr.status, PipelineStatus.PUBLISHED)
        self.assertEqual(image_ocr.action, DefaultCatalogAction.PUBLISHED)

    def test_default_static_web_pipeline_routes_url_source(self) -> None:
        initialized = self.client.post(
            "/api/v1/management/defaults/initialize",
            headers=AUTH_HEADERS,
            json={},
        )
        self.assertEqual(initialized.status_code, 200)

        response = self.client.post(
            "/api/v1/tasks",
            headers=AUTH_HEADERS,
            json={
                "source": {
                    "type": "url",
                    "url": "https://example.com/article",
                }
            },
        )
        task = CreateTaskResponse.model_validate_json(response.content)
        detail_response = self.client.get(
            f"/api/v1/tasks/{task.data.task_id}",
            headers=AUTH_HEADERS,
        )
        detail = TaskDetailResponse.model_validate_json(detail_response.content)
        backend_response = self.client.get(
            "/api/v1/management/backends?name_contains=builtin_web",
            headers=AUTH_HEADERS,
        )
        backends = BackendListResponse.model_validate_json(backend_response.content)

        self.assertEqual(response.status_code, 201)
        self.assertEqual(detail_response.status_code, 200)
        self.assertEqual(detail.data.pipeline_id, "pipeline_web_static")
        self.assertEqual(len(detail.data.stages), 1)
        self.assertEqual(len(backends.items), 1)
        self.assertEqual(backends.items[0].capability.name, "builtin_web")
        self.assertEqual(
            detail.data.stages[0].backend_id,
            backends.items[0].backend_id,
        )

    def test_default_rendered_web_pipeline_publishes_with_engine_backend(
        self,
    ) -> None:
        initialized = self.client.post(
            "/api/v1/management/defaults/initialize",
            headers=AUTH_HEADERS,
            json={},
        )
        self.assertEqual(initialized.status_code, 200)
        response = self.client.post(
            "/api/v1/management/backends",
            headers=AUTH_HEADERS,
            json={
                "capability": {
                    "name": "web_rendered",
                    "version": "1.0",
                    "media_categories": ["web"],
                    "mime_types": ["text/html", "application/xhtml+xml"],
                    "runtimes": ["cpu"],
                    "maximum_concurrency": 2,
                },
                "execution_mode": "local",
                "default_timeout_seconds": 300,
            },
        )
        self.assertEqual(response.status_code, 201)

        retried = self.client.post(
            "/api/v1/management/defaults/initialize",
            headers=AUTH_HEADERS,
            json={},
        )
        catalog = DefaultCatalogInitializationResponse.model_validate_json(
            retried.content
        )
        rendered = next(
            item
            for item in catalog.data.pipelines
            if item.pipeline_id == "pipeline_web_rendered"
        )

        self.assertEqual(retried.status_code, 200)
        self.assertEqual(rendered.status, PipelineStatus.PUBLISHED)
        self.assertEqual(rendered.action, DefaultCatalogAction.PUBLISHED)

    def test_validation_publish_and_route_task(self) -> None:
        pipeline = self.create_pipeline()

        response = self.client.post(
            "/api/v1/management/pipelines/pipeline_textparse/versions/1/validate",
            headers=AUTH_HEADERS,
        )
        validation = PipelineValidationResponse.model_validate_json(response.content)
        self.assertFalse(validation.data.valid)

        response = self.client.post(
            "/api/v1/management/pipelines/pipeline_textparse/versions/1/publish",
            headers=AUTH_HEADERS,
        )
        self.assertEqual(response.status_code, 409)
        self.assertTrue(response.json()["error"]["context"]["violations"])

        backend = self.create_backend()
        published = self.publish(pipeline.data.version)
        self.assertEqual(published.data.status, PipelineStatus.PUBLISHED)

        response = self.client.post(
            "/api/v1/tasks",
            headers=AUTH_HEADERS,
            json={"source": {"type": "text", "text": "hello"}},
        )
        task = CreateTaskResponse.model_validate_json(response.content)

        response = self.client.post(
            f"/api/v1/management/tasks/{task.data.task_id}/route",
            headers=AUTH_HEADERS,
        )
        routed = TaskDetailResponse.model_validate_json(response.content)
        self.assertEqual(routed.data.pipeline_id, "pipeline_textparse")
        self.assertEqual(len(routed.data.stages), 2)
        self.assertEqual(
            routed.data.stages[0].backend_id,
            backend.data.backend_id,
        )
        self.assertEqual(routed.data.stages[1].depends_on, ["extract"])

        response = self.client.get(
            f"/api/v1/tasks/{task.data.task_id}/stages",
            headers=AUTH_HEADERS,
            params={"limit": 1, "sort_by": "position"},
        )
        first_page = StageListResponse.model_validate_json(response.content)
        self.assertEqual([stage.name for stage in first_page.items], ["extract"])
        self.assertTrue(first_page.page.has_more)
        self.assertIsNotNone(first_page.page.next_cursor)

        response = self.client.get(
            f"/api/v1/tasks/{task.data.task_id}/stages",
            headers=AUTH_HEADERS,
            params={
                "limit": 1,
                "sort_by": "position",
                "cursor": first_page.page.next_cursor,
            },
        )
        second_page = StageListResponse.model_validate_json(response.content)
        self.assertEqual([stage.name for stage in second_page.items], ["normalize"])
        self.assertFalse(second_page.page.has_more)

        response = self.client.get(
            f"/api/v1/tasks/{task.data.task_id}/stages",
            headers=AUTH_HEADERS,
            params={
                "sort_by": "created_at",
                "cursor": first_page.page.next_cursor,
            },
        )
        self.assertEqual(response.status_code, 422)

        response = self.client.get(
            f"/api/v1/tasks/{task.data.task_id}/stages",
            headers=AUTH_HEADERS,
            params={"statuses": "pending", "backend_id": backend.data.backend_id},
        )
        filtered = StageListResponse.model_validate_json(response.content)
        self.assertEqual(len(filtered.items), 2)

        response = self.client.get(
            "/api/v1/capabilities",
            headers=AUTH_HEADERS,
        )
        self.assertEqual(
            response.json()["data"]["pipelines"],
            ["pipeline_textparse@1"],
        )
        self.assertEqual(
            response.json()["data"]["backends"],
            ["text_backend@1.0"],
        )

    def test_pipeline_test_executes_valid_draft_without_publishing_it(
        self,
    ) -> None:
        self.create_backend()
        draft = self.create_pipeline()

        response = self.client.post(
            ("/api/v1/management/pipelines/pipeline_textparse/versions/1/test"),
            headers=AUTH_HEADERS,
            json={
                "source": {
                    "type": "text",
                    "text": "draft pipeline test",
                    "mime_type": "text/plain",
                },
                "options": {
                    "priority": 10,
                    "features": {"extract_tables": False},
                },
                "client_reference": "management-draft-test",
            },
        )
        task = TaskDetailResponse.model_validate_json(response.content)
        pipeline_response = self.client.get(
            "/api/v1/management/pipelines/pipeline_textparse/versions/1",
            headers=AUTH_HEADERS,
        )
        unchanged = PipelineDetailResponse.model_validate_json(
            pipeline_response.content
        )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(task.data.status, "pending")
        self.assertEqual(task.data.pipeline_id, draft.data.pipeline_id)
        self.assertEqual(task.data.pipeline_version, 1)
        self.assertEqual(task.data.options.priority, 10)
        self.assertFalse(task.data.options.features.extract_tables)
        self.assertEqual(task.data.client_reference, "management-draft-test")
        self.assertEqual(len(task.data.stages), 2)
        self.assertEqual(unchanged.data.status, PipelineStatus.DRAFT)

    def test_pipeline_test_rejects_incompatible_source_without_creating_task(
        self,
    ) -> None:
        self.create_backend()
        self.create_pipeline()

        response = self.client.post(
            ("/api/v1/management/pipelines/pipeline_textparse/versions/1/test"),
            headers=AUTH_HEADERS,
            json={
                "source": {
                    "type": "url",
                    "url": "https://example.com/page",
                }
            },
        )
        tasks_response = self.client.get(
            "/api/v1/tasks",
            headers=AUTH_HEADERS,
        )

        self.assertEqual(response.status_code, 409)
        self.assertEqual(
            response.json()["error"]["code"],
            ErrorCode.BACKEND_NOT_AVAILABLE,
        )
        self.assertEqual(tasks_response.json()["items"], [])

    def test_pipeline_test_requires_valid_backend_catalog(self) -> None:
        self.create_pipeline()

        response = self.client.post(
            ("/api/v1/management/pipelines/pipeline_textparse/versions/1/test"),
            headers=AUTH_HEADERS,
            json={"source": {"type": "text", "text": "unavailable"}},
        )

        self.assertEqual(response.status_code, 409)
        self.assertTrue(response.json()["error"]["context"]["violations"])

    def test_task_creation_routes_immediately_when_catalog_is_available(
        self,
    ) -> None:
        self.create_backend()
        pipeline = self.create_pipeline()
        self.publish(pipeline.data.version)

        created = self.client.post(
            "/api/v1/tasks",
            headers=AUTH_HEADERS,
            json={"source": {"type": "text", "text": "route now"}},
        )
        self.assertEqual(created.status_code, 201)
        detail = self.client.get(
            f"/api/v1/tasks/{created.json()['data']['task_id']}",
            headers=AUTH_HEADERS,
        )
        task = TaskDetailResponse.model_validate_json(detail.content)

        self.assertEqual(task.data.pipeline_id, "pipeline_textparse")
        self.assertEqual(len(task.data.stages), 2)

    def test_failed_immediate_route_does_not_commit_partial_stage_plan(
        self,
    ) -> None:
        first = self.create_backend("first_backend")
        second = self.create_backend("second_backend")
        response = self.client.post(
            "/api/v1/management/pipelines",
            headers=AUTH_HEADERS,
            json={
                "pipeline_id": "pipeline_atomicroute",
                "name": "Atomic route",
                "media_categories": ["text"],
                "stages": [
                    {
                        "name": "first",
                        "backend": {"preferred": "first_backend"},
                        "timeout_seconds": 60,
                    },
                    {
                        "name": "second",
                        "backend": {"preferred": "second_backend"},
                        "depends_on": ["first"],
                        "timeout_seconds": 60,
                    },
                ],
            },
        )
        self.assertEqual(response.status_code, 201)
        published = self.client.post(
            "/api/v1/management/pipelines/pipeline_atomicroute/versions/1/publish",
            headers=AUTH_HEADERS,
        )
        self.assertEqual(published.status_code, 200)
        disabled = self.client.patch(
            f"/api/v1/management/backends/{second.data.backend_id}",
            headers=AUTH_HEADERS,
            json={"enabled": False},
        )
        self.assertEqual(disabled.status_code, 200)

        created = self.client.post(
            "/api/v1/tasks",
            headers=AUTH_HEADERS,
            json={
                "source": {"type": "text", "text": "no partial route"},
                "options": {
                    "pipeline_id": "pipeline_atomicroute",
                    "pipeline_version": 1,
                },
            },
        )
        self.assertEqual(created.status_code, 201)
        detail = self.client.get(
            f"/api/v1/tasks/{created.json()['data']['task_id']}",
            headers=AUTH_HEADERS,
        )
        task = TaskDetailResponse.model_validate_json(detail.content)

        self.assertEqual(task.data.status, "pending")
        self.assertEqual(task.data.stages, [])
        self.assertEqual(task.data.pipeline_id, "pipeline_atomicroute")
        self.assertNotEqual(first.data.backend_id, second.data.backend_id)

    def test_backend_crud_filter_and_uniqueness(self) -> None:
        created = self.create_backend()
        response = self.client.post(
            "/api/v1/management/backends",
            headers=AUTH_HEADERS,
            json=backend_payload(),
        )
        self.assertEqual(response.status_code, 409)

        response = self.client.patch(
            f"/api/v1/management/backends/{created.data.backend_id}",
            headers=AUTH_HEADERS,
            json={"enabled": False, "scheduling_weight": 50},
        )
        updated = BackendDetailResponse.model_validate_json(response.content)
        self.assertEqual(updated.data.status, BackendStatus.DISABLED)
        self.assertEqual(updated.data.scheduling_weight, 50)

        response = self.client.get(
            "/api/v1/management/backends",
            headers=AUTH_HEADERS,
            params={"statuses": "disabled", "runtimes": "cpu"},
        )
        listed = BackendListResponse.model_validate_json(response.content)
        self.assertEqual(len(listed.items), 1)

        response = self.client.get(
            f"/api/v1/management/backends/{created.data.backend_id}",
            headers=AUTH_HEADERS,
        )
        detail = BackendDetailResponse.model_validate_json(response.content)
        self.assertEqual(detail.data.capability.name, "text_backend")

    def test_pipeline_versions_list_and_rollback(self) -> None:
        self.create_backend()
        first = self.create_pipeline()
        second = self.create_pipeline()
        self.assertEqual((first.data.version, second.data.version), (1, 2))

        self.publish(2)
        rolled_back = self.publish(1)
        self.assertEqual(rolled_back.data.status, PipelineStatus.PUBLISHED)

        response = self.client.get(
            "/api/v1/management/pipelines",
            headers=AUTH_HEADERS,
            params={
                "media_category": "text",
                "limit": 1,
                "sort_by": "version",
                "sort_direction": "asc",
            },
        )
        page_one = PipelineListResponse.model_validate_json(response.content)
        self.assertEqual(len(page_one.items), 1)
        self.assertTrue(page_one.page.has_more)

        response = self.client.get(
            "/api/v1/management/pipelines",
            headers=AUTH_HEADERS,
            params={
                "media_category": "text",
                "limit": 1,
                "sort_by": "version",
                "sort_direction": "asc",
                "cursor": page_one.page.next_cursor,
            },
        )
        page_two = PipelineListResponse.model_validate_json(response.content)
        self.assertEqual(len(page_two.items), 1)
        self.assertEqual(
            [page_one.items[0].version, page_two.items[0].version],
            [1, 2],
        )

        response = self.client.get(
            "/api/v1/management/pipelines",
            headers=AUTH_HEADERS,
            params={
                "sort_by": "created_at",
                "cursor": page_one.page.next_cursor,
            },
        )
        self.assertEqual(response.status_code, 422)

        response = self.client.get(
            "/api/v1/management/pipelines/pipeline_textparse/versions/2",
            headers=AUTH_HEADERS,
        )
        version_two = PipelineDetailResponse.model_validate_json(response.content)
        self.assertEqual(version_two.data.status, PipelineStatus.DISABLED)

    def test_route_reports_missing_task(self) -> None:
        response = self.client.post(
            "/api/v1/management/tasks/task_doesnotexist/route",
            headers=AUTH_HEADERS,
        )
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["error"]["code"], ErrorCode.NOT_FOUND)


if __name__ == "__main__":
    unittest.main()
