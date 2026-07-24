"""Generate the Python SDK operation table from the committed OpenAPI contract."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
OPENAPI = ROOT / "web" / "openapi.json"
TARGET = ROOT / "parser_serve" / "sdk" / "generated.py"
HTTP_METHODS = {"get", "post", "put", "patch", "delete", "options", "head"}


def generate(specification: dict[str, Any]) -> str:
    operations: list[tuple[str, str, str]] = []
    for path, path_item in specification["paths"].items():
        for method, operation in path_item.items():
            if method not in HTTP_METHODS or not isinstance(operation, dict):
                continue
            operation_id = operation.get("operationId")
            if not isinstance(operation_id, str) or not operation_id:
                raise ValueError(f"{method.upper()} {path} has no operationId")
            operations.append((operation_id, method.upper(), path))

    operation_ids = [operation[0] for operation in operations]
    if len(operation_ids) != len(set(operation_ids)):
        raise ValueError("OpenAPI operationId values must be unique")

    lines = [
        '"""Generated OpenAPI operation identifiers and routes. Do not edit."""',
        "",
        "from __future__ import annotations",
        "",
        "from dataclasses import dataclass",
        "from typing import Final, Literal",
        "",
        "",
        "OperationId = Literal[",
    ]
    lines.extend(f"    {json.dumps(value)}," for value in sorted(operation_ids))
    lines.extend(
        [
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
            "OPERATION_SPECS: Final[dict[OperationId, OperationSpec]] = {",
        ]
    )
    for operation_id, method, path in sorted(operations):
        lines.extend(
            [
                f"    {json.dumps(operation_id)}: OperationSpec(",
                f"        {json.dumps(method)},",
                f"        {json.dumps(path)},",
                "    ),",
            ]
        )
    lines.extend(
        [
            "}",
            "",
            "",
            '__all__ = ["OPERATION_SPECS", "HttpMethod", "OperationId", "OperationSpec"]',
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
