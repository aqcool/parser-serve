"""Versioned pipeline DAG contracts."""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated

from pydantic import Field, StringConstraints, model_validator

from .base import JsonValue, StrictSchema
from .common import (
    ApiResponse,
    ListResponse,
    MediaCategory,
    MimePattern,
    NonEmptyStr,
    PipelineId,
    PositiveVersion,
    Priority,
    SortDirection,
    StrictBool,
    UTCDateTime,
)
from .hardware import DeviceRuntime
from .hardware import DeviceRequirement
from .source import ParseSource
from .task import ParseFeatures


PipelineStageName = Annotated[
    str,
    StringConstraints(
        pattern=r"^[a-z][a-z0-9_-]{0,63}$",
        strict=True,
    ),
]


class PipelineStatus(StrEnum):
    DRAFT = "draft"
    PUBLISHED = "published"
    DISABLED = "disabled"
    ARCHIVED = "archived"


class RetryPolicy(StrictSchema):
    maximum_attempts: Annotated[int, Field(ge=1, le=20, strict=True)] = 1
    initial_delay_seconds: Annotated[
        float,
        Field(ge=0.0, le=3600.0, strict=True),
    ] = 1.0
    maximum_delay_seconds: Annotated[
        float,
        Field(ge=0.0, le=86_400.0, strict=True),
    ] = 30.0
    multiplier: Annotated[float, Field(ge=1.0, le=10.0, strict=True)] = 2.0

    @model_validator(mode="after")
    def validate_delays(self) -> RetryPolicy:
        if self.maximum_delay_seconds < self.initial_delay_seconds:
            raise ValueError(
                "maximum_delay_seconds cannot be less than initial_delay_seconds"
            )
        return self


class BackendSelector(StrictSchema):
    preferred: NonEmptyStr
    fallbacks: list[NonEmptyStr] = Field(default_factory=list)
    required_runtimes: list[DeviceRuntime] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_selector(self) -> BackendSelector:
        candidates = [self.preferred, *self.fallbacks]
        if len(candidates) != len(set(candidates)):
            raise ValueError("backend candidates must be unique")
        if len(self.required_runtimes) != len(set(self.required_runtimes)):
            raise ValueError("required_runtimes must be unique")
        return self


class PipelineStageDefinition(StrictSchema):
    name: PipelineStageName
    backend: BackendSelector
    depends_on: list[PipelineStageName] = Field(default_factory=list)
    timeout_seconds: Annotated[int, Field(ge=1, le=86_400, strict=True)]
    retry: RetryPolicy = Field(default_factory=RetryPolicy)
    optional: StrictBool = False
    parameters: dict[str, JsonValue] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_dependencies(self) -> PipelineStageDefinition:
        if self.name in self.depends_on:
            raise ValueError("a stage cannot depend on itself")
        if len(self.depends_on) != len(set(self.depends_on)):
            raise ValueError("depends_on must not contain duplicates")
        return self


class PipelineDefinition(StrictSchema):
    pipeline_id: PipelineId
    name: NonEmptyStr
    version: PositiveVersion
    status: PipelineStatus
    media_categories: Annotated[list[MediaCategory], Field(min_length=1)]
    mime_types: list[MimePattern] = Field(default_factory=list)
    routing_priority: Annotated[
        int,
        Field(ge=-1000, le=1000, strict=True),
    ] = 0
    stages: Annotated[list[PipelineStageDefinition], Field(min_length=1)]
    created_at: UTCDateTime
    published_at: UTCDateTime | None = None

    @model_validator(mode="after")
    def validate_dag(self) -> PipelineDefinition:
        stage_names = [stage.name for stage in self.stages]
        if len(stage_names) != len(set(stage_names)):
            raise ValueError("pipeline stage names must be unique")

        known = set(stage_names)
        for stage in self.stages:
            missing = set(stage.depends_on) - known
            if missing:
                names = ", ".join(sorted(missing))
                raise ValueError(
                    f"stage {stage.name!r} has unknown dependencies: {names}"
                )

        dependencies = {stage.name: set(stage.depends_on) for stage in self.stages}
        visiting: set[str] = set()
        visited: set[str] = set()

        def visit(name: str) -> None:
            if name in visiting:
                raise ValueError("pipeline dependencies must form an acyclic graph")
            if name in visited:
                return
            visiting.add(name)
            for dependency in dependencies[name]:
                visit(dependency)
            visiting.remove(name)
            visited.add(name)

        for name in stage_names:
            visit(name)

        if self.status is PipelineStatus.PUBLISHED and self.published_at is None:
            raise ValueError("published pipelines require published_at")
        if (
            self.status is not PipelineStatus.PUBLISHED
            and self.published_at is not None
        ):
            raise ValueError("only published pipelines may define published_at")
        if self.published_at is not None and self.published_at < self.created_at:
            raise ValueError("published_at cannot be earlier than created_at")
        return self


