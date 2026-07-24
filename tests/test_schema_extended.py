from __future__ import annotations

import json
import unittest
from datetime import UTC, datetime, timedelta

from pydantic import HttpUrl, TypeAdapter, ValidationError

from parser_serve.schema.authentication import (
    ApiKeyStatus,
    ApiKeySummary,
    CreateApiKeyData,
    CreateApiKeyRequest,
    UpdateApiKeyRequest,
)
from parser_serve.schema.backend import (
    BackendCapability,
    BackendDetail,
    BackendExecutionMode,
    BackendStatus,
    UpdateBackendRequest,
)
from parser_serve.schema.callback import (
    CallbackConfig,
    CallbackDeliveryDetail,
    CallbackDeliveryStatus,
    CallbackEvent,
    CallbackPayload,
)
from parser_serve.schema.common import MediaCategory
from parser_serve.schema.dashboard import (
    CallbackDashboardSummary,
    DashboardData,
    StorageDashboardSummary,
    TaskDashboardSummary,
    WorkerDashboardSummary,
)
from parser_serve.schema.event import EventEnvelope, EventPayload
from parser_serve.schema.hardware import DeviceRuntime
from parser_serve.schema.management import (
    ComponentHealth,
    SettingKey,
    SystemHealthData,
    UpdateSetting,
    UpdateSettingsRequest,
)
from parser_serve.schema.mcp import McpSubmitRequest
from parser_serve.schema.pipeline import (
    BackendSelector,
    PipelineDefinition,
    PipelineStageDefinition,
    PipelineStatus,
)
from parser_serve.schema.task import CreateTaskRequest
from parser_serve.schema.worker import WorkerHealthCheck, WorkerResourceUsage


NOW = datetime(2026, 7, 24, 8, 0, tzinfo=UTC)


def pipeline_stage(
    name: str,
    *,
    depends_on: list[str] | None = None,
) -> PipelineStageDefinition:
    return PipelineStageDefinition(
        name=name,
        backend=BackendSelector(preferred=f"{name}_backend"),
        depends_on=depends_on or [],
        timeout_seconds=60,
    )


class PipelineSchemaTests(unittest.TestCase):
    def test_accepts_valid_pipeline_dag(self) -> None:
        pipeline = PipelineDefinition(
            pipeline_id="pipeline_abcdefgh",
            name="Document Pipeline",
            version=1,
            status=PipelineStatus.PUBLISHED,
            media_categories=[MediaCategory.DOCUMENT],
            stages=[
                pipeline_stage("convert"),
                pipeline_stage("parse", depends_on=["convert"]),
            ],
            created_at=NOW,
            published_at=NOW + timedelta(seconds=1),
        )

        self.assertEqual(pipeline.stages[1].depends_on, ["convert"])

    def test_rejects_pipeline_cycle(self) -> None:
        with self.assertRaisesRegex(ValidationError, "acyclic"):
            PipelineDefinition(
                pipeline_id="pipeline_abcdefgh",
                name="Cyclic Pipeline",
                version=1,
                status=PipelineStatus.DRAFT,
                media_categories=[MediaCategory.DOCUMENT],
                stages=[
                    pipeline_stage("first", depends_on=["second"]),
                    pipeline_stage("second", depends_on=["first"]),
                ],
                created_at=NOW,
            )

    def test_rejects_unknown_stage_dependency(self) -> None:
        with self.assertRaisesRegex(ValidationError, "unknown dependencies"):
            PipelineDefinition(
                pipeline_id="pipeline_abcdefgh",
                name="Invalid Pipeline",
                version=1,
                status=PipelineStatus.DRAFT,
                media_categories=[MediaCategory.DOCUMENT],
                stages=[pipeline_stage("parse", depends_on=["missing"])],
                created_at=NOW,
            )


