from __future__ import annotations

import base64
import json
import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
from pydantic import SecretStr, ValidationError

from parser_serve.backends import BackendContext, BackendExecutionError
from parser_serve.backends.remote import RemoteHttpBackend
from parser_serve.schema.common import MediaCategory
from parser_serve.schema.hardware import DeviceRuntime, HardwareVendor
from parser_serve.schema.remote import RemoteBackendConfig
from parser_serve.schema.result import (
    ContentMetadata,
    ParseResult,
    TextBlock,
)
from parser_serve.schema.source import SourceMetadata, TextSource, UploadedFileSource
from parser_serve.schema.task import TaskOptions
from parser_serve.schema.worker import LeasedStage
from parser_serve.worker import WorkerSettings, configured_backend_registry


NOW = datetime(2026, 7, 24, 12, 0, tzinfo=UTC)


def lease(*, uploaded: bool = False) -> LeasedStage:
    metadata = SourceMetadata(
        filename="source.txt",
        mime_type="text/plain",
        media_category=MediaCategory.TEXT,
    )
    return LeasedStage(
        task_id="task_remote1234",
        stage_id="stage_remote1234",
        stage_name="parse",
        backend_id="backend_remote1234",
        backend_name="remote_parser",
        backend_version="1.0",
        backend_candidates=["backend_remote1234"],
        runtime=DeviceRuntime.CPU,
        source=(
            UploadedFileSource(type="uploaded_file", file_id="file_remote1234")
            if uploaded
            else TextSource(
                type="text",
                text="hello remote",
                filename="source.txt",
                mime_type="text/plain",
            )
        ),
        source_metadata=metadata,
        task_options=TaskOptions(),
        parameters={"feature": True},
        timeout_seconds=30,
        attempt=1,
        maximum_attempts=2,
        lease_token=f"lease_{'r' * 32}",
        lease_expires_at=NOW + timedelta(seconds=60),
    )


def success_payload(
    leased: LeasedStage,
    *,
    task_id: str | None = None,
    attachment: bytes | None = None,
) -> dict[str, object]:
    result = ParseResult(
        schema_version="1.0",
        task_id=task_id or leased.task_id,
        source=leased.source_metadata,
        metadata=ContentMetadata(language="en"),
        blocks=[
            TextBlock(
                type="text",
                block_id="block_remote1234",
                text="normalized result",
            )
        ],
        created_at=NOW,
    )
    artifacts: list[dict[str, object]] = []
    if attachment is not None:
        artifacts.append(
            {
                "type": "result_text",
                "filename": "result.txt",
                "mime_type": "text/plain",
                "content_base64": base64.b64encode(attachment).decode(),
                "metadata": {"provider": "test"},
            }
        )
    return {
        "status": "succeeded",
        "result": result.model_dump(mode="json"),
        "artifacts": artifacts,
    }


def backend_config(**updates: object) -> RemoteBackendConfig:
    payload: dict[str, object] = {
        "name": "remote_parser",
        "version": "1.0",
        "endpoint": "https://parser.internal/v1/parse",
        "authentication": {
            "type": "bearer",
            "token": f"remote_{'s' * 32}",
        },
        "media_categories": ["text"],
        "maximum_concurrency": 3,
    }
    payload.update(updates)
    return RemoteBackendConfig.model_validate(payload)


