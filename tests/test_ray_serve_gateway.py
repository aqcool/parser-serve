from __future__ import annotations

import hashlib
import unittest
from contextlib import contextmanager
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import patch

from pydantic import ValidationError
from starlette.requests import Request

from parser_serve.ray_serve import (
    RayServeDeploymentConfig,
    RemoteProtocolGateway,
    build_ray_serve_application,
)
from parser_serve.ray_serve.gateway import (
    FileTooLargeError,
    _read_request_body,
    _request_from_body,
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
from parser_serve.schema.trace import TraceContext
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

    async def test_handler_span_uses_explicit_ingress_trace_context(self) -> None:
        handler = SuccessHandler()
        gateway = RemoteProtocolGateway(handler, maximum_file_bytes=1)
        ingress_context = TraceContext(
            traceparent=("00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01")
        )
        captured: dict[str, object] = {}

        @contextmanager
        def fake_span(
            name: str,
            *,
            parent: TraceContext | None = None,
            attributes: object = None,
        ):
            captured.update(name=name, parent=parent, attributes=attributes)
            yield None

        with patch(
            "parser_serve.ray_serve.gateway.trace_span",
            side_effect=fake_span,
        ):
            response = await gateway.parse(
                remote_request().model_dump_json(),
                None,
                parent_trace_context=ingress_context,
            )

        self.assertIsInstance(response, RemoteParseSucceeded)
        self.assertEqual(captured["name"], "parser.remote.execute")
        self.assertEqual(captured["parent"], ingress_context)

    async def test_request_body_limit_applies_before_multipart_parsing(self) -> None:
        class StreamingRequest:
            def __init__(
                self,
                chunks: list[bytes],
                content_length: str | None = None,
            ) -> None:
                self.chunks = chunks
                self.headers = (
                    {"content-length": content_length}
                    if content_length is not None
                    else {}
                )

            async def stream(self):
                for chunk in self.chunks:
                    yield chunk

        with self.assertRaises(FileTooLargeError):
            await _read_request_body(StreamingRequest([b"123", b"456"]), 5)
        with self.assertRaises(FileTooLargeError):
            await _read_request_body(
                StreamingRequest([], content_length="100"),
                5,
            )
        body = await _read_request_body(StreamingRequest([b"12", b"34"]), 4)
        try:
            self.assertEqual(body.read(), b"1234")
        finally:
            body.close()

    async def test_bounded_body_can_be_parsed_as_multipart(self) -> None:
        boundary = "parser-serve-boundary"
        payload = (
            f"--{boundary}\r\n"
            'Content-Disposition: form-data; name="request"\r\n\r\n'
            "{}\r\n"
            f"--{boundary}--\r\n"
        ).encode()

        class StreamingRequest:
            headers = {"content-length": str(len(payload))}
            scope = {
                "type": "http",
                "method": "POST",
                "path": "/",
                "headers": [
                    (
                        b"content-type",
                        f"multipart/form-data; boundary={boundary}".encode(),
                    )
                ],
            }

            async def stream(self):
                yield payload[:10]
                yield payload[10:]

        original = StreamingRequest()
        body = await _read_request_body(original, len(payload))
        try:
            request = _request_from_body(
                Request,
                SimpleNamespace(scope=original.scope),
                body,
            )
            form = await request.form(max_files=1, max_fields=1)
            try:
                self.assertEqual(form["request"], "{}")
            finally:
                await form.close()
        finally:
            body.close()


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
