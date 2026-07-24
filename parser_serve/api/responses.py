"""Helpers for creating typed response envelopes."""

from __future__ import annotations

from typing import TypeVar

from fastapi import Request

from ..schema.common import ApiResponse
from ..schema.base import StrictSchema
from .request_id import request_id_for


DataT = TypeVar("DataT", bound=StrictSchema)


def api_response(request: Request, data: DataT) -> ApiResponse[DataT]:
    return ApiResponse[DataT](
        request_id=request_id_for(request),
        data=data,
    )


__all__ = ["api_response"]
