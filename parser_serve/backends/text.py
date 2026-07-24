"""Plain text and Markdown parsing Backend."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from uuid import uuid4

from ..schema.artifact import ArtifactType
from ..schema.backend import BackendCapability
from ..schema.common import MediaCategory
from ..schema.hardware import DeviceRuntime
from ..schema.result import (
    ContentMetadata,
    ContentBlock,
    HeadingBlock,
    ParseResult,
    TextBlock,
)
from .base import (
    BackendContext,
    BackendExecutionError,
    BackendOutput,
    ProducedArtifact,
)


_HEADING = re.compile(r"^(#{1,6})[ \t]+(.+?)\s*$")


class TextBackend:
    capability = BackendCapability(
        name="builtin_text",
        version="1.0",
        media_categories=[MediaCategory.TEXT],
        mime_types=[
            "text/plain",
            "text/markdown",
            "text/x-markdown",
            "application/json",
        ],
        runtimes=[DeviceRuntime.CPU],
        maximum_concurrency=8,
    )

    async def execute(self, context: BackendContext) -> BackendOutput:
        await context.report_progress(10.0)
        text = self._read_text(context)
        is_markdown = context.lease.source_metadata.mime_type in {
            "text/markdown",
            "text/x-markdown",
        } or (
            context.lease.source_metadata.filename is not None
            and context.lease.source_metadata.filename.lower().endswith(
                (".md", ".markdown")
            )
        )
        blocks: list[ContentBlock]
        if is_markdown:
            blocks, title = self._markdown_blocks(text)
        else:
            blocks = [
                TextBlock(
                    type="text",
                    block_id=f"block_{uuid4().hex}",
                    text=text,
                )
            ]
            title = None
        await context.report_progress(80.0)
        result = ParseResult(
            schema_version="1.0",
            task_id=context.lease.task_id,
            source=context.lease.source_metadata,
            metadata=ContentMetadata(
                title=title,
                attributes={
                    "character_count": len(text),
                    "line_count": len(text.splitlines()),
                },
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

    @staticmethod
    def _read_text(context: BackendContext) -> str:
        if context.source_text is not None:
            return context.source_text
        if context.source_path is None:
            raise BackendExecutionError("text Backend requires text or a local file")
        try:
            return context.source_path.read_text(encoding="utf-8-sig")
        except UnicodeDecodeError as exc:
            raise BackendExecutionError("the text source is not valid UTF-8") from exc

    @staticmethod
    def _markdown_blocks(
        text: str,
    ) -> tuple[list[ContentBlock], str | None]:
        blocks: list[ContentBlock] = []
        paragraph: list[str] = []
        title: str | None = None

        def flush_paragraph() -> None:
            if not paragraph:
                return
            blocks.append(
                TextBlock(
                    type="text",
                    block_id=f"block_{uuid4().hex}",
                    text="\n".join(paragraph),
                )
            )
            paragraph.clear()

        for line in text.splitlines():
            heading = _HEADING.match(line)
            if heading is not None:
                flush_paragraph()
                heading_text = heading.group(2)
                title = title or heading_text
                blocks.append(
                    HeadingBlock(
                        type="heading",
                        block_id=f"block_{uuid4().hex}",
                        text=heading_text,
                        level=len(heading.group(1)),
                    )
                )
            elif line.strip():
                paragraph.append(line)
            else:
                flush_paragraph()
        flush_paragraph()
        return blocks, title


__all__ = ["TextBackend"]