class BackendSchemaTests(unittest.TestCase):
    def setUp(self) -> None:
        self.capability = BackendCapability(
            name="mineru_remote",
            version="1.0",
            media_categories=[MediaCategory.DOCUMENT],
            runtimes=[DeviceRuntime.CPU],
            maximum_concurrency=4,
        )

    def test_remote_backend_requires_url(self) -> None:
        with self.assertRaisesRegex(ValidationError, "remote_url"):
            BackendDetail(
                backend_id="backend_abcdefgh",
                capability=self.capability,
                status=BackendStatus.ENABLED,
                execution_mode=BackendExecutionMode.REMOTE,
                default_timeout_seconds=300,
                created_at=NOW,
                updated_at=NOW,
            )

    def test_accepts_remote_backend(self) -> None:
        backend = BackendDetail.model_validate_json(
            json.dumps(
                {
                    "backend_id": "backend_abcdefgh",
                    "capability": self.capability.model_dump(mode="json"),
                    "status": "enabled",
                    "execution_mode": "remote",
                    "default_timeout_seconds": 300,
                    "remote_url": "https://mineru.example.com/v1/parse",
                    "created_at": "2026-07-24T08:00:00Z",
                    "updated_at": "2026-07-24T08:00:00Z",
                }
            )
        )

        self.assertEqual(backend.execution_mode, BackendExecutionMode.REMOTE)

    def test_backend_update_requires_change(self) -> None:
        with self.assertRaises(ValidationError):
            UpdateBackendRequest()


class CallbackAndEventSchemaTests(unittest.TestCase):
    def test_task_request_accepts_typed_callback(self) -> None:
        request = CreateTaskRequest.model_validate_json(
            json.dumps(
                {
                    "source": {"type": "text", "text": "hello"},
                    "callback": {
                        "url": "https://client.example.com/callback",
                        "events": ["task.succeeded", "task.failed"],
                        "secret": "s" * 32,
                    },
                }
            )
        )

        self.assertIsNotNone(request.callback)
        if request.callback is not None:
            self.assertEqual(len(request.callback.events), 2)

    def test_callback_config_rejects_duplicate_events(self) -> None:
        with self.assertRaises(ValidationError):
            CallbackConfig.model_validate_json(
                json.dumps(
                    {
                        "url": "https://client.example.com/callback",
                        "events": ["task.failed", "task.failed"],
                    }
                )
            )

    def test_parses_callback_payload_union(self) -> None:
        payload = TypeAdapter(CallbackPayload).validate_json(
            json.dumps(
                {
                    "type": "task.progress",
                    "progress_percent": 50.0,
                    "updated_at": "2026-07-24T08:00:00Z",
                }
            )
        )

        self.assertEqual(payload.type, "task.progress")

    def test_retry_wait_delivery_requires_next_attempt(self) -> None:
        event = CallbackEvent.model_validate_json(
            json.dumps(
                {
                    "schema_version": "1.0",
                    "event_id": "event_abcdefgh",
                    "task_id": "task_abcdefgh",
                    "occurred_at": "2026-07-24T08:00:00Z",
                    "payload": {
                        "type": "task.failed",
                        "failed_at": "2026-07-24T08:00:00Z",
                        "error": {
                            "code": "INTERNAL_ERROR",
                            "message": "failed",
                        },
                    },
                }
            )
        )

        with self.assertRaises(ValidationError):
            CallbackDeliveryDetail(
                delivery_id="delivery_abcdefgh",
                event=event,
                target_url=HttpUrl("https://client.example.com/callback"),
                status=CallbackDeliveryStatus.RETRY_WAIT,
                attempt=1,
                total_attempts=1,
                maximum_attempts=3,
                created_at=NOW,
                updated_at=NOW,
            )

    def test_parses_event_payload_union(self) -> None:
        payload = TypeAdapter(EventPayload).validate_json(
            json.dumps(
                {
                    "type": "worker.status_changed",
                    "worker_id": "worker_abcdefgh",
                    "current_status": "online",
                }
            )
        )
        envelope = EventEnvelope(
            schema_version="1.0",
            event_id="event_abcdefgh",
            occurred_at=NOW,
            payload=payload,
        )

        self.assertEqual(envelope.payload.type, "worker.status_changed")


