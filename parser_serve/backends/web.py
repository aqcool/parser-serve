"""Static HTML text and link extraction Backend."""

from __future__ import annotations

from datetime import UTC, datetime
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse
from uuid import uuid4

from pydantic import AnyUrl

from ..schema.artifact import ArtifactType
from ..schema.backend import BackendCapability
from ..schema.common import MediaCategory
from ..schema.hardware import DeviceRuntime
from ..schema.result import (
    ContentBlock,
    ContentMetadata,
    LinkBlock,
    ParseResult,
    TextBlock,
)
from .base import (
    BackendContext,
    BackendExecutionError,
    BackendOutput,
    ProducedArtifact,
)


class _ReadableHtmlParser(HTMLParser):
    def __init__(self, *, base_url: str | None) -> None:
        super().__init__(convert_charrefs=True)
        self.base_url = base_url
        self.hidden_depth = 0
        self.in_title = False
        self.title_parts: list[str] = []
        self.text_parts: list[str] = []
        self.links: list[tuple[str, str | None]] = []
        self._current_link: str | None = None
        self._current_link_text: list[str] = []

    def handle_starttag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        normalized = tag.casefold()
        if normalized in {"script", "style", "noscript", "template"}:
            self.hidden_depth += 1
            return
        if self.hidden_depth:
            return
        if normalized == "title":
            self.in_title = True
        if normalized == "a":
            href = dict(attrs).get("href")
            if href:
                candidate = urljoin(self.base_url, href) if self.base_url else href
                if urlparse(candidate).scheme in {"http", "https"}:
                    self._current_link = candidate
                    self._current_link_text = []

    def handle_endtag(self, tag: str) -> None:
        normalized = tag.casefold()
        if normalized in {"script", "style", "noscript", "template"}:
            self.hidden_depth = max(self.hidden_depth - 1, 0)
            return
        if self.hidden_depth:
            return
        if normalized == "title":
            self.in_title = False
        if normalized == "a" and self._current_link is not None:
            text = " ".join(self._current_link_text).strip() or None
            self.links.append((self._current_link, text))
            self._current_link = None
            self._current_link_text = []

    def handle_data(self, data: str) -> None:
        if self.hidden_depth:
            return
        text = " ".join(data.split())
        if not text:
            return
        if self.in_title:
            self.title_parts.append(text)
        else:
            self.text_parts.append(text)
        if self._current_link is not None:
            self._current_link_text.append(text)


class StaticWebBackend:
    capability = BackendCapability(
        name="builtin_web",
        version="1.0",
        media_categories=[MediaCategory.WEB],
        mime_types=["text/html", "application/xhtml+xml"],
        runtimes=[DeviceRuntime.CPU],
        maximum_concurrency=16,
    )

    async def execute(self, context: BackendContext) -> BackendOutput:
        await context.report_progress(10.0)
        html = self._html(context)
        base_url = context.lease.parameters.get("base_url")
        if base_url is None:
            base_url = context.lease.source_metadata.attributes.get("source_url")
        if base_url is not None and not isinstance(base_url, str):
            raise BackendExecutionError("base_url must be a string")
        parser = _ReadableHtmlParser(base_url=base_url)
        try:
            parser.feed(html)
            parser.close()
        except Exception as exc:
            raise BackendExecutionError(
                f"HTML parsing failed: {type(exc).__name__}"
            ) from exc
        blocks: list[ContentBlock] = []
        text = "\n".join(parser.text_parts)
        if text:
            blocks.append(
                TextBlock(
                    type="text",
                    block_id=f"block_{uuid4().hex}",
                    text=text,
                )
            )
        blocks.extend(
            LinkBlock(
                type="link",
                block_id=f"block_{uuid4().hex}",
                url=AnyUrl(url),
                text=link_text,
            )
            for url, link_text in parser.links
        )
        await context.report_progress(90.0)
        result = ParseResult(
            schema_version="1.0",
            task_id=context.lease.task_id,
            source=context.lease.source_metadata,
            metadata=ContentMetadata(
                title=" ".join(parser.title_parts).strip() or None,
                attributes={"link_count": len(parser.links)},
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
    def _html(context: BackendContext) -> str:
        if context.source_text is not None:
            return context.source_text
        if context.source_path is None:
            raise BackendExecutionError("web Backend requires HTML text or a file")
        try:
            return context.source_path.read_text(encoding="utf-8-sig")
        except UnicodeDecodeError as exc:
            raise BackendExecutionError("HTML source is not valid UTF-8") from exc


__all__ = ["StaticWebBackend"]
