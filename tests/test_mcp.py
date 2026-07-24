from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient
from pydantic import SecretStr

from parser_serve.api import create_app
from parser_serve.persistence import Database
from parser_serve.settings import Environment, Settings


API_KEY = f"parser_{'m' * 32}"
AUTH_HEADERS = {
    "Authorization": f"Bearer {API_KEY}",
    "Accept": "application/json, text/event-stream",
    "Content-Type": "application/json",
}


class McpApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        database_path = Path(self.temporary_directory.name) / "mcp.sqlite3"
        self.database = Database(f"sqlite+aiosqlite:///{database_path}")
        asyncio.run(self.database.create_schema_for_testing())
        self.client = TestClient(
            create_app(
                Settings(
                    environment=Environment.TEST,
                    api_keys=[SecretStr(API_KEY)],
                ),
                database=self.database,
            ),
            base_url="http://localhost:8000",
        )
        self.client.__enter__()
        self.request_id = 0

    def tearDown(self) -> None:
        self.client.__exit__(None, None, None)
        asyncio.run(self.database.dispose())
        self.temporary_directory.cleanup()

    def rpc(
        self,
        method: str,
        params: dict[str, object] | None = None,
        *,
        headers: dict[str, str] | None = None,
    ):
        self.request_id += 1
        return self.client.post(
            "/mcp",
            headers=headers or AUTH_HEADERS,
            json={
                "jsonrpc": "2.0",
                "id": self.request_id,
                "method": method,
                "params": params or {},
            },
        )

    def test_requires_ordinary_api_key(self) -> None:
        response = self.rpc("tools/list", headers={"Accept": "application/json"})
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["error"]["code"], -32001)

        response = self.rpc(
            "tools/list",
            headers={
                "X-API-Key": API_KEY,
                "Accept": "application/json, text/event-stream",
                "Content-Type": "application/json",
            },
        )
        self.assertEqual(response.status_code, 200, response.text)

        created = self.client.post(
            "/api/v1/management/api-keys",
            headers={"Authorization": f"Bearer {API_KEY}"},
            json={"name": "MCP database key"},
        )
        self.assertEqual(created.status_code, 201, created.text)
        database_key = created.json()["data"]["api_key"]
        response = self.rpc(
            "tools/list",
            headers={
                "Authorization": f"Bearer {database_key}",
                "Accept": "application/json, text/event-stream",
                "Content-Type": "application/json",
            },
        )
        self.assertEqual(response.status_code, 200, response.text)

    def test_lists_complete_typed_tool_and_resource_contracts(self) -> None:
        response = self.rpc("tools/list")
        self.assertEqual(response.status_code, 200, response.text)
        tools = response.json()["result"]["tools"]
        self.assertEqual(
            {tool["name"] for tool in tools},
            {
                "parser_submit",
                "parser_get_task",
                "parser_get_result",
                "parser_cancel_task",
                "parser_list_capabilities",
                "parser_list_pipelines",
                "parser_list_backends",
            },
        )
        for tool in tools:
            self.assertEqual(tool["inputSchema"]["type"], "object")
            self.assertIn("outputSchema", tool)

        response = self.rpc("resources/list")
        resources = response.json()["result"]["resources"]
        self.assertEqual(
            {resource["uri"] for resource in resources},
            {
                "parser://capabilities",
                "parser://pipelines",
                "parser://backends",
            },
        )
        response = self.rpc("resources/templates/list")
        templates = response.json()["result"]["resourceTemplates"]
        self.assertEqual(
            {template["uriTemplate"] for template in templates},
            {
                "parser://tasks/{task_id}",
                "parser://tasks/{task_id}/result",
            },
        )

    def test_submit_get_cancel_and_read_task_resource(self) -> None:
        response = self.rpc(
            "tools/call",
            {
                "name": "parser_submit",
                "arguments": {
                    "request": {
                        "source": {
                            "type": "text",
                            "text": "MCP submission",
                            "filename": "mcp.txt",
                        }
                    },
                    "idempotency_key": "mcp-submission-1",
                },
            },
        )
        self.assertEqual(response.status_code, 200, response.text)
        result = response.json()["result"]
        self.assertFalse(result.get("isError", False))
        task_id = result["structuredContent"]["task_id"]

        response = self.rpc(
            "tools/call",
            {
                "name": "parser_get_task",
                "arguments": {"reference": {"task_id": task_id}},
            },
        )
        self.assertEqual(
            response.json()["result"]["structuredContent"]["status"],
            "pending",
        )

        response = self.rpc(
            "resources/read",
            {"uri": f"parser://tasks/{task_id}"},
        )
        contents = response.json()["result"]["contents"]
        self.assertEqual(len(contents), 1)
        self.assertIn(task_id, contents[0]["text"])

        response = self.rpc(
            "tools/call",
            {
                "name": "parser_get_result",
                "arguments": {"reference": {"task_id": task_id}},
            },
        )
        self.assertTrue(response.json()["result"]["isError"])

        response = self.rpc(
            "tools/call",
            {
                "name": "parser_cancel_task",
                "arguments": {"reference": {"task_id": task_id}},
            },
        )
        self.assertEqual(
            response.json()["result"]["structuredContent"]["status"],
            "cancelled",
        )


if __name__ == "__main__":
    unittest.main()
