from __future__ import annotations

import json
import re
import unittest
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

from pydantic import TypeAdapter, ValidationError

from parser_serve.schema.artifact import Artifact, ArtifactType
from parser_serve.schema.base import JsonValue, StrictSchema
from parser_serve.schema.common import ApiResponse, MediaCategory
from parser_serve.schema.error import ErrorCode, ErrorDetail
from parser_serve.schema.hardware import (
    DeviceInfo,
    DeviceRequirement,
    DeviceRuntime,
    HardwareVendor,
    SchedulingStrategy,
)
from parser_serve.schema.result import ContentBlock, ParseResult
from parser_serve.schema.source import ParseSource, SourceMetadata, TextSource
from parser_serve.schema.stage import StageDetail, StageStatus
from parser_serve.schema.task import (
    CreateTaskData,
    CreateTaskRequest,
    TaskDetail,
    TaskOptions,
    TaskStatus,
)
from parser_serve.schema.worker import (
    BackendCapability,
    WorkerHeartbeatRequest,
    WorkerRegistrationRequest,
    WorkerResourceUsage,
    WorkerStatus,
)


NOW = datetime(2026, 7, 23, 12, 0, tzinfo=UTC)


class StrictSchemaTests(unittest.TestCase):
    def test_forbids_unknown_fields(self) -> None:
        payload = {
            "source": {
                "type": "text",
                "text": "hello",
                "unknown": True,
            }
        }

        with self.assertRaises(ValidationError):
            CreateTaskRequest.model_validate(payload)

    def test_rejects_implicit_type_coercion(self) -> None:
        payload = {
            "source": {"type": "text", "text": "hello"},
            "options": {"priority": "10"},
        }

        with self.assertRaises(ValidationError):
            CreateTaskRequest.model_validate(payload)

    def test_json_enum_values_are_accepted_without_coercing_booleans(self) -> None:
        request = CreateTaskRequest.model_validate(
            {
                "source": {"type": "text", "text": "hello"},
                "options": {
                    "device": {
                        "strategy": "require",
                        "runtimes": ["cpu"],
                    }
                },
            }
        )
        self.assertEqual(request.options.device.runtimes[0], "cpu")

        with self.assertRaises(ValidationError):
            CreateTaskRequest.model_validate(
                {
                    "source": {"type": "text", "text": "hello"},
                    "options": {
                        "features": {
                            "run_ocr": "true",
                        }
                    },
                }
            )

    def test_assignment_is_validated(self) -> None:
        options = TaskOptions()

        with self.assertRaises(ValidationError):
            options.priority = 101

    def test_json_value_rejects_non_json_values(self) -> None:
        class MetadataSchema(StrictSchema):
            metadata: dict[str, JsonValue]

        with self.assertRaises(ValidationError):
            MetadataSchema.model_validate({"metadata": {"value": {1, 2}}})

    def test_all_contracts_generate_json_schema(self) -> None:
        pending = list(StrictSchema.__subclasses__())
        discovered: set[type[StrictSchema]] = set()

        while pending:
            model = pending.pop()
            if model in discovered:
                continue
            discovered.add(model)
            pending.extend(model.__subclasses__())

        self.assertGreater(len(discovered), 20)
        for model in discovered:
            with self.subTest(model=model.__name__):
                schema = model.model_json_schema()
                self.assertEqual(schema["type"], "object")

    def test_contracts_do_not_import_unconstrained_any(self) -> None:
        schema_root = Path(__file__).parents[1] / "parser_serve" / "schema"

        for path in schema_root.glob("*.py"):
            with self.subTest(path=path.name):
                source = path.read_text(encoding="utf-8")
                self.assertIsNone(re.search(r"\bAny\b", source))

    def test_timestamps_are_normalized_to_utc(self) -> None:
        timestamp = datetime(
            2026,
            7,
            23,
            20,
            0,
            tzinfo=timezone(timedelta(hours=8)),
        )
        data = CreateTaskData(
            task_id="task_abcdefgh",
            status=TaskStatus.PENDING,
            created_at=timestamp,
        )

        self.assertEqual(data.created_at, NOW)
        self.assertEqual(data.created_at.tzinfo, UTC)


