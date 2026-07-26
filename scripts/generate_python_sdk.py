"""Generate the fully typed Python SDK contract from committed OpenAPI."""

from __future__ import annotations

import argparse
import json
import keyword
import re
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
OPENAPI = ROOT / "web" / "openapi.json"
TARGET = ROOT / "parser_serve" / "sdk" / "generated.py"
HTTP_METHODS = {"get", "post", "put", "patch", "delete", "options", "head"}
IDENTIFIER_PART = re.compile(r"[^A-Za-z0-9_]")


def _identifier(value: str) -> str:
    normalized = IDENTIFIER_PART.sub("_", value)
    if not normalized or normalized[0].isdigit():
        normalized = f"_{normalized}"
    if keyword.iskeyword(normalized):
        normalized += "_"
    return normalized


def _type_name(value: str) -> str:
    return _identifier(value.replace("-", "_"))


def _operation_type_name(operation_id: str) -> str:
    return "".join(part.capitalize() for part in operation_id.split("_"))


def _literal(value: object) -> str:
    return repr(value)


def _reference(reference: str) -> str:
    prefix = "#/components/schemas/"
    if not reference.startswith(prefix):
        raise ValueError(f"unsupported OpenAPI reference: {reference}")
    return _type_name(reference.removeprefix(prefix))


def _schema_type(schema: object) -> str:
    if not isinstance(schema, dict) or not schema:
        return "JsonValue"
    if reference := schema.get("$ref"):
        return _reference(str(reference))
    if "const" in schema:
        return f"Literal[{_literal(schema['const'])}]"
    if enum := schema.get("enum"):
        return f"Literal[{', '.join(_literal(value) for value in enum)}]"
    for keyword_name in ("oneOf", "anyOf"):
        if variants := schema.get(keyword_name):
            return " | ".join(f"({_schema_type(variant)})" for variant in variants)
    schema_type = schema.get("type")
    if isinstance(schema_type, list):
        return " | ".join(
            "None" if item == "null" else _schema_type({**schema, "type": item})
            for item in schema_type
        )
    if schema_type == "string":
        return (
            "UploadFile"
            if schema.get("format") == "binary"
            or schema.get("contentMediaType") == "application/octet-stream"
            else "str"
        )
    if schema_type == "integer":
        return "int"
    if schema_type == "number":
        return "float"
    if schema_type == "boolean":
        return "bool"
    if schema_type == "null":
        return "None"
    if schema_type == "array":
        return f"list[{_schema_type(schema.get('items', {}))}]"
    if schema_type == "object" or "properties" in schema:
        additional = schema.get("additionalProperties")
        if isinstance(additional, dict):
            return f"dict[str, {_schema_type(additional)}]"
        if additional is True:
            return "dict[str, JsonValue]"
        return "dict[str, JsonValue]"
    return "JsonValue"


def _typed_dict(
    name: str,
    properties: dict[str, object],
    required: set[str],
) -> list[str]:
    if not properties:
        return [f"class {name}(TypedDict):", "    pass", ""]
    if all(_identifier(key) == key for key in properties):
        lines = [f"class {name}(TypedDict):"]
        for key, schema in properties.items():
            rendered = _schema_type(schema)
            if key not in required:
                rendered = f"NotRequired[{rendered}]"
            lines.append(f"    {key}: {rendered}")
        lines.append("")
        return lines
    fields = []
    for key, schema in properties.items():
        rendered = _schema_type(schema)
        wrapper = "typing.Required" if key in required else "typing.NotRequired"
        fields.append(f"    {key!r}: {wrapper}[{rendered}],")
    return [
        f"{name} = TypedDict(",
        f"    {name!r},",
        "    {",
        *fields,
        "    },",
        ")",
        "",
    ]


def _component(name: str, schema: object) -> list[str]:
    type_name = _type_name(name)
    if not isinstance(schema, dict):
        return [f"type {type_name} = JsonValue", ""]
    properties = schema.get("properties")
    if isinstance(properties, dict):
        return _typed_dict(
            type_name,
            properties,
            {str(item) for item in schema.get("required", [])},
        )
    return [f"type {type_name} = {_schema_type(schema)}", ""]