class AuthenticationSchemaTests(unittest.TestCase):
    def test_create_api_key_returns_full_key_once(self) -> None:
        summary = ApiKeySummary(
            api_key_id="key_abcdefgh",
            name="automation",
            prefix="parser_abcd",
            status=ApiKeyStatus.ACTIVE,
            created_at=NOW,
            updated_at=NOW,
        )
        result = CreateApiKeyData(
            api_key=f"parser_{'a' * 32}",
            summary=summary,
        )

        self.assertTrue(result.api_key.startswith("parser_"))

    def test_api_key_update_requires_change(self) -> None:
        with self.assertRaises(ValidationError):
            UpdateApiKeyRequest()

    def test_create_api_key_request_schema(self) -> None:
        request = CreateApiKeyRequest(
            name="external integration",
            expires_at=NOW + timedelta(days=30),
        )

        self.assertEqual(request.name, "external integration")


class DashboardAndManagementSchemaTests(unittest.TestCase):
    def test_dashboard_counts_are_consistent(self) -> None:
        data = DashboardData(
            generated_at=NOW,
            tasks=TaskDashboardSummary(
                total_tasks=10,
                pending_tasks=1,
                running_tasks=2,
                succeeded_tasks=6,
                failed_tasks=1,
                cancelled_tasks=0,
                success_rate=0.6,
                average_wait_ms=10.0,
                average_execution_ms=100.0,
                p50_execution_ms=80.0,
                p95_execution_ms=200.0,
                p99_execution_ms=300.0,
            ),
            workers=WorkerDashboardSummary(
                total_workers=2,
                online_workers=1,
                busy_workers=1,
                draining_workers=0,
                offline_workers=0,
                unhealthy_workers=0,
                total_concurrency=8,
                used_concurrency=3,
            ),
            callbacks=CallbackDashboardSummary(
                total_deliveries=5,
                successful_deliveries=4,
                failed_deliveries=1,
                pending_retries=0,
                success_rate=0.8,
            ),
            storage=StorageDashboardSummary(
                objects=4,
                original_bytes=100,
                artifact_bytes=200,
                result_bytes=50,
            ),
        )

        self.assertEqual(data.tasks.total_tasks, 10)

    def test_dashboard_rejects_inconsistent_task_counts(self) -> None:
        with self.assertRaises(ValidationError):
            TaskDashboardSummary(
                total_tasks=2,
                pending_tasks=0,
                running_tasks=0,
                succeeded_tasks=1,
                failed_tasks=0,
                cancelled_tasks=0,
                success_rate=0.5,
                average_wait_ms=0.0,
                average_execution_ms=0.0,
                p50_execution_ms=0.0,
                p95_execution_ms=0.0,
                p99_execution_ms=0.0,
            )

    def test_settings_reject_duplicate_keys(self) -> None:
        with self.assertRaises(ValidationError):
            UpdateSettingsRequest(
                settings=[
                    UpdateSetting(key=SettingKey.MAXIMUM_UPLOAD_BYTES, value=100),
                    UpdateSetting(key=SettingKey.MAXIMUM_UPLOAD_BYTES, value=200),
                ]
            )

    def test_system_health_matches_components(self) -> None:
        components = [
            ComponentHealth(
                name="postgres",
                healthy=False,
                checked_at=NOW,
            )
        ]

        with self.assertRaises(ValidationError):
            SystemHealthData(healthy=True, components=components)


class McpSchemaTests(unittest.TestCase):
    def test_mcp_submit_reuses_http_request_schema(self) -> None:
        self.assertIs(McpSubmitRequest, CreateTaskRequest)
        self.assertEqual(
            McpSubmitRequest.model_json_schema(),
            CreateTaskRequest.model_json_schema(),
        )


class WorkerHealthSchemaTests(unittest.TestCase):
    def test_requires_unique_named_health_checks_and_failure_message(self) -> None:
        with self.assertRaises(ValidationError):
            WorkerHealthCheck(name="ffmpeg", healthy=False)

        failed = WorkerHealthCheck(
            name="ffmpeg",
            healthy=False,
            message="ffmpeg executable is unavailable",
        )
        with self.assertRaises(ValidationError):
            WorkerResourceUsage(
                cpu_percent=0.0,
                memory_used_bytes=0,
                memory_total_bytes=1,
                running_tasks=0,
                leased_tasks=0,
                health_checks=[failed, failed],
            )


if __name__ == "__main__":
    unittest.main()
