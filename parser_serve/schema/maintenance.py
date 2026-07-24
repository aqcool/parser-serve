"""Retention maintenance request and response contracts."""

from __future__ import annotations

from typing import Annotated

from pydantic import Field

from .base import StrictSchema
from .common import ApiResponse, StrictBool, UTCDateTime


class RunRetentionRequest(StrictSchema):
    dry_run: StrictBool = False
    maximum_records: Annotated[int, Field(ge=1, le=10_000, strict=True)] = 500


class RetentionRunData(StrictSchema):
    dry_run: StrictBool
    cutoff_time: UTCDateTime
    uploaded_files_selected: Annotated[int, Field(ge=0, strict=True)]
    uploaded_files_skipped_active: Annotated[int, Field(ge=0, strict=True)]
    artifacts_selected: Annotated[int, Field(ge=0, strict=True)]
    artifacts_skipped_active: Annotated[int, Field(ge=0, strict=True)]
    events_selected: Annotated[int, Field(ge=0, strict=True)]
    storage_delete_failures: Annotated[int, Field(ge=0, strict=True)]


RetentionRunResponse = ApiResponse[RetentionRunData]


__all__ = [
    "RetentionRunData",
    "RetentionRunResponse",
    "RunRetentionRequest",
]
