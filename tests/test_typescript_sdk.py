from __future__ import annotations

import json
import unittest
from pathlib import Path

from scripts.generate_typescript_sdk import generate


ROOT = Path(__file__).resolve().parents[1]
OPENAPI = ROOT / "web" / "openapi.json"
GENERATED = ROOT / "web" / "src" / "api" / "generated.ts"


class TypeScriptSdkContractTests(unittest.TestCase):
    def test_generated_sdk_is_current_and_covers_every_operation(self) -> None:
        specification = json.loads(OPENAPI.read_text(encoding="utf-8"))
        expected = generate(specification)

        self.assertEqual(GENERATED.read_text(encoding="utf-8"), expected)
        operation_ids = {
            operation["operationId"]
            for path_item in specification["paths"].values()
            for method, operation in path_item.items()
            if method in {"get", "post", "put", "patch", "delete", "head", "options"}
        }
        for operation_id in operation_ids:
            self.assertIn(f'"{operation_id}": {{', expected)
            self.assertIn(f'"{operation_id}": {{ method:', expected)

    def test_generated_sdk_contains_no_untyped_fallbacks(self) -> None:
        generated = GENERATED.read_text(encoding="utf-8")

        self.assertNotIn(": any", generated)
        self.assertNotIn(": unknown", generated)
        self.assertIn("export type JsonValue =", generated)
        self.assertIn("export interface components", generated)
        self.assertIn("export interface operations", generated)

    def test_web_client_uses_generated_operations_for_api_calls(self) -> None:
        client = (ROOT / "web" / "src" / "api" / "client.ts").read_text(
            encoding="utf-8"
        )
        generated_client = (
            ROOT / "web" / "src" / "api" / "generated-client.ts"
        ).read_text(encoding="utf-8")

        self.assertNotIn('"/api/v1/', client)
        self.assertNotIn("`/api/v1/", client)
        self.assertIn('generatedRequest("create_task"', client)
        self.assertIn('generatedRequest("upload_file"', client)
        self.assertIn('generatedRequest("list_workers"', client)
        self.assertIn('generatedRequest("list_pipelines"', client)
        self.assertIn("export class ParserServeClient", generated_client)
        self.assertNotIn("useConnectionStore", generated_client)
