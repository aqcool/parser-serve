from __future__ import annotations

import asyncio
import hashlib
import json
import unittest
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from pydantic import AnyUrl, HttpUrl, SecretStr, ValidationError

from parser_serve.backends import (
    BackendContext,
    BackendOutput,
    BackendRegistry,
    ProducedArtifact,
    builtin_cpu_backends,
)
from parser_serve.schema.artifact import Artifact, ArtifactType
from parser_serve.schema.backend import BackendCapability, BackendLoadTarget
from parser_serve.schema.common import MediaCategory
from parser_serve.schema.hardware import (
    DeviceRuntime,
    HardwareVendor,
)
from parser_serve.schema.source import (
    SourceMetadata,
    ObjectStorageSource,
    TextSource,
    UploadedFileSource,
    UrlSource,
)
from parser_serve.schema.task import TaskOptions
from parser_serve.schema.worker import (
    CompleteStageRequest,
    LeasedStage,
    WorkerDetailResponse,
    WorkerLeaseRequest,
    WorkerHeartbeatRequest,
    WorkerHeartbeatResponse,
    WorkerHeartbeatData,
    WorkerRegistrationRequest,
    WorkerRegistrationResponse,
    WorkerRegistrationData,
    WorkerStatus,
)
from parser_serve.worker import (
    CpuWorkerService,
    HardwareProbe,
    HardwareProbeError,
    WorkerAgent,
    WorkerService,
    WorkerSettings,
    configured_device,
)


NOW = datetime(2026, 7, 24, 12, 0, tzinfo=UTC)


def text_lease(*, uploaded: bool = False) -> LeasedStage:
    uploaded_content = b"# Uploaded"
    return LeasedStage(
        task_id="task_agent1234",
        stage_id="stage_agent1234",
        stage_name="parse",
        backend_id="backend_text1234",
        backend_name="builtin_text",
        backend_version="1.0",
        backend_candidates=["backend_text1234"],
        runtime=DeviceRuntime.CPU,
        source=(
            UploadedFileSource(type="uploaded_file", file_id="file_agent1234")
            if uploaded
            else TextSource(
                type="text",
                text="# Hello",
                filename="note.md",
                mime_type="text/markdown",
            )
        ),
        source_metadata=SourceMetadata(
            filename="note.md",
            mime_type="text/markdown",
            media_category=MediaCategory.TEXT,
            size_bytes=len(uploaded_content) if uploaded else None,
            sha256=(hashlib.sha256(uploaded_content).hexdigest() if uploaded else None),
        ),
        task_options=TaskOptions(),
        timeout_seconds=30,
        attempt=1,
        maximum_attempts=2,
        lease_token=f"lease_{'w' * 32}",
        lease_expires_at=NOW + timedelta(seconds=60),
    )


class FakeWorkerClient:
    def __init__(self, leases: tuple[LeasedStage, ...]) -> None:
        self.leases = leases
        self.started: list[str] = []
        self.progress_values: list[float] = []
        self.uploaded: list[ProducedArtifact] = []
        self.completions: list[CompleteStageRequest] = []
        self.renewals = 0
        self.renew_failure = False
        self.download_metadata: tuple[int, str] | None = None

    async def register(
        self,
        request: WorkerRegistrationRequest,
    ) -> WorkerRegistrationResponse:
        raise NotImplementedError

    async def heartbeat(
        self,
        request: WorkerHeartbeatRequest,
    ) -> WorkerHeartbeatResponse:
        raise NotImplementedError

    async def drain(self, worker_id: str) -> WorkerDetailResponse:
        raise NotImplementedError

    async def lease(self, request: WorkerLeaseRequest) -> tuple[LeasedStage, ...]:
        self.last_lease_request = request
        leases, self.leases = self.leases, ()
        return leases

    async def start(self, lease: LeasedStage, worker_id: str) -> None:
        self.started.append(lease.stage_id)

    async def renew(self, lease: LeasedStage, worker_id: str) -> None:
        self.renewals += 1
        if self.renew_failure:
            raise RuntimeError("renewal unavailable")

    async def progress(
        self,
        lease: LeasedStage,
        worker_id: str,
        progress_percent: float,
    ) -> None:
        self.progress_values.append(progress_percent)

    async def download_source(
        self,
        *,
        worker_id: str,
        file_id: str,
        destination: Path,
        expected_size_bytes: int,
        expected_sha256: str,
    ) -> Path:
        destination.parent.mkdir(parents=True)
        content = b"# Uploaded"
        self.download_metadata = (expected_size_bytes, expected_sha256)
        destination.write_bytes(content)
        return destination

    async def upload_artifact(
        self,
        *,
        worker_id: str,
        lease: LeasedStage,
        artifact: ProducedArtifact,
        idempotency_key: str,
    ) -> Artifact:
        self.uploaded.append(artifact)
        content = artifact.data or (
            artifact.path.read_bytes() if artifact.path else b""
        )
        return Artifact(
            artifact_id=f"artifact_{len(self.uploaded):08d}",
            type=artifact.type,
            filename=artifact.filename,
            mime_type=artifact.mime_type,
            size_bytes=len(content),
            sha256=hashlib.sha256(content).hexdigest(),
            storage_uri=f"local:///artifacts/{len(self.uploaded)}",
            created_at=NOW,
        )

    async def complete(
        self,
        lease: LeasedStage,
        request: CompleteStageRequest,
    ) -> None:
        self.completions.append(request)


