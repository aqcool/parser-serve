"""Typed MCP tools and resources backed by the control-plane repositories."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime

from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError
from mcp.server.transport_security import TransportSecuritySettings
from sqlalchemy import select

from ..persistence import (
    ArtifactRepository,
    Database,
    SystemSettingRepository,
    TransactionalEventPublisher,
)
from ..persistence.models import BackendRecord, PipelineRecord, WorkerRecord
from ..persistence.registry import (
    BackendRepository,
    PipelineRepository,
    backend_detail,
    pipeline_definition,
)
from ..persistence.tasks import (
    IdempotencyConflictError,
    PipelineNotFoundError,
    TaskNotCancellableError,
    TaskRepository,
    task_detail,
)
from ..schema.backend import BackendListQuery, BackendStatus
from ..schema.common import TaskId
from ..schema.hardware import DeviceInfo, DeviceRuntime, HardwareVendor
from ..schema.management import (
    ParserCapabilitiesData,
    RuntimeCapability,
    SettingKey,
)
from ..schema.mcp import (
    McpBackendListResult,
    McpCapabilitiesResult,
    McpPipelineListResult,
    McpSubmitRequest,
    McpSubmitResult,
    McpTaskReference,
    McpTaskResult,
)
from ..schema.pipeline import PipelineListQuery, PipelineStatus
from ..schema.result import ParseResult
from ..schema.task import TaskStatus
from ..schema.worker import WorkerStatus
from ..settings import Settings
from ..storage import Storage


Clock = Callable[[], datetime]


class ParserMcpService:
    """Application service shared by MCP tools and resources."""

    def __init__(
        self,
        *,
        database: Database,
        storage: Storage,
        settings: Settings,
        clock: Clock,
        events: TransactionalEventPublisher | None = None,
    ) -> None:
        self.database = database
        self.storage = storage
        self.settings = settings
        self.clock = clock
        self.tasks = TaskRepository(events=events)
        self.artifacts = ArtifactRepository()
        self.system_settings = SystemSettingRepository()
        self.backends = BackendRepository()
        self.pipelines = PipelineRepository()

    async def submit(
        self,
        request: McpSubmitRequest,
        *,
        idempotency_key: str | None = None,
    ) -> McpSubmitResult:
        try:
            async with self.database.session_factory() as session:
                record, _ = await self.tasks.create(
                    session,
                    request=request,
                    idempotency_key=idempotency_key,
                    now=self.clock(),
                )
                await session.commit()
        except IdempotencyConflictError as exc:
            raise ToolError(
                "Idempotency key was used with a different request"
            ) from exc
        except PipelineNotFoundError as exc:
            raise ToolError("The requested Pipeline version is unavailable") from exc
        return McpSubmitResult(
            task_id=record.task_id,
            status=TaskStatus(record.status),
            created_at=record.created_at,
        )

    async def get_task(self, task_id: TaskId) -> McpTaskResult:
        async with self.database.session_factory() as session:
            record = await self.tasks.get(session, task_id)
        if record is None:
            raise ToolError("Task not found")
        return task_detail(record)

    async def cancel_task(self, task_id: TaskId) -> McpTaskResult:
        try:
            async with self.database.session_factory() as session:
                record = await self.tasks.cancel(
                    session,
                    task_id=task_id,
                    now=self.clock(),
                )
                if record is None:
                    raise ToolError("Task not found")
                detail = task_detail(record)
                await session.commit()
        except TaskNotCancellableError as exc:
            raise ToolError("Task is terminal and cannot be cancelled") from exc
        return detail

    async def get_result(self, task_id: TaskId) -> ParseResult:
        async with self.database.session_factory() as session:
            task = await self.tasks.get(session, task_id)
            if task is None:
                raise ToolError("Task not found")
            if task.status != TaskStatus.SUCCEEDED.value or task.result_uri is None:
                raise ToolError("Task result is not ready")
            artifact = await self.artifacts.get_by_storage_uri(
                session,
                task_id=task_id,
                storage_uri=task.result_uri,
                now=self.clock(),
            )
            maximum_result_bytes = await self.system_settings.get_int(
                session,
                key=SettingKey.MAXIMUM_RESULT_JSON_BYTES,
                defaults=self.settings,
            )
        if artifact is None or not await self.storage.exists(artifact.storage_key):
            raise ToolError("Primary result Artifact is unavailable")
        content = bytearray()
        async for chunk in self.storage.read(artifact.storage_key):
            content.extend(chunk)
            if len(content) > maximum_result_bytes:
                raise ToolError("Primary result exceeds the configured JSON limit")
        try:
            result = ParseResult.model_validate_json(content)
        except ValueError as exc:
            raise ToolError("Primary result is not a valid ParseResult") from exc
        if result.task_id != task_id:
            raise ToolError("Primary result belongs to a different task")
        return result

    async def list_pipelines(self) -> McpPipelineListResult:
        async with self.database.session_factory() as session:
            records = await self.pipelines.list(
                session,
                query=PipelineListQuery(
                    statuses=[PipelineStatus.PUBLISHED],
                    limit=200,
                ),
            )
        return McpPipelineListResult(
            pipelines=[pipeline_definition(record) for record in records[:200]]
        )

    async def list_backends(self) -> McpBackendListResult:
        async with self.database.session_factory() as session:
            records = await self.backends.list(
                session,
                query=BackendListQuery(
                    statuses=[BackendStatus.ENABLED],
                    limit=200,
                ),
            )
        return McpBackendListResult(
            backends=[backend_detail(record) for record in records[:200]]
        )

    async def capabilities(self) -> McpCapabilitiesResult:
        async with self.database.session_factory() as session:
            backend_records = list(
                await session.scalars(
                    select(BackendRecord).where(BackendRecord.status == "enabled")
                )
            )
            pipeline_records = list(
                await session.scalars(
                    select(PipelineRecord).where(PipelineRecord.status == "published")
                )
            )
            worker_records = list(
                await session.scalars(
                    select(WorkerRecord).where(
                        WorkerRecord.enabled.is_(True),
                        WorkerRecord.status.in_(
                            [WorkerStatus.ONLINE.value, WorkerStatus.BUSY.value]
                        ),
                    )
                )
            )
            maximum_upload_bytes = await self.system_settings.get_int(
                session,
                key=SettingKey.MAXIMUM_UPLOAD_BYTES,
                defaults=self.settings,
            )
        backends = [backend_detail(record) for record in backend_records]
        pipelines = [pipeline_definition(record) for record in pipeline_records]
        runtime_workers: dict[DeviceRuntime, set[str]] = {}
        runtime_devices: dict[DeviceRuntime, int] = {}
        runtime_vendors: dict[DeviceRuntime, HardwareVendor] = {}
        for worker in worker_records:
            for payload in worker.devices_payload:
                device = DeviceInfo.model_validate(payload)
                runtime_workers.setdefault(device.runtime, set()).add(worker.worker_id)
                runtime_devices[device.runtime] = (
                    runtime_devices.get(device.runtime, 0) + 1
                )
                runtime_vendors[device.runtime] = device.vendor
        return McpCapabilitiesResult(
            capabilities=ParserCapabilitiesData(
                schema_version=self.settings.result_schema_version,
                media_categories=sorted(
                    {
                        category
                        for backend in backends
                        for category in backend.capability.media_categories
                    },
                    key=lambda item: item.value,
                ),
                mime_types=sorted(
                    {
                        mime_type
                        for backend in backends
                        for mime_type in backend.capability.mime_types
                    }
                ),
                runtimes=[
                    RuntimeCapability(
                        runtime=runtime,
                        vendor=runtime_vendors[runtime],
                        available_workers=len(runtime_workers[runtime]),
                        available_devices=runtime_devices[runtime],
                    )
                    for runtime in sorted(
                        runtime_workers,
                        key=lambda item: item.value,
                    )
                ],
                pipelines=[
                    f"{pipeline.pipeline_id}@{pipeline.version}"
                    for pipeline in sorted(
                        pipelines,
                        key=lambda item: (item.pipeline_id, item.version),
                    )
                ],
                backends=[
                    f"{backend.capability.name}@{backend.capability.version}"
                    for backend in sorted(
                        backends,
                        key=lambda item: (
                            item.capability.name,
                            item.capability.version,
                        ),
                    )
                ],
                maximum_upload_bytes=maximum_upload_bytes,
            )
        )


def create_mcp_server(service: ParserMcpService) -> FastMCP:
    server = FastMCP(
        name="Parser Serve",
        instructions=(
            "Submit and inspect multimodal parsing tasks. Large files must be "
            "uploaded through the HTTP file API and referenced by file_id."
        ),
        streamable_http_path="/mcp",
        stateless_http=True,
        json_response=True,
        transport_security=TransportSecuritySettings(
            enable_dns_rebinding_protection=True,
            allowed_hosts=service.settings.mcp_allowed_hosts,
            allowed_origins=service.settings.mcp_allowed_origins,
        ),
    )

    @server.tool(name="parser_submit", structured_output=True)
    async def parser_submit(
        request: McpSubmitRequest,
        idempotency_key: str | None = None,
    ) -> McpSubmitResult:
        return await service.submit(request, idempotency_key=idempotency_key)

    @server.tool(name="parser_get_task", structured_output=True)
    async def parser_get_task(reference: McpTaskReference) -> McpTaskResult:
        return await service.get_task(reference.task_id)

    @server.tool(name="parser_get_result", structured_output=True)
    async def parser_get_result(reference: McpTaskReference) -> ParseResult:
        return await service.get_result(reference.task_id)

    @server.tool(name="parser_cancel_task", structured_output=True)
    async def parser_cancel_task(reference: McpTaskReference) -> McpTaskResult:
        return await service.cancel_task(reference.task_id)

    @server.tool(name="parser_list_capabilities", structured_output=True)
    async def parser_list_capabilities() -> McpCapabilitiesResult:
        return await service.capabilities()

    @server.tool(name="parser_list_pipelines", structured_output=True)
    async def parser_list_pipelines() -> McpPipelineListResult:
        return await service.list_pipelines()

    @server.tool(name="parser_list_backends", structured_output=True)
    async def parser_list_backends() -> McpBackendListResult:
        return await service.list_backends()

    @server.resource(
        "parser://tasks/{task_id}",
        name="parser_task",
        mime_type="application/json",
    )
    async def parser_task_resource(task_id: str) -> str:
        reference = McpTaskReference(task_id=task_id)
        return (await service.get_task(reference.task_id)).model_dump_json(indent=2)

    @server.resource(
        "parser://tasks/{task_id}/result",
        name="parser_task_result",
        mime_type="application/json",
    )
    async def parser_result_resource(task_id: str) -> str:
        reference = McpTaskReference(task_id=task_id)
        return (await service.get_result(reference.task_id)).model_dump_json(indent=2)

    @server.resource(
        "parser://capabilities",
        name="parser_capabilities",
        mime_type="application/json",
    )
    async def parser_capabilities_resource() -> str:
        return (await service.capabilities()).model_dump_json(indent=2)

    @server.resource(
        "parser://pipelines",
        name="parser_pipelines",
        mime_type="application/json",
    )
    async def parser_pipelines_resource() -> str:
        return (await service.list_pipelines()).model_dump_json(indent=2)

    @server.resource(
        "parser://backends",
        name="parser_backends",
        mime_type="application/json",
    )
    async def parser_backends_resource() -> str:
        return (await service.list_backends()).model_dump_json(indent=2)

    return server


__all__ = ["ParserMcpService", "create_mcp_server"]