class RemoteHttpBackendTests(unittest.IsolatedAsyncioTestCase):
    async def test_streams_typed_request_and_normalizes_response(self) -> None:
        leased = lease()
        captured: dict[str, object] = {}

        async def handler(request: httpx.Request) -> httpx.Response:
            captured["authorization"] = request.headers["Authorization"]
            captured["body"] = await request.aread()
            return httpx.Response(
                200,
                headers={"Content-Type": "application/json; charset=utf-8"},
                json=success_payload(leased, attachment=b"plain text"),
            )

        progress: list[float] = []

        async def report(value: float) -> None:
            progress.append(value)

        backend = RemoteHttpBackend(
            config=backend_config(),
            runtime=DeviceRuntime.CPU,
            transport=httpx.MockTransport(handler),
        )
        output = await backend.execute(
            BackendContext(
                lease=leased,
                work_dir=Path(tempfile.gettempdir()),
                source_path=None,
                source_text="hello remote",
                report_progress=report,
            )
        )

        self.assertEqual(captured["authorization"], f"Bearer remote_{'s' * 32}")
        raw_body = captured["body"]
        self.assertIsInstance(raw_body, bytes)
        assert isinstance(raw_body, bytes)
        body = raw_body
        self.assertIn(b"task_remote1234", body)
        self.assertIn(b"hello remote", body)
        self.assertEqual(progress, [5.0, 90.0])
        self.assertEqual(output.primary_artifact_index, 0)
        self.assertEqual(len(output.artifacts), 2)
        parsed = ParseResult.model_validate_json(output.artifacts[0].data or b"")
        self.assertEqual(parsed.blocks[0].type, "text")
        self.assertEqual(output.artifacts[1].data, b"plain text")

    async def test_file_request_contains_file_and_digest(self) -> None:
        leased = lease(uploaded=True)
        source_data = b"source file bytes"
        captured_body = b""

        async def handler(request: httpx.Request) -> httpx.Response:
            nonlocal captured_body
            captured_body = await request.aread()
            return httpx.Response(
                200,
                headers={"Content-Type": "application/json"},
                json=success_payload(leased),
            )

        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "source.txt"
            path.write_bytes(source_data)

            async def report(_: float) -> None:
                return None

            backend = RemoteHttpBackend(
                config=backend_config(),
                runtime=DeviceRuntime.CPU,
                transport=httpx.MockTransport(handler),
            )
            await backend.execute(
                BackendContext(
                    lease=leased,
                    work_dir=Path(temporary),
                    source_path=path,
                    source_text=None,
                    report_progress=report,
                )
            )

        self.assertIn(source_data, captured_body)
        self.assertIn(
            __import__("hashlib").sha256(source_data).hexdigest().encode(),
            captured_body,
        )

    async def test_rejects_result_for_another_task(self) -> None:
        leased = lease()

        async def handler(_: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                headers={"Content-Type": "application/json"},
                json=success_payload(leased, task_id="task_another123"),
            )

        async def report(_: float) -> None:
            return None

        backend = RemoteHttpBackend(
            config=backend_config(),
            runtime=DeviceRuntime.CPU,
            transport=httpx.MockTransport(handler),
        )
        with self.assertRaisesRegex(
            BackendExecutionError,
            "different task",
        ):
            await backend.execute(
                BackendContext(
                    lease=leased,
                    work_dir=Path(tempfile.gettempdir()),
                    source_path=None,
                    source_text="hello remote",
                    report_progress=report,
                )
            )

    async def test_maps_service_failure_and_http_status_to_retryable_error(
        self,
    ) -> None:
        async def handler(_: httpx.Request) -> httpx.Response:
            return httpx.Response(
                503,
                headers={"Content-Type": "application/problem+json"},
                json={
                    "status": "failed",
                    "error": {
                        "code": "DEPENDENCY_UNAVAILABLE",
                        "message": "model is loading",
                        "retryable": False,
                        "context": {},
                    },
                },
            )

        async def report(_: float) -> None:
            return None

        backend = RemoteHttpBackend(
            config=backend_config(),
            runtime=DeviceRuntime.CPU,
            transport=httpx.MockTransport(handler),
        )
        with self.assertRaisesRegex(
            BackendExecutionError, "model is loading"
        ) as raised:
            await backend.execute(
                BackendContext(
                    lease=lease(),
                    work_dir=Path(tempfile.gettempdir()),
                    source_path=None,
                    source_text="hello remote",
                    report_progress=report,
                )
            )
        self.assertTrue(raised.exception.retryable)

    async def test_rejects_oversized_response_before_parsing(self) -> None:
        async def handler(_: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                headers={
                    "Content-Type": "application/json",
                    "Content-Length": "1000",
                },
                content=b"{}",
            )

        async def report(_: float) -> None:
            return None

        backend = RemoteHttpBackend(
            config=backend_config(maximum_response_bytes=100),
            runtime=DeviceRuntime.CPU,
            transport=httpx.MockTransport(handler),
        )
        with self.assertRaisesRegex(BackendExecutionError, "size limit"):
            await backend.execute(
                BackendContext(
                    lease=lease(),
                    work_dir=Path(tempfile.gettempdir()),
                    source_path=None,
                    source_text="hello remote",
                    report_progress=report,
                )
            )


class RemoteBackendConfigurationTests(unittest.TestCase):
    def test_authentication_token_is_required_and_hidden(self) -> None:
        with self.assertRaises(ValidationError):
            backend_config(authentication={"type": "bearer"})

        config = backend_config()
        self.assertNotIn(f"remote_{'s' * 32}", repr(config))

        with self.assertRaisesRegex(ValidationError, "credentials or a fragment"):
            backend_config(endpoint="https://user:password@parser.internal/v1/parse")

    def test_worker_registers_configured_remote_provider_for_its_runtime(
        self,
    ) -> None:
        settings = WorkerSettings(
            api_key=SecretStr(f"parser_{'w' * 32}"),
            worker_id="worker_remote123",
            device_runtime=DeviceRuntime.CUDA,
            device_vendor=HardwareVendor.NVIDIA,
            device_id="cuda-0",
            device_model="Test GPU",
            remote_backends=[
                backend_config(
                    name="paddleocr",
                    media_categories=["image"],
                )
            ],
        )

        registry = configured_backend_registry(settings)

        self.assertEqual(len(registry.capabilities), 1)
        capability = registry.capabilities[0]
        self.assertEqual(capability.name, "paddleocr")
        self.assertEqual(capability.runtimes, [DeviceRuntime.CUDA])

    def test_remote_backend_json_environment_is_fully_typed(self) -> None:
        payload = [
            {
                "name": "asr",
                "endpoint": "http://asr.internal/v1/parse",
                "media_categories": ["audio"],
            }
        ]
        settings = WorkerSettings(
            api_key=SecretStr(f"parser_{'w' * 32}"),
            worker_id="worker_remote456",
            remote_backends=json.loads(json.dumps(payload)),
        )

        self.assertEqual(settings.remote_backends[0].name, "asr")
        self.assertEqual(
            settings.remote_backends[0].media_categories,
            [MediaCategory.AUDIO],
        )
