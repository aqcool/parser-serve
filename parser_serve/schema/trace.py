"""W3C Trace Context carried across persisted asynchronous work."""

from __future__ import annotations

from typing import Annotated

from pydantic import Field, model_validator

from .base import StrictSchema


class TraceContext(StrictSchema):
    traceparent: Annotated[
        str,
        Field(
            pattern=(r"^[0-9a-f]{2}-[0-9a-f]{32}-[0-9a-f]{16}-[0-9a-f]{2}$"),
            strict=True,
        ),
    ]
    tracestate: (
        Annotated[
            str,
            Field(min_length=1, max_length=512, strict=True),
        ]
        | None
    ) = None

    @model_validator(mode="after")
    def validate_identifiers(self) -> TraceContext:
        _, trace_id, parent_id, _ = self.traceparent.split("-")
        if trace_id == "0" * 32 or parent_id == "0" * 16:
            raise ValueError("traceparent identifiers cannot be all zero")
        return self


__all__ = ["TraceContext"]
