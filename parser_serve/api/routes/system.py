"""Authenticated system information and capability endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from ...persistence import Database
from ...persistence.models import BackendRecord, PipelineRecord, WorkerRecord
from ...persistence.registry import backend_detail, pipeline_definition
from ...schema.common import ApiResponse
from ...schema.hardware import DeviceInfo, DeviceRuntime, HardwareVendor
from ...schema.management import (
    ParserCapabilitiesData,
    RuntimeCapability,
    SettingKey,
    SystemInfoData,
)
from ...schema.worker import WorkerStatus
from ..authentication import require_api_key
from ..errors import ApiError
from ...schema.error import ErrorCode
from ..responses import api_response
from ..dynamic_settings import effective_int_setting


router = APIRouter(
    prefix="/api/v1",
    tags=["system"],
    dependencies=[Depends(require_api_key)],
)


@router.get(
    "/capabilities",
    operation_id="get_capabilities",
    response_model=ApiResponse[ParserCapabilitiesData],
)
async def get_capabilities(
    request: Request,
) -> ApiResponse[ParserCapabilitiesData]:
    settings = request.app.state.settings
    maximum_upload_bytes = await effective_int_setting(
        request,
        SettingKey.MAXIMUM_UPLOAD_BYTES,
    )
    database: Database | None = request.app.state.database
    backends = []
    pipelines = []
    workers = []
    if database is not None:
        try:
            async with database.session_factory() as session:
                backends = list(
                    await session.scalars(
                        select(BackendRecord).where(BackendRecord.status == "enabled")
                    )
                )
                pipelines = list(
                    await session.scalars(
                        select(PipelineRecord).where(
                            PipelineRecord.status == "published"
                        )
                    )
                )
                workers = list(
                    await session.scalars(
                        select(WorkerRecord).where(
                            WorkerRecord.enabled.is_(True),
                            WorkerRecord.status.in_(
                                [
                                    WorkerStatus.ONLINE.value,
                                    WorkerStatus.BUSY.value,
                                ]
                            ),
                        )
                    )
                )
        except SQLAlchemyError as exc:
            raise ApiError(
                status_code=503,
                code=ErrorCode.DEPENDENCY_UNAVAILABLE,
                message="The capability registry is unavailable",
                retryable=True,
            ) from exc

    backend_definitions = [backend_detail(record) for record in backends]
    pipeline_definitions = [pipeline_definition(record) for record in pipelines]
    media_categories = sorted(
        {
            category
            for backend in backend_definitions
            for category in backend.capability.media_categories
        },
        key=lambda item: item.value,
    )
    mime_types = sorted(
        {
            mime_type
            for backend in backend_definitions
            for mime_type in backend.capability.mime_types
        }
    )
    runtime_workers: dict[DeviceRuntime, set[str]] = {}
    runtime_devices: dict[DeviceRuntime, int] = {}
    runtime_vendors: dict[DeviceRuntime, HardwareVendor] = {}
    for worker in workers:
        for payload in worker.devices_payload:
            device = DeviceInfo.model_validate(payload)
            runtime_workers.setdefault(device.runtime, set()).add(worker.worker_id)
            runtime_devices[device.runtime] = runtime_devices.get(device.runtime, 0) + 1
            runtime_vendors[device.runtime] = device.vendor
    return api_response(
        request,
        ParserCapabilitiesData(
            schema_version=settings.result_schema_version,
            media_categories=media_categories,
            mime_types=mime_types,
            runtimes=[
                RuntimeCapability(
                    runtime=runtime,
                    vendor=runtime_vendors[runtime],
                    available_workers=len(runtime_workers[runtime]),
                    available_devices=runtime_devices[runtime],
                )
                for runtime in sorted(runtime_workers, key=lambda item: item.value)
            ],
            pipelines=[
                f"{pipeline.pipeline_id}@{pipeline.version}"
                for pipeline in sorted(
                    pipeline_definitions,
                    key=lambda item: (item.pipeline_id, item.version),
                )
            ],
            backends=[
                f"{backend.capability.name}@{backend.capability.version}"
                for backend in sorted(
                    backend_definitions,
                    key=lambda item: (
                        item.capability.name,
                        item.capability.version,
                    ),
                )
            ],
            maximum_upload_bytes=maximum_upload_bytes,
        ),
    )


@router.get(
    "/system/info",
    operation_id="get_system_info",
    response_model=ApiResponse[SystemInfoData],
)
async def get_system_info(request: Request) -> ApiResponse[SystemInfoData]:
    settings = request.app.state.settings
    return api_response(
        request,
        SystemInfoData(
            name=settings.app_name,
            version=settings.app_version,
            api_version=settings.api_version,
            result_schema_version=settings.result_schema_version,
            build_commit=settings.build_commit,
            build_time=settings.build_time,
        ),
    )


__all__ = ["router"]