class SourceSchemaTests(unittest.TestCase):
    def test_parses_discriminated_text_source(self) -> None:
        source = TypeAdapter(ParseSource).validate_json(
            json.dumps(
                {
                    "type": "text",
                    "text": "Parser Serve",
                    "mime_type": "text/plain",
                }
            )
        )

        self.assertEqual(source.type, "text")
        self.assertEqual(source.text, "Parser Serve")

    def test_parses_discriminated_url_source(self) -> None:
        source = TypeAdapter(ParseSource).validate_json(
            '{"type":"url","url":"https://example.com/document.pdf"}'
        )

        self.assertEqual(source.type, "url")
        self.assertEqual(str(source.url), "https://example.com/document.pdf")

    def test_rejects_unknown_source_type(self) -> None:
        with self.assertRaises(ValidationError):
            TypeAdapter(ParseSource).validate_python(
                {"type": "database", "record_id": "123"}
            )


class TaskAndStageSchemaTests(unittest.TestCase):
    def test_create_task_response_is_typed(self) -> None:
        response = ApiResponse[CreateTaskData](
            request_id="req_abcdefgh",
            data=CreateTaskData(
                task_id="task_abcdefgh",
                status=TaskStatus.PENDING,
                created_at=NOW,
            ),
        )

        self.assertEqual(response.data.status, TaskStatus.PENDING)
        schema = ApiResponse[CreateTaskData].model_json_schema()
        self.assertIn("$defs", schema)

    def test_pipeline_version_requires_pipeline_id(self) -> None:
        with self.assertRaises(ValidationError):
            TaskOptions(pipeline_version=1)

    def test_terminal_stage_requires_completion_time(self) -> None:
        with self.assertRaises(ValidationError):
            StageDetail(
                stage_id="stage_abcdefgh",
                name="convert",
                status=StageStatus.SUCCEEDED,
                created_at=NOW,
            )

    def test_failed_stage_requires_error(self) -> None:
        with self.assertRaises(ValidationError):
            StageDetail(
                stage_id="stage_abcdefgh",
                name="convert",
                status=StageStatus.FAILED,
                created_at=NOW,
                completed_at=NOW,
            )

    def test_failed_task_accepts_typed_error(self) -> None:
        task = TaskDetail(
            task_id="task_abcdefgh",
            status=TaskStatus.FAILED,
            source=TextSource(
                type="text",
                text="hello",
            ),
            source_metadata=SourceMetadata(
                mime_type="text/plain",
                media_category=MediaCategory.TEXT,
                size_bytes=5,
            ),
            options=TaskOptions(),
            pipeline_id="pipeline_abcdefgh",
            pipeline_version=1,
            created_at=NOW,
            completed_at=NOW + timedelta(seconds=1),
            error=ErrorDetail(
                code=ErrorCode.INTERNAL_ERROR,
                message="conversion failed",
            ),
        )

        self.assertIsNotNone(task.error)
        if task.error is not None:
            self.assertEqual(task.error.code, ErrorCode.INTERNAL_ERROR)


class ResultSchemaTests(unittest.TestCase):
    def test_parses_content_block_union(self) -> None:
        block = TypeAdapter(ContentBlock).validate_python(
            {
                "type": "transcript",
                "block_id": "block_abcdefgh",
                "text": "hello",
                "start_ms": 100,
                "end_ms": 200,
            }
        )

        self.assertEqual(block.type, "transcript")
        self.assertEqual(block.end_ms, 200)

    def test_rejects_invalid_transcript_range(self) -> None:
        with self.assertRaises(ValidationError):
            TypeAdapter(ContentBlock).validate_python(
                {
                    "type": "transcript",
                    "block_id": "block_abcdefgh",
                    "text": "hello",
                    "start_ms": 200,
                    "end_ms": 100,
                }
            )

    def test_parse_result_schema_is_serializable(self) -> None:
        result = ParseResult.model_validate_json(
            json.dumps(
                {
                    "schema_version": "1.0",
                    "task_id": "task_abcdefgh",
                    "source": {
                        "filename": "example.txt",
                        "mime_type": "text/plain",
                        "media_category": "text",
                        "size_bytes": 5,
                    },
                    "metadata": {"language": "en"},
                    "blocks": [
                        {
                            "type": "text",
                            "block_id": "block_abcdefgh",
                            "text": "hello",
                        }
                    ],
                    "created_at": "2026-07-23T12:00:00Z",
                }
            )
        )

        self.assertEqual(result.blocks[0].type, "text")
        self.assertEqual(result.model_dump(mode="json")["schema_version"], "1.0")
        self.assertIn("$defs", ParseResult.model_json_schema())

    def test_artifact_requires_timezone_aware_timestamp(self) -> None:
        with self.assertRaises(ValidationError):
            Artifact(
                artifact_id="artifact_abcdefgh",
                type=ArtifactType.RESULT_JSON,
                filename="result.json",
                mime_type="application/json",
                size_bytes=10,
                sha256="a" * 64,
                storage_uri="s3://bucket/result.json",
                created_at=datetime(2026, 7, 23, 12, 0),
            )

    def test_artifact_expiration_must_be_later_than_creation(self) -> None:
        with self.assertRaises(ValidationError):
            Artifact(
                artifact_id="artifact_abcdefgh",
                type=ArtifactType.RESULT_JSON,
                filename="result.json",
                mime_type="application/json",
                size_bytes=10,
                sha256="a" * 64,
                storage_uri="s3://bucket/result.json",
                created_at=NOW,
                expires_at=NOW,
            )


