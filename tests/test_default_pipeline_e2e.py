from __future__ import annotations

import asyncio
import io
import tempfile
import unittest
from collections import Counter
from datetime import UTC, datetime
from email.parser import BytesParser
from email.policy import default
from pathlib import Path
import zipfile

import httpx
from pydantic import AnyHttpUrl, SecretStr

from parser_serve.api import create_app
from parser_serve.backends import (
    BackendRegistry,
    EngineRemoteBackend,
    OfficeOpenXmlBackend,
    StaticWebBackend,
)
from parser_serve.persistence import Database
from parser_serve.schema.defaults import DefaultCatalogInitializationResponse
from parser_serve.schema.engine import EngineBackendConfig, ParserEngine
from parser_serve.schema.hardware import DeviceInfo, DeviceRuntime, HardwareVendor
from parser_serve.schema.remote import RemoteParseRequest, RemoteParseSucceeded
from parser_serve.schema.result import (
    ContentBlock,
    ContentMetadata,
    ParseResult,
    ParseResultResponse,
    TextBlock,
    TranscriptBlock,
)
from parser_serve.schema.stage import StageListResponse
from parser_serve.schema.task import TaskDetailResponse, TaskStatus
from parser_serve.schema.worker import WorkerRegistrationRequest
from parser_serve.settings import Environment, Settings
from parser_serve.storage import LocalFileStorage
from parser_serve.worker import HttpWorkerControlClient, WorkerAgent


NOW = datetime(2026, 7, 24, 12, 0, tzinfo=UTC)
ORDINARY_KEY = f"parser_{'p' * 32}"
WORKER_KEY = f"parser_{'q' * 32}"
ORDINARY_HEADERS = {"Authorization": f"Bearer {ORDINARY_KEY}"}
WORKER_ID = "worker_pipelinee2e"

ENGINE_PIPELINES = {
    "pipeline_document_auto": ParserEngine.MINERU,
    "pipeline_web_rendered": ParserEngine.WEB_RENDERED,
    "pipeline_image_ocr": ParserEngine.PADDLEOCR,
    "pipeline_image_multimodal": ParserEngine.PADDLEOCR_VL,
    "pipeline_audio_transcription": ParserEngine.ASR,
    "pipeline_video_multimodal": ParserEngine.VIDEO_VLM,
}

SAMPLES = {
    "document": ("sample.pdf", "application/pdf", b"%PDF-1.7\nsample"),
    "web": (
        "sample.html",
        "text/html",
        b"<!doctype html><html><head><title>Sample</title></head>"
        b"<body>Static pipeline sample</body></html>",
    ),
    "image": ("sample.png", "image/png", b"\x89PNG\r\n\x1a\nsample"),
    "audio": (
        "sample.wav",
        "audio/wav",
        b"RIFF\x10\x00\x00\x00WAVEsample",
    ),
    "video": (
        "sample.mp4",
        "video/mp4",
        b"\x00\x00\x00\x18ftypisomsample",
    ),
}

PIPELINE_SOURCES = {
    "pipeline_document_auto": "document",
    "pipeline_web_static": "web",
    "pipeline_web_rendered": "web",
    "pipeline_image_ocr": "image",
    "pipeline_image_multimodal": "image",
    "pipeline_audio_transcription": "audio",
    "pipeline_video_multimodal": "video",
}