class WorkerAgentTests(unittest.IsolatedAsyncioTestCase):
    async def test_enforces_backend_level_concurrency(self) -> None:
        class ConcurrencyBackend:
            capability = BackendCapability(
                name="builtin_text",
                version="1.0",
                media_categories=[MediaCategory.TEXT],
                runtimes=[DeviceRuntime.CPU],
                maximum_concurrency=1,
            )

            def __init__(self) -> None:
                self.active = 0
                self.maximum_active = 0

            async def execute(self, context: BackendContext) -> BackendOutput:
                self.active += 1
                self.maximum_active = max(self.maximum_active, self.active)
                await asyncio.sleep(0.01)
                self.active -= 1
                return BackendOutput(
                    artifacts=(
                        ProducedArtifact(
                            type=ArtifactType.RESULT_TEXT,
                            filename="result.txt",
                            mime_type="text/plain",
                            data=b"done",
                        ),
                    )
                )

        backend = ConcurrencyBackend()
        registry = BackendRegistry()
        registry.register(backend)
        second_lease = text_lease().model_copy(
            update={
                "task_id": "task_agent5678",
                "stage_id": "stage_agent5678",
                "lease_token": f"lease_{'x' * 32}",
            }
        )
        client = FakeWorkerClient((text_lease(), second_lease))
        agent = WorkerAgent(
            worker_id="worker_agent123",
            client=client,
            backends=registry,
            maximum_concurrency=2,
            lease_renew_interval_seconds=60,
        )

        count = await agent.run_once()

        self.assertEqual(count, 2)
        self.assertEqual(backend.maximum_active, 1)
        self.assertEqual(len(client.completions), 2)
        self.assertTrue(
            all(completion.status == "succeeded" for completion in client.completions)
        )

    async def test_leases_executes_uploads_and_completes_text_stage(self) -> None:
        client = FakeWorkerClient((text_lease(),))
        agent = WorkerAgent(
            worker_id="worker_agent123",
            client=client,
            backends=builtin_cpu_backends(),
            maximum_concurrency=2,
            lease_wait_seconds=12.0,
            lease_renew_interval_seconds=60,
        )

        count = await agent.run_once()

        self.assertEqual(count, 1)
        self.assertEqual(client.last_lease_request.available_slots, 2)
        self.assertEqual(client.last_lease_request.wait_seconds, 12.0)
        self.assertEqual(client.started, ["stage_agent1234"])
        self.assertEqual(client.progress_values, [10.0, 80.0])
        self.assertEqual(client.uploaded[0].filename, "result.json")
        self.assertEqual(client.completions[0].status, "succeeded")
        self.assertEqual(
            client.completions[0].result_uri,
            "local:///artifacts/1",
        )

    async def test_downloads_uploaded_source_before_execution(self) -> None:
        client = FakeWorkerClient(())
        agent = WorkerAgent(
            worker_id="worker_agent123",
            client=client,
            backends=builtin_cpu_backends(),
            maximum_concurrency=1,
        )

        succeeded = await agent.execute(text_lease(uploaded=True))

        self.assertTrue(succeeded)
        self.assertEqual(client.completions[0].status, "succeeded")

    async def test_fetches_url_source_before_static_web_execution(self) -> None:
        source_url = "https://example.com/docs/index.html"
        url_lease = text_lease().model_copy(
            update={
                "backend_id": "backend_web12345",
                "backend_name": "builtin_web",
                "backend_candidates": ["backend_web12345"],
                "source": UrlSource(type="url", url=HttpUrl(source_url)),
                "source_metadata": SourceMetadata(
                    filename="index.html",
                    mime_type="text/html",
                    media_category=MediaCategory.WEB,
                    attributes={"source_url": source_url},
                ),
            }
        )

        async def fetch(
            _: object,
            destination: Path,
            **__: object,
        ) -> Path:
            destination.parent.mkdir(parents=True)
            destination.write_text(
                '<html><body><a href="../about">About</a></body></html>',
                encoding="utf-8",
            )
            return destination

        client = FakeWorkerClient(())
        agent = WorkerAgent(
            worker_id="worker_agent123",
            client=client,
            backends=builtin_cpu_backends(),
            maximum_concurrency=1,
        )
        with patch(
            "parser_serve.worker.agent.fetch_url_source",
            side_effect=fetch,
        ):
            succeeded = await agent.execute(url_lease)

        self.assertTrue(succeeded)
        payload = (client.uploaded[0].data or b"").decode()
        self.assertIn("https://example.com/about", payload)

    async def test_downloads_object_storage_source_before_execution(self) -> None:
        object_lease = text_lease().model_copy(
            update={
                "source": ObjectStorageSource(
                    type="object_storage",
                    uri=AnyUrl("s3://documents/note.md"),
                    version_id="version-1",
                ),
                "source_metadata": SourceMetadata(
                    filename="note.md",
                    mime_type="text/markdown",
                    media_category=MediaCategory.TEXT,
                ),
            }
        )

        async def download(
            _: object,
            destination: Path,
            **__: object,
        ) -> Path:
            destination.parent.mkdir(parents=True)
            destination.write_text("# Stored object", encoding="utf-8")
            return destination

        client = FakeWorkerClient(())
        agent = WorkerAgent(
            worker_id="worker_agent123",
            client=client,
            backends=builtin_cpu_backends(),
            maximum_concurrency=1,
            allowed_s3_buckets={"documents"},
        )
        with patch(
            "parser_serve.worker.agent.download_object_storage_source",
            side_effect=download,
        ):
            succeeded = await agent.execute(object_lease)

        self.assertTrue(succeeded)
        self.assertIn("Stored object", (client.uploaded[0].data or b"").decode())

    async def test_unknown_backend_reports_typed_failure(self) -> None:
        unknown = text_lease().model_copy(update={"backend_name": "missing_backend"})
        client = FakeWorkerClient(())
        agent = WorkerAgent(
            worker_id="worker_agent123",
            client=client,
            backends=builtin_cpu_backends(),
            maximum_concurrency=1,
        )

        succeeded = await agent.execute(unknown)

        self.assertFalse(succeeded)
        completion = client.completions[0]
        self.assertEqual(completion.status, "failed")
        self.assertIsNotNone(completion.error)
        if completion.error is not None:
            self.assertEqual(completion.error.code, "BACKEND_NOT_AVAILABLE")

    async def test_lease_renewal_failure_cancels_backend_and_reports_retryable(
        self,
    ) -> None:
        class SlowBackend:
            capability = BackendCapability(
                name="builtin_text",
                version="1.0",
                media_categories=[MediaCategory.TEXT],
                runtimes=[DeviceRuntime.CPU],
                maximum_concurrency=1,
            )

            async def execute(self, context: BackendContext) -> BackendOutput:
                await asyncio.sleep(10)
                return BackendOutput(
                    artifacts=(
                        ProducedArtifact(
                            type=ArtifactType.RESULT_TEXT,
                            filename="result.txt",
                            mime_type="text/plain",
                            data=b"late",
                        ),
                    )
                )

        registry = BackendRegistry()
        registry.register(SlowBackend())
        client = FakeWorkerClient(())
        client.renew_failure = True
        agent = WorkerAgent(
            worker_id="worker_agent123",
            client=client,
            backends=registry,
            maximum_concurrency=1,
            lease_renew_interval_seconds=0.001,
        )

        succeeded = await agent.execute(text_lease())

        self.assertFalse(succeeded)
        self.assertEqual(client.renewals, 1)
        self.assertEqual(client.completions[0].status, "failed")
        self.assertIsNotNone(client.completions[0].error)
        if client.completions[0].error is not None:
            self.assertTrue(client.completions[0].error.retryable)
        self.assertEqual(agent.active_count, 0)


