"""Basic PDF text extraction Backend."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from importlib import import_module
from pathlib import Path
from uuid import uuid4

from ..schema.artifact import ArtifactType
from ..schema.backend import BackendCapability
from ..schema.base import JsonValue
from ..schema.common import MediaCategory
from ..schema.hardware import DeviceRuntime
from ..schema.result import (
    BlockLocation,
    ContentBlock,
    ContentMetadata,
    ParseResult,
    TextBlock,
)
from .base import (
    BackendContext,
    BackendExecutionError,
    BackendOutput,
    ProducedArtifact,
)


def _extract_pdf(
    source: Path,
    *,
    maximum_pages: int,
) -> tuple[list[str], dict[str, str]]:
    try:
        pypdf = import_module("pypdf")
    except ImportError as exc:
        raise BackendExecutionError("pypdf is not installed in this Worker") from exc
    try:
        reader = pypdf.PdfReader(str(source))
        if getattr(reader, "is_encrypted", False):
            raise BackendExecutionError("encrypted PDFs are not supported")
        if len(reader.pages) > maximum_pages:
            raise BackendExecutionError(
                f"PDF has {len(reader.pages)} pages; limit is {maximum_pages}"
            )
        pages = [(page.extract_text() or "") for page in reader.pages]
        raw_metadata = getattr(reader, "metadata", None) or {}
        metadata = {
            str(key).lstrip("/"): str(value)
            for key, value in raw_metadata.items()
            if value is not None
        }
        return pages, metadata
    except BackendExecutionError:
        raise
    except Exception as exc:
        raise BackendExecutionError(
            f"PDF extraction failed: {type(exc).__name__}"
        ) from exc


class PdfBackend:
    capability = BackendCapability(
        name="builtin_pdf",
        version="1.0",
        media_categories=[MediaCategory.DOCUMENT],
        mime_types=["application/pdf"],
        runtimes=[DeviceRuntime.CPU],
        maximum_concurrency=4,
    )

    def __init__(self, *, maximum_pages: int = 1000) -> None:
        if maximum_pages < 1:
            raise ValueError("maximum_pages must be greater than zero")
        self.maximum_pages = maximum_pages

    async def execute(self, context: BackendContext) -> BackendOutput:
        if context.source_path is None:
            raise BackendExecutionError("PDF Backend requires a downloaded source file")
        maximum_pages = self._maximum_pages(context)
        await context.report_progress(10.0)
        pages, document_metadata = await asyncio.to_thread(
            _extract_pdf,
            context.source_path,
            maximum_pages=maximum_pages,
        )
        blocks: list[ContentBlock] = [
            TextBlock(
                type="text",
                block_id=f"block_{uuid4().hex}",
                text=text,
                location=BlockLocation(page_number=index),
            )
            for index, text in enumerate(pages, start=1)
            if text
        ]
        await context.report_progress(90.0)
        pdf_metadata: dict[str, JsonValue] = {
            key: value for key, value in document_metadata.items()
        }
        result = ParseResult(
            schema_version="1.0",
            task_id=context.lease.task_id,
            source=context.lease.source_metadata,
            metadata=ContentMetadata(
                title=document_metadata.get("Title"),
                page_count=len(pages),
                attributes={"pdf_metadata": pdf_metadata},
            ),
            blocks=blocks,
            created_at=datetime.now(UTC),
        )
        return BackendOutput(
            artifacts=(
                ProducedArtifact(
                    type=ArtifactType.RESULT_JSON,
                    filename="result.json",
                    mime_type="application/json",
                    data=result.model_dump_json(indent=2).encode("utf-8"),
                ),
            )
        )

    def _maximum_pages(self, context: BackendContext) -> int:
        value = context.lease.parameters.get("maximum_pages", self.maximum_pages)
        if not isinstance(value, int) or isinstance(value, bool) or value < 1:
            raise BackendExecutionError("maximum_pages must be a positive integer")
        if value > self.maximum_pages:
            raise BackendExecutionError(
                f"maximum_pages cannot exceed the Worker limit {self.maximum_pages}"
            )
        return value


__all__ = ["PdfBackend"]
