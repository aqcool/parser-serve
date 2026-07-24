"""Typed contracts for installing the built-in registry catalog."""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated

from pydantic import Field

from .base import StrictSchema
from .common import ApiResponse, BackendId, PipelineId, PositiveVersion, StrictBool
from .pipeline import PipelineStatus, PipelineValidationViolation


class InitializeDefaultsRequest(StrictSchema):
    include_builtin_backends: StrictBool = True
    publish_valid_pipelines: StrictBool = True


class DefaultCatalogAction(StrEnum):
    CREATED = "created"
    PUBLISHED = "published"
    UNCHANGED = "unchanged"
    DRAFT_UNAVAILABLE = "draft_unavailable"


class DefaultPipelineInitialization(StrictSchema):
    pipeline_id: PipelineId
    version: PositiveVersion
    status: PipelineStatus
    action: DefaultCatalogAction
    violations: list[PipelineValidationViolation] = Field(default_factory=list)


class DefaultCatalogInitializationData(StrictSchema):
    backend_ids_created: list[BackendId] = Field(default_factory=list)
    backend_ids_existing: list[BackendId] = Field(default_factory=list)
    pipelines: Annotated[
        list[DefaultPipelineInitialization],
        Field(min_length=1),
    ]


DefaultCatalogInitializationResponse = ApiResponse[DefaultCatalogInitializationData]


__all__ = [
    "DefaultCatalogAction",
    "DefaultCatalogInitializationData",
    "DefaultCatalogInitializationResponse",
    "DefaultPipelineInitialization",
    "InitializeDefaultsRequest",
]