def _parameters(
    operation_name: str,
    parameters: list[object],
    location: str,
) -> tuple[str, list[str], bool]:
    suffix = {"path": "Path", "query": "Query", "header": "Headers"}[location]
    name = f"{operation_name}{suffix}"
    selected = [
        parameter
        for parameter in parameters
        if isinstance(parameter, dict) and parameter.get("in") == location
    ]
    properties = {
        str(parameter["name"]): parameter.get("schema", {}) for parameter in selected
    }
    required = {
        str(parameter["name"])
        for parameter in selected
        if parameter.get("required") is True
    }
    return name, _typed_dict(name, properties, required), bool(required)


def _request_body(
    operation_name: str,
    operation: dict[str, Any],
) -> tuple[str, list[str], str | None, bool]:
    name = f"{operation_name}Body"
    body = operation.get("requestBody")
    if not isinstance(body, dict):
        return name, [f"type {name} = None", ""], None, False
    content = body.get("content", {})
    if not isinstance(content, dict):
        return name, [f"type {name} = JsonValue", ""], None, bool(body.get("required"))
    for media_type in (
        "application/json",
        "multipart/form-data",
        "application/octet-stream",
    ):
        media = content.get(media_type)
        if isinstance(media, dict):
            return (
                name,
                [f"type {name} = {_schema_type(media.get('schema', {}))}", ""],
                media_type,
                bool(body.get("required")),
            )
    return name, [f"type {name} = JsonValue", ""], None, bool(body.get("required"))


def _response(
    operation_name: str,
    operation: dict[str, Any],
) -> tuple[str, list[str], str]:
    name = f"{operation_name}Response"
    responses = operation.get("responses", {})
    success = (
        next(
            (
                response
                for status, response in sorted(responses.items())
                if str(status).startswith("2")
            ),
            None,
        )
        if isinstance(responses, dict)
        else None
    )
    if not isinstance(success, dict):
        return name, [f"type {name} = None", ""], "none"
    content = success.get("content", {})
    if not isinstance(content, dict) or not content:
        return name, [f"type {name} = None", ""], "none"
    media = content.get("application/json")
    if isinstance(media, dict):
        return (
            name,
            [f"type {name} = {_schema_type(media.get('schema', {}))}", ""],
            "json",
        )
    if "application/octet-stream" in content:
        return name, [f"type {name} = bytes", ""], "bytes"
    if "text/event-stream" in content:
        return name, [f"type {name} = Iterator[bytes]", ""], "stream"
    if "text/plain" in content:
        return name, [f"type {name} = str", ""], "text"
    return name, [f"type {name} = bytes", ""], "bytes"


def _argument(name: str, type_name: str, required: bool) -> str:
    return f"        {name}: {type_name}{',' if required else ' | None = None,'}"


def _sync_method(
    operation_id: str,
    operation_name: str,
    *,
    path_required: bool,
    query_required: bool,
    headers_required: bool,
    body_required: bool,
    body_media_type: str | None,
    response_kind: str,
) -> list[str]:
    lines = [
        f"    def call_{operation_id}(",
        "        self,",
        "        *,",
        _argument("path", f"{operation_name}Path", path_required),
        _argument("query", f"{operation_name}Query", query_required),
        _argument("headers", f"{operation_name}Headers", headers_required),
        _argument("body", f"{operation_name}Body", body_required),
        f"    ) -> {operation_name}Response:",
    ]
    arguments = [
        repr(operation_id),
        "path=path",
        "query=query",
        "headers=headers",
        "body=body",
        f"body_media_type={body_media_type!r}",
    ]
    call = {
        "json": f"self._generated_json({', '.join(arguments)}, response_type={operation_name}Response)",
        "bytes": f"self._generated_bytes({', '.join(arguments)})",
        "text": f"self._generated_text({', '.join(arguments)})",
        "stream": f"self._generated_stream({', '.join(arguments)})",
        "none": f"self._generated_none({', '.join(arguments)})",
    }[response_kind]
    lines.extend([f"        return cast({operation_name}Response, {call})", ""])
    return lines


