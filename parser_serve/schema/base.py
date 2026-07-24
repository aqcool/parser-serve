"""Base classes and JSON-compatible values for API contracts."""

from __future__ import annotations

from typing import Annotated, TypeAliasType

from pydantic import BaseModel, ConfigDict, Field, GetJsonSchemaHandler
from pydantic.json_schema import JsonSchemaValue
from pydantic_core import CoreSchema


JsonValue = TypeAliasType(
    "JsonValue",
    Annotated[str, Field(strict=True)]
    | Annotated[int, Field(strict=True)]
    | Annotated[float, Field(strict=True, allow_inf_nan=False)]
    | Annotated[bool, Field(strict=True)]
    | None
    | Annotated[list["JsonValue"], Field(strict=True)]
    | Annotated[dict[str, "JsonValue"], Field(strict=True)],
)

_FIELD_DESCRIPTIONS = {
    "request_id": "Correlation identifier shared by the response body and X-Request-ID header.",
    "data": "Typed response payload.",
    "items": "Typed resources returned on the current page.",
    "page": "Cursor pagination metadata for the current result set.",
    "next_cursor": "Opaque cursor for the next page, or null when no page remains.",
    "has_more": "Whether another page is available after the current page.",
    "type": "Discriminator identifying the concrete variant of this object.",
    "schema_version": "Version of the serialized Parser Serve contract.",
    "message": "Human-readable diagnostic text; clients must not branch on this value.",
    "retryable": "Whether the same operation may be retried after backoff.",
    "field_violations": "Request fields that failed validation.",
    "context": "Additional JSON-compatible diagnostic context.",
    "metadata": "JSON-compatible metadata associated with this resource.",
    "labels": "Operator-defined labels used for filtering or scheduling.",
    "parameters": "Typed execution parameters passed to the selected Backend.",
    "source": "Input source to parse.",
    "options": "Task-level parsing and routing options.",
    "error": "Typed failure detail, or null when the operation has not failed.",
    "result": "Typed parsing result produced by the task or Stage.",
    "status": "Current lifecycle status of this resource.",
    "name": "Human-readable resource name.",
    "version": "Contract, resource, or implementation version.",
    "url": "Absolute HTTP or HTTPS URL.",
    "mime_type": "Canonical Internet media type for the content.",
    "media_category": "High-level category of the input content.",
    "sort_by": "Field used to order the result set.",
    "sort_direction": "Ascending or descending result ordering.",
    "limit": "Maximum number of resources returned in one page.",
    "cursor": "Opaque cursor returned by the preceding page.",
}

_FIELD_EXAMPLES: dict[str, object] = {
    "request_id": "req_01J00000000000000000000000",
    "task_id": "task_01J00000000000000000000000",
    "stage_id": "stage_01J00000000000000000000000",
    "worker_id": "worker_01J00000000000000000000000",
    "backend_id": "backend_01J00000000000000000000000",
    "pipeline_id": "pipeline_01J00000000000000000000000",
    "artifact_id": "artifact_01J00000000000000000000000",
    "file_id": "file_01J00000000000000000000000",
    "event_id": "event_01J00000000000000000000000",
    "api_key_id": "key_01J00000000000000000000000",
    "delivery_id": "delivery_01J00000000000000000000000",
    "attempt_id": "attempt_01J00000000000000000000000",
    "schema_version": "1.0",
    "mime_type": "application/pdf",
    "progress_percent": 50.0,
}


def contract_field_description(name: str, schema: JsonSchemaValue) -> str:
    if description := _FIELD_DESCRIPTIONS.get(name):
        return description
    words = name.replace("_", " ")
    if name.endswith("_id"):
        return f"Stable unique identifier for the {words.removesuffix(' id')} resource."
    if name.endswith("_at"):
        return f"UTC timestamp when {words.removesuffix(' at')} occurred."
    if name.endswith("_bytes"):
        return f"{words.capitalize()}, measured in bytes."
    if name.endswith("_seconds"):
        return f"{words.capitalize()}, measured in seconds."
    if name.endswith("_percent"):
        return f"{words.capitalize()} in the inclusive range from 0 to 100."
    if name.startswith(("is_", "has_", "allow_", "include_", "enabled")):
        return f"Whether {words}."
    if schema.get("type") == "array":
        return f"Ordered {words} values defined by this contract."
    return f"{words.capitalize()} defined by this contract."


def contract_field_example(name: str) -> object | None:
    return _FIELD_EXAMPLES.get(name)


class StrictSchema(BaseModel):
    """Base model for every external Parser Serve contract."""

    model_config = ConfigDict(
        extra="forbid",
        strict=False,
        validate_assignment=True,
        validate_default=True,
        use_enum_values=False,
    )

    @classmethod
    def __get_pydantic_json_schema__(
        cls,
        core_schema: CoreSchema,
        handler: GetJsonSchemaHandler,
    ) -> JsonSchemaValue:
        schema = handler(core_schema)
        properties = schema.get("properties")
        if not isinstance(properties, dict):
            return schema
        for name, property_schema in properties.items():
            if not isinstance(property_schema, dict):
                continue
            property_schema.setdefault(
                "description",
                contract_field_description(name, property_schema),
            )
            if example := contract_field_example(name):
                property_schema.setdefault("examples", [example])
        return schema


__all__ = [
    "JsonValue",
    "StrictSchema",
    "contract_field_description",
    "contract_field_example",
]