PipelineDetailResponse = ApiResponse[PipelineDefinition]
PipelineListResponse = ListResponse[PipelineDefinition]


class CreatePipelineRequest(StrictSchema):
    pipeline_id: PipelineId
    name: NonEmptyStr
    media_categories: Annotated[list[MediaCategory], Field(min_length=1)]
    mime_types: list[MimePattern] = Field(default_factory=list)
    routing_priority: Annotated[
        int,
        Field(ge=-1000, le=1000, strict=True),
    ] = 0
    stages: Annotated[list[PipelineStageDefinition], Field(min_length=1)]


class PipelineValidationViolation(StrictSchema):
    location: NonEmptyStr
    message: NonEmptyStr


class PipelineValidationData(StrictSchema):
    valid: StrictBool
    violations: list[PipelineValidationViolation] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_result(self) -> PipelineValidationData:
        if self.valid and self.violations:
            raise ValueError("valid pipeline results cannot contain violations")
        if not self.valid and not self.violations:
            raise ValueError("invalid pipeline results require violations")
        return self


PipelineValidationResponse = ApiResponse[PipelineValidationData]


class PipelineSortField(StrEnum):
    CREATED_AT = "created_at"
    UPDATED_AT = "updated_at"
    NAME = "name"
    VERSION = "version"


class PipelineListQuery(StrictSchema):
    statuses: list[PipelineStatus] = Field(default_factory=list)
    media_category: MediaCategory | None = None
    name_contains: (
        Annotated[
            str,
            Field(min_length=1, max_length=128, strict=True),
        ]
        | None
    ) = None
    limit: Annotated[int, Field(ge=1, le=200, strict=True)] = 50
    cursor: str | None = None
    sort_by: PipelineSortField = PipelineSortField.CREATED_AT
    sort_direction: SortDirection = SortDirection.DESC


class PipelineTestOptions(StrictSchema):
    backend_name: NonEmptyStr | None = None
    priority: Priority = 0
    timeout_seconds: Annotated[int, Field(ge=1, le=86_400, strict=True)] | None = None
    device: DeviceRequirement = Field(default_factory=DeviceRequirement)
    features: ParseFeatures = Field(default_factory=ParseFeatures)


class PipelineTestRequest(StrictSchema):
    source: ParseSource
    options: PipelineTestOptions = Field(default_factory=PipelineTestOptions)
    client_reference: (
        Annotated[
            str,
            Field(min_length=1, max_length=256, strict=True),
        ]
        | None
    ) = None


__all__ = [
    "BackendSelector",
    "CreatePipelineRequest",
    "PipelineDefinition",
    "PipelineDetailResponse",
    "PipelineListQuery",
    "PipelineListResponse",
    "PipelineSortField",
    "PipelineStageDefinition",
    "PipelineStageName",
    "PipelineStatus",
    "PipelineTestOptions",
    "PipelineTestRequest",
    "PipelineValidationData",
    "PipelineValidationResponse",
    "PipelineValidationViolation",
    "RetryPolicy",
]
