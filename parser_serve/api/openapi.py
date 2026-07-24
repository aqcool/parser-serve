"""OpenAPI annotations for parameters that FastAPI builds outside Pydantic models."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastapi import FastAPI

from ..schema.base import contract_field_description, contract_field_example


_PARAMETER_DESCRIPTIONS = {
    "Idempotency-Key": "Stable key reused when retrying the same create request.",
    "Last-Event-ID": "Last processed Event ID used to resume an SSE stream.",
    "created_after": "Return resources created at or after this UTC timestamp.",
    "created_before": "Return resources created before this UTC timestamp.",
    "start_time": "Inclusive UTC start of the dashboard aggregation window.",
    "end_time": "Exclusive UTC end of the dashboard aggregation window.",
    "name_contains": "Case-insensitive substring matched against resource names.",
    "statuses": "Return resources whose status is one of these values.",
    "runtimes": "Return resources supporting one of these hardware runtimes.",
    "types": "Return resources or events whose type is one of these values.",
    "kinds": "Return API Keys whose kind is one of these values.",
    "labels": "Require every supplied Worker label key and value.",
    "last_event_id": "Return events strictly after this Event ID.",
}


def annotate_openapi_contract(schema: dict[str, Any]) -> dict[str, Any]:
    for path_item in schema.get("paths", {}).values():
        if not isinstance(path_item, dict):
            continue
        for operation in path_item.values():
            if not isinstance(operation, dict):
                continue
            summary = operation.get("summary")
            if summary and not operation.get("description"):
                operation["description"] = f"{summary}."
            for parameter in operation.get("parameters", []):
                if not isinstance(parameter, dict):
                    continue
                name = str(parameter.get("name", "parameter"))
                parameter_schema = parameter.get("schema", {})
                description = _PARAMETER_DESCRIPTIONS.get(name)
                if description is None:
                    description = contract_field_description(
                        name.casefold().replace("-", "_"),
                        parameter_schema if isinstance(parameter_schema, dict) else {},
                    )
                parameter.setdefault("description", description)
                example = contract_field_example(name.casefold().replace("-", "_"))
                if example is not None:
                    parameter.setdefault("example", example)
    return schema


def install_openapi_annotations(application: FastAPI) -> None:
    default_openapi: Callable[[], dict[str, Any]] = application.openapi

    def annotated_openapi() -> dict[str, Any]:
        if application.openapi_schema is None:
            application.openapi_schema = annotate_openapi_contract(default_openapi())
        return application.openapi_schema

    application.openapi = annotated_openapi


__all__ = ["annotate_openapi_contract", "install_openapi_annotations"]
