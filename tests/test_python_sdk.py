from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import httpx
from pydantic import SecretStr

from parser_serve.api import create_app
from parser_serve.persistence import Database
from parser_serve.schema.error import ErrorCode
from parser_serve.schema.source import TextSource
from parser_serve.schema.task import (
    CreateTaskRequest,
    TaskListQuery,
    TaskStatus,
)
from parser_serve.sdk import (
    AsyncParserServeClient,
    OPERATION_SPECS,
    ParserServeApiError,
    ParserServeClient,
)
from parser_serve.settings import Environment, Settings
from parser_serve.storage import LocalFileStorage
from scripts.generate_python_sdk import OPENAPI, TARGET, generate


API_KEY = f"parser_{'s' * 32}"


class PythonSdkGenerationTests(unittest.TestCase):
    def test_generated_operation_table_is_current_and_complete(self) -> None:
        specification = json.loads(OPENAPI.read_text(encoding="utf-8"))
        generated = generate(specification)

        self.assertEqual(TARGET.read_text(encoding="utf-8"), generated)
        expected = {
            operation["operationId"]
            for path_item in specification["paths"].values()
            for method, operation in path_item.items()
            if method in {"get", "post", "put", "patch", "delete", "options", "head"}
        }
        self.assertEqual(set(OPERATION_SPECS), expected)
        self.assertTrue(
            all(
                hasattr(ParserServeClient, f"call_{operation_id}")
                and hasattr(AsyncParserServeClient, f"call_{operation_id}")
                for operation_id in expected
            )
        )
        self.assertIn("class GetTaskPath(TypedDict)", generated)
        self.assertIn("type GetTaskResponse =", generated)
        self.assertIn("file: UploadFile", generated)


class SyncPythonSdkTests(unittest.TestCase):
    def test_request_encoding_authentication_and_typed_error(self) -> None:
        requests: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            requests.append(request)
            if request.url.path.endswith("/missing"):
                return httpx.Response(
                    404,
                    json={
                        "request_id": "req_01J00000000000000000000000",
                        "error": {
                            "code": "NOT_FOUND",
                            "message": "Task was not found",
                            "retryable": False,
                            "field_violations": [],
                            "context": {},
                        },
                    },
                )
            return httpx.Response(200, json={})

        transport = httpx.MockTransport(handler)
        http_client = httpx.Client(
            base_url="https://parser.example", transport=transport
        )
        sdk = ParserServeClient("https://ignored.example", API_KEY, client=http_client)

        sdk.request_raw(
            "list_tasks",
            query={"statuses": [TaskStatus.PENDING, TaskStatus.FAILED]},
        )
        self.assertEqual(
            requests[0].url.params.get_list("statuses"),
            ["pending", "failed"],
        )
        self.assertEqual(requests[0].headers["Authorization"], f"Bearer {API_KEY}")

        with self.assertRaises(ParserServeApiError) as raised:
            sdk.get_task("missing")
        self.assertEqual(raised.exception.status_code, 404)
        self.assertEqual(raised.exception.code, ErrorCode.NOT_FOUND)
        self.assertIsInstance(raised.exception.code, ErrorCode)
        self.assertFalse(raised.exception.retryable)
        self.assertEqual(raised.exception.request_id, "req_01J00000000000000000000000")

        with self.assertRaisesRegex(ValueError, "missing path parameter"):
            sdk.request_raw("get_task")
        with self.assertRaisesRegex(ValueError, "managed by the SDK"):
            sdk.request_raw(
                "get_health", headers={"authorization": "Bearer replacement"}
            )

        sdk.close()
        self.assertFalse(http_client.is_closed)
        http_client.close()

    def test_future_error_code_preserves_structured_error_fields(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                503,
                json={
                    "request_id": "req_01J00000000000000000000000",
                    "error": {
                        "code": "FUTURE_ERROR",
                        "message": "retry later",
                        "retryable": True,
                        "field_violations": [],
                        "context": {"generation": 2},
                    },
                },
            )

        transport = httpx.MockTransport(handler)
        with httpx.Client(
            transport=transport,
            base_url="https://parser.invalid",
        ) as http_client:
            sdk = ParserServeClient(
                "https://ignored.invalid",
                API_KEY,
                client=http_client,
            )
            with self.assertRaises(ParserServeApiError) as raised:
                sdk.get_task("task_futureerror1")

        self.assertEqual(raised.exception.code, "FUTURE_ERROR")
        self.assertTrue(raised.exception.retryable)
        self.assertEqual(
            raised.exception.request_id,
            "req_01J00000000000000000000000",
        )
        self.assertIn("retry later", str(raised.exception))


class AsyncPythonSdkAsgiTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        root = Path(self.temporary_directory.name)
        self.database = Database(f"sqlite+aiosqlite:///{root / 'sdk.sqlite3'}")
        await self.database.create_schema_for_testing()
        app = create_app(
            Settings(
                environment=Environment.TEST,
                api_keys=[SecretStr(API_KEY)],
                maximum_upload_bytes=1024,
            ),
            database=self.database,
            storage=LocalFileStorage(root / "objects"),
        )
        self.http_client = httpx.AsyncClient(
            base_url="http://parser.test",
            transport=httpx.ASGITransport(app=app),
        )
        self.sdk = AsyncParserServeClient(
            "http://ignored.test", API_KEY, client=self.http_client
        )

    async def asyncTearDown(self) -> None:
        await self.http_client.aclose()
        await self.database.dispose()
        self.temporary_directory.cleanup()

    async def test_typed_task_upload_list_and_error_against_real_asgi(self) -> None:
        health = await self.sdk.health()
        self.assertEqual(health.status, "healthy")

        created = await self.sdk.create_task(
            CreateTaskRequest(
                source=TextSource(
                    type="text",
                    text="Python SDK end-to-end",
                    filename="sdk.txt",
                ),
                client_reference="python-sdk-test",
            ),
            idempotency_key="python-sdk-idempotency",
        )
        task = await self.sdk.get_task(created.task_id)
        self.assertEqual(task.task_id, created.task_id)
        self.assertEqual(task.client_reference, "python-sdk-test")
        wire_task = await self.sdk.call_get_task(path={"task_id": created.task_id})
        self.assertEqual(wire_task["data"]["task_id"], created.task_id)

        listed = await self.sdk.list_tasks(
            TaskListQuery(statuses=[task.status], limit=10)
        )
        self.assertIn(task.task_id, {item.task_id for item in listed.items})

        uploaded = await self.sdk.upload_file(
            "sdk.txt", b"SDK uploaded content", "text/plain"
        )
        self.assertEqual(uploaded.filename, "sdk.txt")
        self.assertEqual(uploaded.size_bytes, len(b"SDK uploaded content"))
        wire_uploaded = await self.sdk.call_upload_file(
            body={"file": ("typed.txt", b"typed upload", "text/plain")}
        )
        self.assertEqual(wire_uploaded["data"]["filename"], "typed.txt")

        with self.assertRaises(ParserServeApiError) as raised:
            await self.sdk.get_task("task_00000000missing")
        self.assertEqual(raised.exception.code, ErrorCode.NOT_FOUND)
        self.assertIsNotNone(raised.exception.request_id)

        await self.sdk.aclose()
        self.assertFalse(self.http_client.is_closed)


if __name__ == "__main__":
    unittest.main()
