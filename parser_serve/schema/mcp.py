"""MCP tool input/output and resource contracts."""

from __future__ import annotations

from enum import StrEnum

from .backend import BackendDetail
from .base import StrictSchema
from .common import NonEmptyStr, TaskId
from .management import ParserCapabilitiesData
from .pipeline import PipelineDefinition
from .result import ParseResult
from .task import CreateTaskData, CreateTaskRequest, TaskDetail


# MCP and HTTP intentionally share the same task contracts.
McpSubmitRequest = CreateTaskRequest
McpSubmitResult = CreateTaskData
McpTaskResult = TaskDetail
McpParseResult = ParseResult
McpCancelResult = TaskDetail


class McpTaskReference(StrictSchema):
    task_id: TaskId


class McpResourceType(StrEnum):
    TASK = "task"
    TASK_RESULT = "task_result"
    CAPABILITIES = "capabilities"
    PIPELINE = "pipeline"
    BACKEND = "backend"


class McpResourceReference(StrictSchema):
    type: McpResourceType
    uri: NonEmptyStr
    name: NonEmptyStr
    description: str | None = None


class McpCapabilitiesResult(StrictSchema):
    capabilities: ParserCapabilitiesData


class McpPipelineResult(StrictSchema):
    pipeline: PipelineDefinition


class McpBackendResult(StrictSchema):
    backend: BackendDetail


class McpPipelineListResult(StrictSchema):
    pipelines: list[PipelineDefinition]


class McpBackendListResult(StrictSchema):
    backends: list[BackendDetail]


__all__ = [
    "McpBackendListResult",
    "McpBackendResult",
    "McpCancelResult",
    "McpCapabilitiesResult",
    "McpParseResult",
    "McpPipelineResult",
    "McpPipelineListResult",
    "McpResourceReference",
    "McpResourceType",
    "McpSubmitRequest",
    "McpSubmitResult",
    "McpTaskReference",
    "McpTaskResult",
]
