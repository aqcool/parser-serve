"""Idempotent installation of built-in Backends and default Pipelines."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..backends import (
    FFmpegBackend,
    ImageMetadataBackend,
    OfficeOpenXmlBackend,
    PdfBackend,
    StaticWebBackend,
    TextBackend,
)
from ..persistence.models import BackendRecord, PipelineRecord
from ..persistence.registry import (
    BackendRepository,
    PipelineRepository,
    pipeline_definition,
)
from ..schema.backend import BackendExecutionMode, CreateBackendRequest
from ..schema.common import MediaCategory
from ..schema.defaults import (
    DefaultCatalogAction,
    DefaultCatalogInitializationData,
    DefaultPipelineInitialization,
    InitializeDefaultsRequest,
)
from ..schema.pipeline import (
    BackendSelector,
    CreatePipelineRequest,
    PipelineStageDefinition,
    PipelineStatus,
    RetryPolicy,
)


BUILTIN_BACKEND_TYPES = (
    TextBackend,
    StaticWebBackend,
    OfficeOpenXmlBackend,
    PdfBackend,
    ImageMetadataBackend,
    FFmpegBackend,
)


def default_pipeline_requests() -> tuple[CreatePipelineRequest, ...]:
    retry = RetryPolicy(
        maximum_attempts=2,
        initial_delay_seconds=2.0,
        maximum_delay_seconds=30.0,
    )
    return (
        CreatePipelineRequest(
            pipeline_id="pipeline_document_auto",
            name="document.auto",
            media_categories=[MediaCategory.DOCUMENT],
            routing_priority=100,
            stages=[
                PipelineStageDefinition(
                    name="parse",
                    backend=BackendSelector(
                        preferred="mineru",
                        fallbacks=[
                            "paddleocr_vl",
                            "hunyuan_ocr",
                            "builtin_pdf",
                            "builtin_office",
                        ],
                    ),
                    timeout_seconds=600,
                    retry=retry,
                )
            ],
        ),
        CreatePipelineRequest(
            pipeline_id="pipeline_web_static",
            name="web.static",
            media_categories=[MediaCategory.WEB],
            mime_types=["text/html", "application/xhtml+xml"],
            routing_priority=100,
            stages=[
                PipelineStageDefinition(
                    name="extract",
                    backend=BackendSelector(preferred="builtin_web"),
                    timeout_seconds=120,
                    retry=retry,
                )
            ],
        ),
        CreatePipelineRequest(
            pipeline_id="pipeline_web_rendered",
            name="web.rendered",
            media_categories=[MediaCategory.WEB],
            mime_types=["text/html", "application/xhtml+xml"],
            routing_priority=90,
            stages=[
                PipelineStageDefinition(
                    name="render",
                    backend=BackendSelector(preferred="web_rendered"),
                    timeout_seconds=300,
                    retry=retry,
                    parameters={
                        "wait_until": "networkidle",
                        "maximum_render_seconds": 60,
                    },
                )
            ],
        ),
        CreatePipelineRequest(
            pipeline_id="pipeline_image_ocr",
            name="image.ocr",
            media_categories=[MediaCategory.IMAGE],
            routing_priority=100,
            stages=[
                PipelineStageDefinition(
                    name="ocr",
                    backend=BackendSelector(
                        preferred="paddleocr",
                        fallbacks=["hunyuan_ocr", "paddleocr_vl"],
                    ),
                    timeout_seconds=300,
                    retry=retry,
                )
            ],
        ),
        CreatePipelineRequest(
            pipeline_id="pipeline_image_multimodal",
            name="image.multimodal",
            media_categories=[MediaCategory.IMAGE],
            routing_priority=90,
            stages=[
                PipelineStageDefinition(
                    name="understand",
                    backend=BackendSelector(
                        preferred="paddleocr_vl",
                        fallbacks=["hunyuan_ocr", "vlm"],
                    ),
                    timeout_seconds=600,
                    retry=retry,
                )
            ],
        ),
        CreatePipelineRequest(
            pipeline_id="pipeline_audio_transcription",
            name="audio.transcription",
            media_categories=[MediaCategory.AUDIO],
            routing_priority=100,
            stages=[
                PipelineStageDefinition(
                    name="transcribe",
                    backend=BackendSelector(preferred="asr"),
                    timeout_seconds=3600,
                    retry=retry,
                )
            ],
        ),
        CreatePipelineRequest(
            pipeline_id="pipeline_video_multimodal",
            name="video.multimodal",
            media_categories=[MediaCategory.VIDEO],
            routing_priority=100,
            stages=[
                PipelineStageDefinition(
                    name="understand",
                    backend=BackendSelector(
                        preferred="video_vlm",
                        fallbacks=["vlm"],
                    ),
                    timeout_seconds=7200,
                    retry=retry,
                )
            ],
        ),
    )


class DefaultCatalogInstaller:
    def __init__(self) -> None:
        self.backends = BackendRepository()
        self.pipelines = PipelineRepository()

    async def install(
        self,
        session: AsyncSession,
        *,
        request: InitializeDefaultsRequest,
        now: datetime,
    ) -> DefaultCatalogInitializationData:
        created_backend_ids: list[str] = []
        existing_backend_ids: list[str] = []
        if request.include_builtin_backends:
            for backend_type in BUILTIN_BACKEND_TYPES:
                capability = backend_type.capability
                existing = await session.scalar(
                    select(BackendRecord).where(
                        BackendRecord.name == capability.name,
                        BackendRecord.version == capability.version,
                    )
                )
                if existing is not None:
                    existing_backend_ids.append(existing.backend_id)
                    continue
                record = await self.backends.create(
                    session,
                    request=CreateBackendRequest(
                        capability=capability,
                        execution_mode=BackendExecutionMode.LOCAL,
                        default_timeout_seconds=600,
                        maximum_attempts=2,
                    ),
                    now=now,
                )
                created_backend_ids.append(record.backend_id)

        pipeline_results = [
            await self._install_pipeline(
                session,
                request=pipeline_request,
                publish_valid=request.publish_valid_pipelines,
                now=now,
            )
            for pipeline_request in default_pipeline_requests()
        ]
        return DefaultCatalogInitializationData(
            backend_ids_created=created_backend_ids,
            backend_ids_existing=existing_backend_ids,
            pipelines=pipeline_results,
        )

    async def _install_pipeline(
        self,
        session: AsyncSession,
        *,
        request: CreatePipelineRequest,
        publish_valid: bool,
        now: datetime,
    ) -> DefaultPipelineInitialization:
        record = await session.scalar(
            select(PipelineRecord)
            .where(PipelineRecord.pipeline_id == request.pipeline_id)
            .order_by(PipelineRecord.version.desc())
            .limit(1)
        )
        created = record is None
        if record is None:
            record = await self.pipelines.create(session, request=request, now=now)

        definition = pipeline_definition(record)
        if definition.status is PipelineStatus.PUBLISHED:
            return DefaultPipelineInitialization(
                pipeline_id=record.pipeline_id,
                version=record.version,
                status=PipelineStatus.PUBLISHED,
                action=DefaultCatalogAction.UNCHANGED,
            )

        validation = await self.pipelines.validate(session, record)
        if publish_valid and validation.valid:
            published = await self.pipelines.publish(
                session,
                pipeline_id=record.pipeline_id,
                version=record.version,
                now=now,
            )
            if published is None:  # pragma: no cover - locked record exists
                raise RuntimeError("default Pipeline disappeared while publishing")
            return DefaultPipelineInitialization(
                pipeline_id=published.pipeline_id,
                version=published.version,
                status=PipelineStatus.PUBLISHED,
                action=DefaultCatalogAction.PUBLISHED,
            )

        return DefaultPipelineInitialization(
            pipeline_id=record.pipeline_id,
            version=record.version,
            status=PipelineStatus.DRAFT,
            action=(
                DefaultCatalogAction.CREATED
                if created and not publish_valid
                else DefaultCatalogAction.DRAFT_UNAVAILABLE
            ),
            violations=validation.violations,
        )


__all__ = [
    "BUILTIN_BACKEND_TYPES",
    "DefaultCatalogInstaller",
    "default_pipeline_requests",
]