class ServiceFakeWorkerClient(FakeWorkerClient):
    def __init__(self) -> None:
        super().__init__(())
        self.registration_request: WorkerRegistrationRequest | None = None
        self.heartbeat_requests: list[WorkerHeartbeatRequest] = []
        self.drained_worker_ids: list[str] = []

    async def register(
        self,
        request: WorkerRegistrationRequest,
    ) -> WorkerRegistrationResponse:
        self.registration_request = request
        return WorkerRegistrationResponse(
            request_id="req_worker123",
            data=WorkerRegistrationData(
                worker_id=request.worker_id,
                accepted=True,
                heartbeat_interval_seconds=1,
                lease_duration_seconds=30,
                registered_at=NOW,
            ),
        )

    async def heartbeat(
        self,
        request: WorkerHeartbeatRequest,
    ) -> WorkerHeartbeatResponse:
        self.heartbeat_requests.append(request)
        return WorkerHeartbeatResponse(
            request_id="req_worker456",
            data=WorkerHeartbeatData(
                accepted=True,
                next_heartbeat_seconds=1,
                should_drain=True,
            ),
        )

    async def drain(self, worker_id: str) -> WorkerDetailResponse:
        self.drained_worker_ids.append(worker_id)
        return WorkerDetailResponse.model_construct(
            request_id="req_workerdrain",
            data=None,
        )


