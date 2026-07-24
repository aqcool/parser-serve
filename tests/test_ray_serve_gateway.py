from __future__ import annotations

import hashlib
import unittest
from datetime import UTC, datetime
from unittest.mock import patch

from pydantic import ValidationError

from parser_serve.ray_serve import (
    RayServeDeploymentConfig,
    RemoteProtocolGateway,
    build_ray_serve_application,
)
from parser_serve.schema.error import ErrorCode
from parser_serve.schema.hardware import DeviceRuntime
from parser_serve.schema.remote import (
    RemoteParseFailed,
    RemoteParseRequest,
    RemoteParseSucceeded,
    RemoteSourceFile,
)
from parser_serve.schema.result import ContentMetadata, ParseResult
from parser_serve.schema.source import SourceMetadata
from parser_serve.schema.common import MediaCategory


NOW = datetime(2026, 7, 24, 12, 0, tzinfo=UTC)
FILE_CONTENT = b"ray serve source"
SOURCE = SourceMetadata(
    filename="sample.txt",
    mime_type="text/plain",
    media_category=MediaCategory.TEXT,
    size_bytes=len(FILE_CONTENT),
    sha256=hashlib.sha256(FILE_CONTENT).hexdigest(),
)


def remote_request(*, file: bool = False) -> RemoteParseRequest:
    return RemoteParseRequest(
        task_id="task_rayserve1",
        stage_id="stage_rayserve1",
        backend_name="ray_model",
        backend_version="1.0",
        runtime=DeviceRuntime.CUDA,
        device_id="cuda-1",
        source=SOURCE,
        source_text=None if file else "hello",
        source_file=(
            RemoteSourceFile(
                filename="sample.txt",
                mime_type="text/plain",
                size_bytes=len(FILE_CONTENT),
                sha256=hashlib.sha256(FILE_CONTENT).hexdigest(),
            )
            if file
            else None
        ),
        timeout_seconds=10,
    )


def success(request: RemoteParseRequest) -> RemoteParseSucceeded:
    return RemoteParseSucceeded(
        status="succeeded",
        result=ParseResult(
            schema_version="1.0",
            task_id=request.task_id,
            source=request.source,
            metadata=ContentMetadata(),
            created_at=NOW,
        ),
    )


class SuccessHandler:
    def __init__(self) -> None:
        self.calls: list[tuple[RemoteParseRequest, bytes | None]] = []

    async def parse(
        self,
        request: RemoteParseRequest,
        file_content: bytes | None,
    ) -> RemoteParseSucceeded:
        self.calls.append((request, file_content))
        return success(request)


class RayServeGatewayTests(unittest.IsolatedAsyncioTestCase):
    def failed(self, response: object) -> RemoteParseFailed:
        self.assertIsInstance(response, RemoteParseFailed)
        assert isinstance(response, RemoteParseFailed)
        return response

    async def test_validates_file_and_preserves_exact_device_assignment(self) -> None:
        handler = SuccessHandler()
        gateway = RemoteProtocolGateway(handler, maximum_file_bytes=1024)

        response = await gateway.parse(
            remote_request(file=True).model_dump_json(),
            FILE_CONTENT,
        )

        self.assertIsInstance(response, RemoteParseSucceeded)
        self.assertEqual(handler.calls[0][0].device_id, "cuda-1")
        self.assertEqual(handler.calls[0][1], FILE_CONTENT)

    async def test_rejects_missing_oversized_and_corrupted_file(self) -> None:
        gateway = RemoteProtocolGateway(SuccessHandler(), maximum_file_bytes=8)

        missing = await gateway.parse(remote_request(file=True).model_dump_json(), None)
        oversized = await gateway.parse(
            remote_request(file=True).model_dump_json(), FILE_CONTENT
        )
        corrupted = await RemoteProtocolGateway(
            SuccessHandler(), maximum_file_bytes=1024
        ).parse(remote_request(file=True).model_dump_json(), b"x" * len(FILE_CONTENT))

        missing = self.failed(missing)
        self.assertEqual(missing.error.code, ErrorCode.VALIDATION_ERROR)
        oversized = self.failed(oversized)
        self.assertEqual(oversized.error.code, ErrorCode.FILE_TOO_LARGE)
        corrupted = self.failed(corrupted)
        self.assertEqual(corrupted.error.code, ErrorCode.VALIDATION_ERROR)

    async def test_maps_invalid_request_timeout_and_handler_failure(self) -> None:
        class TimeoutHandler:
            async def parse(
                self,
                request: RemoteParseRequest,
                file_content: bytes | None,
            ) -> RemoteParseSucceeded:
                raise TimeoutError

        class FailedHandler:
            async def parse(
                self,
                request: RemoteParseRequest,
                file_content: bytes | None,
            ) -> RemoteParseSucceeded:
                raise RuntimeError("secret model failure")

        invalid = await RemoteProtocolGateway(
            SuccessHandler(), maximum_file_bytes=1
        ).parse("{}", None)
        timed_out = await RemoteProtocolGateway(
            TimeoutHandler(), maximum_file_bytes=1
        ).parse(remote_request().model_dump_json(), None)
        failed = await RemoteProtocolGateway(
            FailedHandler(), maximum_file_bytes=1
        ).parse(remote_request().model_dump_json(), None)

        invalid = self.failed(invalid)
        timed_out = self.failed(timed_out)
        failed = self.failed(failed)
        self.assertEqual(invalid.error.code, ErrorCode.VALIDATION_ERROR)
        self.assertEqual(timed_out.error.code, ErrorCode.TIMEOUT)
        self.assertTrue(timed_out.error.retryable)
        self.assertEqual(failed.error.code, ErrorCode.INTERNAL_ERROR)
        self.assertNotIn("secret", failed.error.message)

    async def test_rejects_result_identity_changes(self) -> None:
        class WrongTaskHandler:
            async def parse(
                self,
                request: RemoteParseRequest,
                file_content: bytes | None,
            ) -> RemoteParseSucceeded:
                response = success(request)
                return response.model_copy(
                    update={
                        "result": response.result.model_copy(
                            update={"task_id": "task_other123"}
                        )
                    }
                )

        response = await RemoteProtocolGateway(
            WrongTaskHandler(), maximum_file_bytes=1
        ).parse(remote_request().model_dump_json(), None)

        response = self.failed(response)
        self.assertEqual(response.error.code, ErrorCode.INTERNAL_ERROR)


class RayServeConfigurationTests(unittest.TestCase):
    def test_configuration_is_strict_and_optional_import_has_clear_error(self) -> None:
        with self.assertRaises(ValidationError):
            RayServeDeploymentConfig(num_replicas=0)
        with patch(
            "parser_serve.ray_serve.gateway.import_module",
            side_effect=ImportError,
        ):
            with self.assertRaisesRegex(RuntimeError, "ray-serve dependency profile"):
                build_ray_serve_application(SuccessHandler)


if __name__ == "__main__":
    unittest.main()