class RemoteEngineReceiver:
    """Real TCP implementation of the Remote Backend 1.0 success path."""

    def __init__(self) -> None:
        self.server: asyncio.Server | None = None
        self.endpoint: AnyHttpUrl | None = None
        self.calls: Counter[str] = Counter()

    async def __aenter__(self) -> RemoteEngineReceiver:
        self.server = await asyncio.start_server(self._handle, "127.0.0.1", 0)
        address = self.server.sockets[0].getsockname()
        self.endpoint = AnyHttpUrl(f"http://127.0.0.1:{address[1]}/v1/parse")
        return self

    async def __aexit__(self, *_: object) -> None:
        if self.server is not None:
            self.server.close()
            await self.server.wait_closed()

    async def _handle(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        try:
            raw_headers = await reader.readuntil(b"\r\n\r\n")
            header_lines = raw_headers.decode("latin-1").split("\r\n")
            headers = {
                name.casefold(): value.strip()
                for name, value in (
                    line.split(":", 1) for line in header_lines[1:] if ":" in line
                )
            }
            body = await reader.readexactly(int(headers["content-length"]))
            message = BytesParser(policy=default).parsebytes(
                (
                    f"Content-Type: {headers['content-type']}\r\n"
                    "MIME-Version: 1.0\r\n\r\n"
                ).encode("ascii")
                + body
            )
            request_part = next(
                part
                for part in message.iter_parts()
                if part.get_param("name", header="content-disposition") == "request"
            )
            request_payload = request_part.get_payload(decode=True)
            if not isinstance(request_payload, bytes):
                raise ValueError("Remote request multipart field is not bytes")
            request = RemoteParseRequest.model_validate_json(request_payload)
            self.calls[request.backend_name] += 1
            block_id = f"block_{request.stage_id[-12:]}"
            blocks: list[ContentBlock] = (
                [
                    TranscriptBlock(
                        type="transcript",
                        block_id=block_id,
                        text="Remote ASR sample transcript",
                        start_ms=0,
                        end_ms=1000,
                        language="zh-CN",
                    )
                ]
                if request.backend_name == ParserEngine.ASR.value
                else [
                    TextBlock(
                        type="text",
                        block_id=block_id,
                        text=f"{request.backend_name} parsed sample",
                    )
                ]
            )
            response = RemoteParseSucceeded(
                status="succeeded",
                result=ParseResult(
                    schema_version="1.0",
                    task_id=request.task_id,
                    source=request.source,
                    metadata=ContentMetadata(
                        attributes={"engine": request.backend_name}
                    ),
                    blocks=blocks,
                    created_at=NOW,
                ),
            ).model_dump_json()
            encoded = response.encode("utf-8")
            writer.write(
                (
                    "HTTP/1.1 200 OK\r\n"
                    "Content-Type: application/json\r\n"
                    f"Content-Length: {len(encoded)}\r\n"
                    "Connection: close\r\n\r\n"
                ).encode("ascii")
                + encoded
            )
            await writer.drain()
        finally:
            writer.close()
            await writer.wait_closed()


class DefaultPipelineEndToEndTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        root = Path(self.temporary_directory.name)
        self.database = Database(f"sqlite+aiosqlite:///{root / 'pipelines.sqlite3'}")
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
            base_url="http://control.test",
            headers={"Authorization": f"Bearer {WORKER_KEY}"},
        )
        self.worker_client = HttpWorkerControlClient(
            base_url="http://control.test",
            api_key=WORKER_KEY,
            client=self.http,
        )

    async def asyncTearDown(self) -> None:
        await self.http.aclose()
        await self.database.dispose()
        self.temporary_directory.cleanup()

    async def _upload_samples(self) -> dict[str, str]:
        file_ids: dict[str, str] = {}
        for category, (filename, mime_type, content) in SAMPLES.items():
            response = await self.http.post(
                "/api/v1/files",
                headers=ORDINARY_HEADERS,
                files={"file": (filename, content, mime_type)},
            )
            self.assertEqual(response.status_code, 201, response.text)
            file_ids[category] = response.json()["data"]["file_id"]
        return file_ids

    async def test_every_default_pipeline_executes_a_sample(self) -> None:
        async with RemoteEngineReceiver() as receiver:
            endpoint = receiver.endpoint
            if endpoint is None:
                self.fail("Remote engine receiver did not expose an endpoint")
            registry = BackendRegistry()
            registry.register(StaticWebBackend())
            for engine in ENGINE_PIPELINES.values():
                backend = EngineRemoteBackend(
                    config=EngineBackendConfig(
                        engine=engine,
                        endpoint=endpoint,
                        maximum_concurrency=4,
                    ),
                    runtime=DeviceRuntime.CPU,
                )
                registry.register(backend)
                response = await self.http.post(
                    "/api/v1/management/backends",
                    headers=ORDINARY_HEADERS,
                    json={
                        "capability": backend.capability.model_dump(mode="json"),
                        "execution_mode": "remote",
                        "default_timeout_seconds": 30,
                        "remote_url": str(endpoint),
                    },
                )
                self.assertEqual(response.status_code, 201, response.text)

            initialized = await self.http.post(
                "/api/v1/management/defaults/initialize",
                headers=ORDINARY_HEADERS,
                json={},
            )
            catalog = DefaultCatalogInitializationResponse.model_validate_json(
                initialized.content
            )
            self.assertEqual(initialized.status_code, 200, initialized.text)
            self.assertEqual(len(catalog.data.pipelines), len(PIPELINE_SOURCES))
            self.assertTrue(
                all(item.status == "published" for item in catalog.data.pipelines)
            )

            registration = WorkerRegistrationRequest(
                worker_id=WORKER_ID,
                name="Default Pipeline E2E Worker",
                version="0.1.0",
                hostname="pipeline-e2e",
                devices=[
                    DeviceInfo(
                        device_id="cpu-0",
                        vendor=HardwareVendor.GENERIC,
                        runtime=DeviceRuntime.CPU,
                        model="Test CPU",
                    )
                ],
                backends=list(registry.capabilities),
                maximum_concurrency=len(PIPELINE_SOURCES),
            )
            registered = await self.worker_client.register(registration)
            self.assertTrue(registered.data.accepted)

            file_ids = await self._upload_samples()
            task_ids: dict[str, str] = {}
            for pipeline_id, sample_category in PIPELINE_SOURCES.items():
                response = await self.http.post(
                    f"/api/v1/management/pipelines/{pipeline_id}/versions/1/test",
                    headers=ORDINARY_HEADERS,
                    json={
                        "source": {
                            "type": "uploaded_file",
                            "file_id": file_ids[sample_category],
                        },
                        "client_reference": f"e2e:{pipeline_id}",
                    },
                )
                self.assertEqual(response.status_code, 201, response.text)
                detail = TaskDetailResponse.model_validate_json(response.content)
                self.assertEqual(detail.data.pipeline_id, pipeline_id)
                task_ids[pipeline_id] = detail.data.task_id

            agent = WorkerAgent(
                worker_id=WORKER_ID,
                client=self.worker_client,
                backends=registry,
                maximum_concurrency=len(PIPELINE_SOURCES),
                lease_renew_interval_seconds=20,
            )
            executed = 0
            for _ in range(len(PIPELINE_SOURCES)):
                if executed == len(PIPELINE_SOURCES):
                    break
                count = await agent.run_once()
                self.assertGreater(count, 0)
                executed += count
            self.assertEqual(executed, len(PIPELINE_SOURCES))

            for pipeline_id, task_id in task_ids.items():
                detail_response = await self.http.get(
                    f"/api/v1/tasks/{task_id}",
                    headers=ORDINARY_HEADERS,
                )
                detail = TaskDetailResponse.model_validate_json(detail_response.content)
                self.assertEqual(detail.data.status, TaskStatus.SUCCEEDED)

                result_response = await self.http.get(
                    f"/api/v1/tasks/{task_id}/result",
                    headers=ORDINARY_HEADERS,
                )
                result = ParseResultResponse.model_validate_json(
                    result_response.content
                )
                if pipeline_id == "pipeline_web_static":
                    self.assertEqual(result.data.metadata.title, "Sample")
                    self.assertIn(
                        "Static pipeline sample",
                        result.data.model_dump_json(),
                    )
                else:
                    expected_engine = ENGINE_PIPELINES[pipeline_id].value
                    self.assertEqual(
                        result.data.metadata.attributes["engine"],
                        expected_engine,
                    )

        self.assertEqual(
            receiver.calls,
            Counter(engine.value for engine in ENGINE_PIPELINES.values()),
        )

    async def test_document_pipeline_falls_back_to_builtin_office(self) -> None:
        initialized = await self.http.post(
            "/api/v1/management/defaults/initialize",
            headers=ORDINARY_HEADERS,
            json={},
        )
        self.assertEqual(initialized.status_code, 200, initialized.text)
        registry = BackendRegistry()
        registry.register(OfficeOpenXmlBackend())
        registered = await self.worker_client.register(
            WorkerRegistrationRequest(
                worker_id=WORKER_ID,
                name="Office Fallback E2E Worker",
                version="0.1.0",
                hostname="office-fallback-e2e",
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
        )
        self.assertTrue(registered.data.accepted)

        output = io.BytesIO()
        with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr(
                "[Content_Types].xml",
                (
                    '<Types xmlns="http://schemas.openxmlformats.org/'
                    'package/2006/content-types"/>'
                ),
            )
            archive.writestr(
                "word/document.xml",
                (
                    '<w:document xmlns:w="http://schemas.openxmlformats.org/'
                    'wordprocessingml/2006/main"><w:body><w:p><w:r>'
                    "<w:t>Built-in Office fallback</w:t></w:r></w:p>"
                    "</w:body></w:document>"
                ),
            )
        upload = await self.http.post(
            "/api/v1/files",
            headers=ORDINARY_HEADERS,
            files={
                "file": (
                    "fallback.docx",
                    output.getvalue(),
                    (
                        "application/vnd.openxmlformats-officedocument."
                        "wordprocessingml.document"
                    ),
                )
            },
        )
        self.assertEqual(upload.status_code, 201, upload.text)
        response = await self.http.post(
            "/api/v1/management/pipelines/pipeline_document_auto/versions/1/test",
            headers=ORDINARY_HEADERS,
            json={
                "source": {
                    "type": "uploaded_file",
                    "file_id": upload.json()["data"]["file_id"],
                }
            },
        )
        task = TaskDetailResponse.model_validate_json(response.content)
        self.assertEqual(response.status_code, 201, response.text)

        executed = await WorkerAgent(
            worker_id=WORKER_ID,
            client=self.worker_client,
            backends=registry,
            maximum_concurrency=1,
            lease_renew_interval_seconds=20,
        ).run_once()
        self.assertEqual(executed, 1)

        stages_response = await self.http.get(
            f"/api/v1/tasks/{task.data.task_id}/stages",
            headers=ORDINARY_HEADERS,
        )
        stages = StageListResponse.model_validate_json(stages_response.content)
        self.assertEqual(len(stages.items), 1)
        backend_response = await self.http.get(
            "/api/v1/management/backends",
            headers=ORDINARY_HEADERS,
            params={"name_contains": "builtin_office"},
        )
        self.assertEqual(
            stages.items[0].backend_id,
            backend_response.json()["items"][0]["backend_id"],
        )
        result_response = await self.http.get(
            f"/api/v1/tasks/{task.data.task_id}/result",
            headers=ORDINARY_HEADERS,
        )
        result = ParseResultResponse.model_validate_json(result_response.content)
        self.assertIn("Built-in Office fallback", result.data.model_dump_json())


if __name__ == "__main__":
    unittest.main()
