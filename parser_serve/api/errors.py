"""Typed API exceptions and FastAPI exception handlers."""

from __future__ import annotations

import logging

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette import status

from ..schema.base import JsonValue
from ..schema.error import (
    ErrorCode,
    ErrorDetail,
    ErrorResponse,
    FieldViolation,
)
from .request_id import request_id_for


class ApiError(Exception):
    def __init__(
        self,
        *,
        status_code: int,
        code: ErrorCode,
        message: str,
        retryable: bool = False,
        context: dict[str, JsonValue] | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.retryable = retryable
        self.context = context or {}


def _error_response(
    request: Request,
    *,
    status_code: int,
    detail: ErrorDetail,
) -> JSONResponse:
    response = ErrorResponse(
        request_id=request_id_for(request),
        error=detail,
    )
    return JSONResponse(
        status_code=status_code,
        content=response.model_dump(mode="json"),
    )


async def api_error_handler(request: Request, exc: Exception) -> JSONResponse:
    if not isinstance(exc, ApiError):
        raise exc
    return _error_response(
        request,
        status_code=exc.status_code,
        detail=ErrorDetail(
            code=exc.code,
            message=exc.message,
            retryable=exc.retryable,
            context=exc.context,
        ),
    )


async def validation_error_handler(
    request: Request,
    exc: Exception,
) -> JSONResponse:
    if not isinstance(exc, RequestValidationError):
        raise exc
    violations = [
        FieldViolation(
            field=".".join(str(part) for part in error["loc"]),
            reason=str(error["msg"]),
        )
        for error in exc.errors()
    ]
    return _error_response(
        request,
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        detail=ErrorDetail(
            code=ErrorCode.VALIDATION_ERROR,
            message="The request is invalid",
            field_violations=violations,
        ),
    )


async def unhandled_error_handler(request: Request, exc: Exception) -> JSONResponse:
    logger = getattr(
        request.app.state,
        "logger",
        logging.getLogger("parser_serve.api"),
    )
    logger.exception(
        "Unhandled API error",
        exc_info=exc,
        extra={"request_id": request_id_for(request)},
    )
    return _error_response(
        request,
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail=ErrorDetail(
            code=ErrorCode.INTERNAL_ERROR,
            message="An internal error occurred",
            retryable=False,
        ),
    )


__all__ = [
    "ApiError",
    "api_error_handler",
    "unhandled_error_handler",
    "validation_error_handler",
]