def _async_method(
    operation_id: str,
    operation_name: str,
    *,
    path_required: bool,
    query_required: bool,
    headers_required: bool,
    body_required: bool,
    body_media_type: str | None,
    response_kind: str,
) -> list[str]:
    is_stream = response_kind == "stream"
    lines = [
        f"    {'def' if is_stream else 'async def'} call_{operation_id}(",
        "        self,",
        "        *,",
        _argument("path", f"{operation_name}Path", path_required),
        _argument("query", f"{operation_name}Query", query_required),
        _argument("headers", f"{operation_name}Headers", headers_required),
        _argument("body", f"{operation_name}Body", body_required),
        f"    ) -> {'AsyncIterator[bytes]' if is_stream else operation_name + 'Response'}:",
    ]
    arguments = [
        repr(operation_id),
        "path=path",
        "query=query",
        "headers=headers",
        "body=body",
        f"body_media_type={body_media_type!r}",
    ]
    if is_stream:
        call = f"self._generated_stream({', '.join(arguments)})"
    else:
        primitive = {
            "json": "_generated_json",
            "bytes": "_generated_bytes",
            "text": "_generated_text",
            "none": "_generated_none",
        }[response_kind]
        extra = (
            f", response_type={operation_name}Response"
            if response_kind == "json"
            else ""
        )
        call = f"await self.{primitive}({', '.join(arguments)}{extra})"
    lines.extend(
        [
            f"        return cast({'AsyncIterator[bytes]' if is_stream else operation_name + 'Response'}, {call})",
            "",
        ]
    )
    return lines


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
    operation_ids = [operation[0] for operation in operations]
    if len(operation_ids) != len(set(operation_ids)):
        raise ValueError("OpenAPI operationId values must be unique")

    lines = [
        '"""Generated Python wire types, operations, and clients. Do not edit."""',
        "# fmt: off",
        "",
        "from __future__ import annotations",
        "",
        "from collections.abc import AsyncIterator, Iterator",
        "from dataclasses import dataclass",
        "import typing",
        "from typing import BinaryIO, Literal, NotRequired, TypedDict, cast",
        "",
        "",
        "type JsonValue = (",
        "    str | int | float | bool | None | list[JsonValue] | dict[str, JsonValue]",
        ")",
        "type UploadContent = bytes | BinaryIO",
        "type UploadFile = tuple[str, UploadContent, str]",
        "",
    ]
    for name, schema in sorted(schemas.items()):
        lines.extend(_component(name, schema))

    operation_metadata: list[dict[str, object]] = []
    for operation_id, _, _, operation in sorted(operations):
        operation_name = _operation_type_name(operation_id)
        parameters = operation.get("parameters", [])
        if not isinstance(parameters, list):
            parameters = []
        _, path_lines, path_required = _parameters(operation_name, parameters, "path")
        _, query_lines, query_required = _parameters(
            operation_name, parameters, "query"
        )
        _, headers_lines, headers_required = _parameters(
            operation_name, parameters, "header"
        )
        _, body_lines, body_media_type, body_required = _request_body(
            operation_name, operation
        )
        _, response_lines, response_kind = _response(operation_name, operation)
        lines.extend(path_lines)
        lines.extend(query_lines)
        lines.extend(headers_lines)
        lines.extend(body_lines)
        lines.extend(response_lines)
        operation_metadata.append(
            {
                "operation_id": operation_id,
                "operation_name": operation_name,
                "path_required": path_required,
                "query_required": query_required,
                "headers_required": headers_required,
                "body_required": body_required,
                "body_media_type": body_media_type,
                "response_kind": response_kind,
            }
        )

    lines.extend(
        [
            "OperationId = Literal[",
            *(f"    {value!r}," for value in sorted(operation_ids)),
            "]",
            "HttpMethod = Literal[",
            '    "DELETE",',
            '    "GET",',
            '    "HEAD",',
            '    "OPTIONS",',
            '    "PATCH",',
            '    "POST",',
            '    "PUT",',
            "]",
            "",
            "",
            "@dataclass(frozen=True, slots=True)",
            "class OperationSpec:",
            "    method: HttpMethod",
            "    path: str",
            "",
            "",
            "OPERATION_SPECS: dict[OperationId, OperationSpec] = {",
        ]
    )
    for operation_id, method, path, _ in sorted(operations):
        lines.append(f"    {operation_id!r}: OperationSpec({method!r}, {path!r}),")
    lines.extend(
        [
            "}",
            "",
            "",
            "class GeneratedSyncClientMixin:",
            '    """All OpenAPI operations with operation-specific wire types."""',
            "",
            "    def _generated_json(",
            "        self, operation_id: OperationId, *, path: object, query: object,",
            "        headers: object, body: object, body_media_type: str | None,",
            "        response_type: object,",
            "    ) -> object:",
            "        raise NotImplementedError",
            "",
            "    def _generated_bytes(",
            "        self, operation_id: OperationId, *, path: object, query: object,",
            "        headers: object, body: object, body_media_type: str | None,",
            "    ) -> bytes:",
            "        raise NotImplementedError",
            "",
            "    def _generated_text(",
            "        self, operation_id: OperationId, *, path: object, query: object,",
            "        headers: object, body: object, body_media_type: str | None,",
            "    ) -> str:",
            "        raise NotImplementedError",
            "",
            "    def _generated_stream(",
            "        self, operation_id: OperationId, *, path: object, query: object,",
            "        headers: object, body: object, body_media_type: str | None,",
            "    ) -> Iterator[bytes]:",
            "        raise NotImplementedError",
            "",
            "    def _generated_none(",
            "        self, operation_id: OperationId, *, path: object, query: object,",
            "        headers: object, body: object, body_media_type: str | None,",
            "    ) -> None:",
            "        raise NotImplementedError",
            "",
        ]
    )
    for metadata in operation_metadata:
        lines.extend(_sync_method(**metadata))  # type: ignore[arg-type]
    lines.extend(
        [
            "class GeneratedAsyncClientMixin:",
            '    """Async variants of every typed OpenAPI operation."""',
            "",
            "    async def _generated_json(",
            "        self, operation_id: OperationId, *, path: object, query: object,",
            "        headers: object, body: object, body_media_type: str | None,",
            "        response_type: object,",
            "    ) -> object:",
            "        raise NotImplementedError",
            "",
            "    async def _generated_bytes(",
            "        self, operation_id: OperationId, *, path: object, query: object,",
            "        headers: object, body: object, body_media_type: str | None,",
            "    ) -> bytes:",
            "        raise NotImplementedError",
            "",
            "    async def _generated_text(",
            "        self, operation_id: OperationId, *, path: object, query: object,",
            "        headers: object, body: object, body_media_type: str | None,",
            "    ) -> str:",
            "        raise NotImplementedError",
            "",
            "    def _generated_stream(",
            "        self, operation_id: OperationId, *, path: object, query: object,",
            "        headers: object, body: object, body_media_type: str | None,",
            "    ) -> AsyncIterator[bytes]:",
            "        raise NotImplementedError",
            "",
            "    async def _generated_none(",
            "        self, operation_id: OperationId, *, path: object, query: object,",
            "        headers: object, body: object, body_media_type: str | None,",
            "    ) -> None:",
            "        raise NotImplementedError",
            "",
        ]
    )
    for metadata in operation_metadata:
        lines.extend(_async_method(**metadata))  # type: ignore[arg-type]
    lines.extend(
        [
            "__all__ = [",
            '    "GeneratedAsyncClientMixin",',
            '    "GeneratedSyncClientMixin",',
            '    "HttpMethod",',
            '    "OPERATION_SPECS",',
            '    "OperationId",',
            '    "OperationSpec",',
            '    "UploadContent",',
            '    "UploadFile",',
            *(
                f"    {(_operation_type_name(value) + suffix)!r},"
                for value in sorted(operation_ids)
                for suffix in ("Body", "Headers", "Path", "Query", "Response")
            ),
            "]",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--check",
        action="store_true",
        help="fail when the generated file differs from the OpenAPI contract",
    )
    arguments = parser.parse_args()
    generated = generate(json.loads(OPENAPI.read_text(encoding="utf-8")))
    if arguments.check:
        if not TARGET.exists() or TARGET.read_text(encoding="utf-8") != generated:
            raise SystemExit(
                "Python SDK is stale; run python -m scripts.generate_python_sdk"
            )
        return
    TARGET.parent.mkdir(parents=True, exist_ok=True)
    TARGET.write_text(generated, encoding="utf-8")


if __name__ == "__main__":
    main()
