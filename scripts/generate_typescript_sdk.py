"""Generate the dependency-free TypeScript HTTP contract from OpenAPI."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
OPENAPI = ROOT / "web" / "openapi.json"
TARGET = ROOT / "web" / "src" / "api" / "generated.ts"
HTTP_METHODS = {"get", "post", "put", "patch", "delete", "options", "head"}
IDENTIFIER = re.compile(r"^[A-Za-z_$][A-Za-z0-9_$]*$")


def _property(name: str) -> str:
    return name if IDENTIFIER.fullmatch(name) else json.dumps(name)


def _literal(value: object) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    return json.dumps(value, ensure_ascii=False)


def _reference(reference: str) -> str:
    prefix = "#/components/schemas/"
    if not reference.startswith(prefix):
        raise ValueError(f"unsupported OpenAPI reference: {reference}")
    name = reference.removeprefix(prefix)
    if name in {"JsonValue-Input", "JsonValue-Output"}:
        return "JsonValue"
    return f'components["schemas"][{json.dumps(name)}]'


def _schema_type(schema: object) -> str:
    if not isinstance(schema, dict) or not schema:
        return "unknown"
    if reference := schema.get("$ref"):
        return _reference(str(reference))
    if "const" in schema:
        return _literal(schema["const"])
    if enum := schema.get("enum"):
        return " | ".join(_literal(value) for value in enum)
    for keyword, separator in (("oneOf", " | "), ("anyOf", " | "), ("allOf", " & ")):
        if variants := schema.get(keyword):
            return separator.join(f"({_schema_type(variant)})" for variant in variants)
    schema_type = schema.get("type")
    if isinstance(schema_type, list):
        return " | ".join(
            "null" if item == "null" else _schema_type({**schema, "type": item})
            for item in schema_type
        )
    if schema_type == "string":
        return "string"
    if schema_type in {"integer", "number"}:
        return "number"
    if schema_type == "boolean":
        return "boolean"
    if schema_type == "null":
        return "null"
    if schema_type == "array":
        return f"Array<{_schema_type(schema.get('items', {}))}>"
    if schema_type == "object" or "properties" in schema:
        properties = schema.get("properties", {})
        required = set(schema.get("required", []))
        lines = ["{"]
        if isinstance(properties, dict):
            for name, value in properties.items():
                optional = "" if name in required else "?"
                lines.append(
                    f"  {_property(str(name))}{optional}: {_schema_type(value)}"
                )
        additional = schema.get("additionalProperties")
        if isinstance(additional, dict):
            lines.append(f"  [key: string]: {_schema_type(additional)}")
        elif additional is True:
            lines.append("  [key: string]: unknown")
        lines.append("}")
        return "\n".join(lines)
    return "unknown"


def _parameter_group(parameters: list[object], location: str) -> str:
    selected = [
        parameter
        for parameter in parameters
        if isinstance(parameter, dict) and parameter.get("in") == location
    ]
    if not selected:
        return "{}"
    lines = ["{"]
    for parameter in selected:
        name = str(parameter["name"])
        optional = "" if parameter.get("required") else "?"
        lines.append(
            f"  {_property(name)}{optional}: "
            f"{_schema_type(parameter.get('schema', {}))}"
        )
    lines.append("}")
    return "\n".join(lines)


def _request_body(operation: dict[str, Any]) -> str:
    body = operation.get("requestBody")
    if not isinstance(body, dict):
        return "undefined"
    content = body.get("content", {})
    if not isinstance(content, dict):
        return "unknown"
    for media_type in (
        "application/json",
        "multipart/form-data",
        "application/octet-stream",
    ):
        media = content.get(media_type)
        if isinstance(media, dict):
            return _schema_type(media.get("schema", {}))
    return "unknown"


def _response(operation: dict[str, Any]) -> str:
    responses = operation.get("responses", {})
    if not isinstance(responses, dict):
        return "unknown"
    success = next(
        (
            response
            for status, response in sorted(responses.items())
            if str(status).startswith("2")
        ),
        None,
    )
    if not isinstance(success, dict):
        return "unknown"
    content = success.get("content", {})
    if not isinstance(content, dict) or not content:
        return "undefined"
    for media_type in ("application/json", "text/event-stream"):
        media = content.get(media_type)
        if isinstance(media, dict):
            return _schema_type(media.get("schema", {}))
    return "Blob"


def generate(specification: dict[str, Any]) -> str:
    schemas = specification["components"]["schemas"]
    operations: list[tuple[str, str, str, dict[str, Any]]] = []
    for path, path_item in specification["paths"].items():
        for method, operation in path_item.items():
            if method not in HTTP_METHODS or not isinstance(operation, dict):
                continue
            operation_id = operation.get("operationId")
            if not isinstance(operation_id, str) or not operation_id:
                raise ValueError(f"{method.upper()} {path} has no operationId")
            operations.append((operation_id, method.upper(), path, operation))
    operation_ids = [item[0] for item in operations]
    if len(operation_ids) != len(set(operation_ids)):
        raise ValueError("OpenAPI operationId values must be unique")

    lines = [
        "/* eslint-disable */",
        "// Generated by scripts/generate_typescript_sdk.py. DO NOT EDIT.",
        "",
        "export type JsonValue =",
        "  | string",
        "  | number",
        "  | boolean",
        "  | null",
        "  | Array<JsonValue>",
        "  | { [key: string]: JsonValue }",
        "",
        "export interface components {",
        "  schemas: {",
    ]
    for name, schema in sorted(schemas.items()):
        rendered = (
            "JsonValue"
            if name in {"JsonValue-Input", "JsonValue-Output"}
            else _schema_type(schema)
        ).replace("\n", "\n    ")
        lines.append(f"    {json.dumps(name)}: {rendered}")
    lines.extend(["  }", "}", "", "export interface operations {"])
    for operation_id, _, _, operation in sorted(operations):
        parameters = operation.get("parameters", [])
        if not isinstance(parameters, list):
            parameters = []
        path_parameters = _parameter_group(parameters, "path").replace("\n", "\n      ")
        query_parameters = _parameter_group(parameters, "query").replace(
            "\n", "\n      "
        )
        header_parameters = _parameter_group(parameters, "header").replace(
            "\n", "\n      "
        )
        request_body = _request_body(operation).replace("\n", "\n    ")
        response = _response(operation).replace("\n", "\n    ")
        lines.extend(
            [
                f"  {json.dumps(operation_id)}: {{",
                "    parameters: {",
                f"      path: {path_parameters}",
                f"      query: {query_parameters}",
                f"      header: {header_parameters}",
                "    }",
                f"    requestBody: {request_body}",
                f"    response: {response}",
                "  }",
            ]
        )
    lines.extend(["}", "", "export const operationSpecs = {"])
    for operation_id, method, path, _ in sorted(operations):
        lines.append(
            f"  {json.dumps(operation_id)}: "
            f"{{ method: {json.dumps(method)}, path: {json.dumps(path)} }},"
        )
    lines.extend(
        [
            "} as const",
            "",
            "export type OperationId = keyof operations",
            "export type OperationResponse<T extends OperationId> = "
            'operations[T]["response"]',
            "export type OperationRequestBody<T extends OperationId> = "
            'operations[T]["requestBody"]',
            "",
        ]
    )
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--check",
        action="store_true",
        help="Fail when the committed generated SDK is stale.",
    )
    arguments = parser.parse_args()
    content = generate(json.loads(OPENAPI.read_text(encoding="utf-8")))
    if arguments.check:
        if not TARGET.is_file() or TARGET.read_text(encoding="utf-8") != content:
            raise SystemExit(
                "generated TypeScript SDK is stale; run "
                "`uv run python -m scripts.generate_typescript_sdk`"
            )
        return
    TARGET.parent.mkdir(parents=True, exist_ok=True)
    TARGET.write_text(content, encoding="utf-8")


if __name__ == "__main__":
    main()
