from __future__ import annotations

import json
import unittest
from pathlib import Path

from parser_serve.api import create_app


ROOT = Path(__file__).resolve().parents[1]
SNAPSHOT = ROOT / "web" / "openapi.json"


def _walk(value: object, *, path: str = "$") -> list[tuple[str, object]]:
    entries = [(path, value)]
    if isinstance(value, dict):
        for key, item in value.items():
            entries.extend(_walk(item, path=f"{path}.{key}"))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            entries.extend(_walk(item, path=f"{path}[{index}]"))
    return entries


class OpenApiSnapshotTests(unittest.TestCase):
    def test_committed_snapshot_matches_application_contract(self) -> None:
        committed = json.loads(SNAPSHOT.read_text(encoding="utf-8"))

        self.assertEqual(committed, create_app().openapi())

    def test_component_schemas_have_no_unconstrained_objects(self) -> None:
        schemas = create_app().openapi()["components"]["schemas"]
        entries = _walk(schemas)

        empty_schema_paths = [path for path, value in entries if value == {}]
        open_object_paths = [
            path
            for path, value in entries
            if isinstance(value, dict) and value.get("additionalProperties") is True
        ]
        self.assertEqual(empty_schema_paths, [])
        self.assertEqual(open_object_paths, [])

    def test_every_component_property_has_a_description(self) -> None:
        schemas = create_app().openapi()["components"]["schemas"]
        missing: list[str] = []
        for schema_name, schema in schemas.items():
            properties = schema.get("properties", {})
            for property_name, property_schema in properties.items():
                if not property_schema.get("description"):
                    missing.append(f"{schema_name}.{property_name}")

        self.assertEqual(missing, [])

    def test_core_contract_fields_include_examples_and_ranges(self) -> None:
        schemas = create_app().openapi()["components"]["schemas"]
        task_id = schemas["TaskDetail"]["properties"]["task_id"]
        progress = schemas["StageDetail"]["properties"]["progress_percent"]

        self.assertEqual(
            task_id["examples"],
            ["task_01J00000000000000000000000"],
        )
        self.assertEqual(progress["minimum"], 0.0)
        self.assertEqual(progress["maximum"], 100.0)
        self.assertEqual(progress["examples"], [50.0])

    def test_operations_and_parameters_have_descriptions(self) -> None:
        paths = create_app().openapi()["paths"]
        missing_operations: list[str] = []
        missing_parameters: list[str] = []
        methods = {"get", "post", "put", "patch", "delete", "options", "head"}
        for path, path_item in paths.items():
            for method, operation in path_item.items():
                if method not in methods:
                    continue
                if not operation.get("description"):
                    missing_operations.append(f"{method.upper()} {path}")
                for parameter in operation.get("parameters", []):
                    if not parameter.get("description"):
                        missing_parameters.append(
                            f"{method.upper()} {path} {parameter.get('name')}"
                        )

        self.assertEqual(missing_operations, [])
        self.assertEqual(missing_parameters, [])


if __name__ == "__main__":
    unittest.main()
