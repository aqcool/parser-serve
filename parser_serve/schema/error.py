"""Typed error responses shared by every external interface."""

from __future__ import annotations

from enum import StrEnum

from pydantic import Field

from .base import JsonValue, StrictSchema
from .common import NonEmptyStr, RequestId, StrictBool


class ErrorCode(StrEnum):
    VALIDATION_ERROR = "VALIDATION_ERROR"
    AUTHENTICATION_FAILED = "AUTHENTICATION_FAILED"
    API_KEY_EXPIRED = "API_KEY_EXPIRED"
    NOT_FOUND = "NOT_FOUND"
    CONFLICT = "CONFLICT"
    UNSUPPORTED_MEDIA_TYPE = "UNSUPPORTED_MEDIA_TYPE"
    FILE_TOO_LARGE = "FILE_TOO_LARGE"
    TASK_NOT_CANCELLABLE = "TASK_NOT_CANCELLABLE"
    WORKER_NOT_AVAILABLE = "WORKER_NOT_AVAILABLE"
    BACKEND_NOT_AVAILABLE = "BACKEND_NOT_AVAILABLE"
    TIMEOUT = "TIMEOUT"
    RATE_LIMITED = "RATE_LIMITED"
    DEPENDENCY_UNAVAILABLE = "DEPENDENCY_UNAVAILABLE"
    INTERNAL_ERROR = "INTERNAL_ERROR"


class FieldViolation(StrictSchema):
    field: NonEmptyStr
    reason: NonEmptyStr


class ErrorDetail(StrictSchema):
    code: ErrorCode
    message: NonEmptyStr
    retryable: StrictBool = False
    field_violations: list[FieldViolation] = Field(default_factory=list)
    context: dict[str, JsonValue] = Field(default_factory=dict)


class ErrorResponse(StrictSchema):
    request_id: RequestId
    error: ErrorDetail


__all__ = [
    "ErrorCode",
    "ErrorDetail",
    "ErrorResponse",
    "FieldViolation",
]