class CpuWorkerServiceTests(unittest.IsolatedAsyncioTestCase):
    async def test_preloads_and_unloads_managed_backend_around_service(self) -> None:
        events: list[str] = []

        class ManagedTestBackend:
            capability = BackendCapability(
                name="managed_model",
                version="1.0",
                media_categories=[MediaCategory.TEXT],
                runtimes=[DeviceRuntime.CPU],
                maximum_concurrency=1,
            )

            async def load(self) -> None:
                events.append("load")

            async def unload(self) -> None:
                events.append("unload")

            async def execute(self, context: BackendContext) -> BackendOutput:
                raise AssertionError("no Stage should be leased")

        registry = BackendRegistry()
        registry.register(ManagedTestBackend())
        settings = WorkerSettings(
            api_key=SecretStr(f"parser_{'m' * 32}"),
            worker_id="worker_managed12",
            preload_backends=[BackendLoadTarget(name="managed_model", version="1.0")],
        )

        await WorkerService(
            settings=settings,
            client=ServiceFakeWorkerClient(),
            backends=registry,
        ).run()

        self.assertEqual(events, ["load", "unload"])
        self.assertEqual(registry.loaded_backends, ())

    async def test_registers_capabilities_and_stops_when_draining(self) -> None:
        settings = WorkerSettings(
            api_key=SecretStr(f"parser_{'s' * 32}"),
            worker_id="worker_service123",
            maximum_concurrency=3,
            labels={"zone": "local"},
        )
        client = ServiceFakeWorkerClient()
        service = CpuWorkerService(
            settings=settings,
            client=client,
            backends=builtin_cpu_backends(include_unavailable_system_tools=True),
        )

        await service.run()

        self.assertIsNotNone(client.registration_request)
        if client.registration_request is not None:
            self.assertEqual(client.registration_request.maximum_concurrency, 3)
            self.assertEqual(client.registration_request.labels["zone"], "local")
            self.assertIn(
                client.registration_request.labels["parser_serve.tool.ffmpeg"],
                {"available", "unavailable"},
            )
            self.assertIn(
                client.registration_request.labels["parser_serve.tool.libreoffice"],
                {"available", "unavailable"},
            )
            self.assertEqual(
                client.registration_request.labels["parser_serve.hardware.probe"],
                "builtin",
            )
            self.assertEqual(
                [item.name for item in client.registration_request.backends],
                [
                    "builtin_ffmpeg",
                    "builtin_image",
                    "builtin_office",
                    "builtin_pdf",
                    "builtin_text",
                    "builtin_web",
                ],
            )
        self.assertEqual(len(client.heartbeat_requests), 1)
        self.assertEqual(client.drained_worker_ids, [settings.worker_id])
        self.assertEqual(client.heartbeat_requests[0].sequence, 0)
        self.assertEqual(
            client.heartbeat_requests[0].devices[0].device_id,
            "cpu-0",
        )

    async def test_required_runtime_probe_failure_reports_unhealthy(self) -> None:
        worker_settings = WorkerSettings(
            api_key=SecretStr(f"parser_{'p' * 32}"),
            worker_id="worker_probe1234",
            device_probe_command=["vendor-probe", "--json"],
            device_probe_required=True,
        )
        payload = json.dumps(
            {
                "schema_version": "1.0",
                "devices": [
                    {
                        "device_id": "cpu-0",
                        "vendor": "generic",
                        "runtime": "cpu",
                        "model": "Test CPU",
                    }
                ],
                "usage": [{"device_id": "cpu-0"}],
            }
        )
        calls = 0

        def runner(_arguments: Sequence[str], _timeout: float) -> str:
            nonlocal calls
            calls += 1
            if calls > 1:
                raise HardwareProbeError("runtime probe failed")
            return payload

        probe = HardwareProbe(worker_settings, runner=runner)
        client = ServiceFakeWorkerClient()
        service = WorkerService(
            settings=worker_settings,
            client=client,
            backends=builtin_cpu_backends(include_unavailable_system_tools=True),
            hardware_probe=probe,
        )

        await service.run()

        self.assertEqual(len(client.heartbeat_requests), 1)
        self.assertEqual(
            client.heartbeat_requests[0].status,
            WorkerStatus.UNHEALTHY,
        )

    async def test_registration_hides_legacy_office_without_libreoffice(
        self,
    ) -> None:
        worker_settings = WorkerSettings(
            api_key=SecretStr(f"parser_{'o' * 32}"),
            worker_id="worker_officecheck",
        )
        service = WorkerService(
            settings=worker_settings,
            client=ServiceFakeWorkerClient(),
            backends=builtin_cpu_backends(include_unavailable_system_tools=True),
            tool_checks={
                "ffmpeg": lambda: False,
                "libreoffice": lambda: False,
            },
        )

        registration_request = service.registration()
        office = next(
            capability
            for capability in registration_request.backends
            if capability.name == "builtin_office"
        )

        self.assertNotIn("application/msword", office.mime_types)
        self.assertNotIn("application/vnd.ms-excel", office.mime_types)
        self.assertNotIn("application/vnd.ms-powerpoint", office.mime_types)
        self.assertIn(
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            office.mime_types,
        )
        self.assertEqual(
            registration_request.labels["parser_serve.tool.libreoffice"],
            "unavailable",
        )

    async def test_runtime_tool_loss_reports_typed_unhealthy_check(self) -> None:
        worker_settings = WorkerSettings(
            api_key=SecretStr(f"parser_{'t' * 32}"),
            worker_id="worker_toolcheck1",
        )
        ffmpeg_results = iter((True, False))
        client = ServiceFakeWorkerClient()
        service = WorkerService(
            settings=worker_settings,
            client=client,
            backends=builtin_cpu_backends(include_unavailable_system_tools=True),
            tool_checks={
                "ffmpeg": lambda: next(ffmpeg_results),
                "libreoffice": lambda: False,
            },
        )

        await service.run()

        heartbeat = client.heartbeat_requests[0]
        self.assertEqual(heartbeat.status, WorkerStatus.UNHEALTHY)
        checks = {check.name: check for check in heartbeat.resources.health_checks}
        self.assertFalse(checks["ffmpeg"].healthy)
        self.assertEqual(
            checks["ffmpeg"].message,
            "ffmpeg executable is unavailable",
        )
        self.assertTrue(checks["hardware"].healthy)

    async def test_worker_settings_hide_api_key(self) -> None:
        api_key = f"parser_{'k' * 32}"
        settings = WorkerSettings(
            api_key=SecretStr(api_key),
            worker_id="worker_settings12",
        )

        self.assertNotIn(api_key, repr(settings))

    async def test_configured_vendor_device_is_typed(self) -> None:
        settings = WorkerSettings(
            api_key=SecretStr(f"parser_{'v' * 32}"),
            worker_id="worker_cuda1234",
            device_runtime=DeviceRuntime.CUDA,
            device_vendor=HardwareVendor.NVIDIA,
            device_id="cuda-2",
            device_model="NVIDIA test device",
            device_total_memory_bytes=24_000_000_000,
            device_driver_version="test-driver",
            device_runtime_version="test-runtime",
        )

        device = configured_device(settings)

        self.assertEqual(device.runtime, DeviceRuntime.CUDA)
        self.assertEqual(device.vendor, HardwareVendor.NVIDIA)
        self.assertEqual(device.device_id, "cuda-2")
        self.assertEqual(device.total_memory_bytes, 24_000_000_000)

    async def test_vendor_must_match_runtime(self) -> None:
        with self.assertRaisesRegex(ValidationError, "requires device_vendor nvidia"):
            WorkerSettings(
                api_key=SecretStr(f"parser_{'v' * 32}"),
                worker_id="worker_cuda5678",
                device_runtime=DeviceRuntime.CUDA,
                device_vendor=HardwareVendor.GENERIC,
            )


if __name__ == "__main__":
    unittest.main()