class HardwareAndWorkerSchemaTests(unittest.TestCase):
    def test_hardware_bring_up_worker_can_register_without_backends(self) -> None:
        registration = WorkerRegistrationRequest(
            worker_id="worker_bringup12",
            name="CUDA bring-up Worker",
            version="0.1.0",
            hostname="worker-01",
            devices=[
                DeviceInfo(
                    device_id="cuda-0",
                    vendor=HardwareVendor.NVIDIA,
                    runtime=DeviceRuntime.CUDA,
                    model="Configured NVIDIA GPU",
                )
            ],
            maximum_concurrency=1,
        )

        self.assertEqual(registration.backends, [])

    def test_rejects_mismatched_vendor_and_runtime(self) -> None:
        with self.assertRaises(ValidationError):
            DeviceInfo(
                device_id="gpu-0",
                vendor=HardwareVendor.HUAWEI,
                runtime=DeviceRuntime.CUDA,
                model="Example GPU",
            )

    def test_preferred_device_requires_runtime(self) -> None:
        with self.assertRaises(ValidationError):
            DeviceRequirement(strategy=SchedulingStrategy.PREFER)

    def test_rejects_duplicate_worker_devices(self) -> None:
        device = DeviceInfo(
            device_id="cpu-0",
            vendor=HardwareVendor.GENERIC,
            runtime=DeviceRuntime.CPU,
            model="CPU",
        )
        backend = BackendCapability(
            name="text",
            version="1.0",
            media_categories=[MediaCategory.TEXT],
            runtimes=[DeviceRuntime.CPU],
            maximum_concurrency=2,
        )

        with self.assertRaises(ValidationError):
            WorkerRegistrationRequest(
                worker_id="worker_abcdefgh",
                name="CPU Worker",
                version="0.1.0",
                hostname="worker-01",
                devices=[device, device],
                backends=[backend],
                maximum_concurrency=2,
            )

    def test_backend_accepts_mime_wildcard(self) -> None:
        backend = BackendCapability(
            name="ocr",
            version="1.0",
            mime_types=["image/*"],
            runtimes=[DeviceRuntime.CPU],
            maximum_concurrency=2,
        )

        self.assertEqual(backend.mime_types, ["image/*"])

    def test_rejects_worker_memory_overflow(self) -> None:
        with self.assertRaises(ValidationError):
            WorkerResourceUsage(
                cpu_percent=10.0,
                memory_used_bytes=20,
                memory_total_bytes=10,
                running_tasks=1,
                leased_tasks=0,
            )

    def test_heartbeat_is_fully_typed(self) -> None:
        heartbeat = WorkerHeartbeatRequest(
            worker_id="worker_abcdefgh",
            sequence=1,
            status=WorkerStatus.ONLINE,
            resources=WorkerResourceUsage(
                cpu_percent=10.0,
                memory_used_bytes=10,
                memory_total_bytes=100,
                running_tasks=1,
                leased_tasks=0,
            ),
            timestamp=NOW,
        )

        self.assertEqual(heartbeat.status, WorkerStatus.ONLINE)


if __name__ == "__main__":
    unittest.main()
