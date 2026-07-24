"""Dependency-free, bounded extraction for modern Office Open XML files."""

from __future__ import annotations

import asyncio
import re
import zipfile
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from uuid import uuid4
from xml.etree import ElementTree

from ..schema.artifact import ArtifactType
from ..schema.backend import BackendCapability
from ..schema.common import MediaCategory
from ..schema.hardware import DeviceRuntime
from ..schema.result import (
    BlockLocation,
    ContentBlock,
    ContentMetadata,
    ParseResult,
    TableBlock,
    TextBlock,
)
from .base import (
    BackendContext,
    BackendExecutionError,
    BackendOutput,
    ProducedArtifact,
)


_WORD_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
_SHEET_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
_DRAWING_NS = "http://schemas.openxmlformats.org/drawingml/2006/main"
_REL_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_PACKAGE_REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
_CORE_NS = "http://purl.org/dc/elements/1.1/"
_CELL_REFERENCE = re.compile(r"^([A-Z]+)[1-9][0-9]*$")
_SLIDE_NAME = re.compile(r"^ppt/slides/slide([1-9][0-9]*)\.xml$")


class _SafeOfficeArchive:
    def __init__(
        self,
        path: Path,
        *,
        maximum_entries: int,
        maximum_uncompressed_bytes: int,
        maximum_xml_bytes: int,
    ) -> None:
        try:
            self.archive = zipfile.ZipFile(path)
        except (OSError, zipfile.BadZipFile) as exc:
            raise BackendExecutionError(
                "Office file is not a valid ZIP archive"
            ) from exc
        self.maximum_xml_bytes = maximum_xml_bytes
        infos = self.archive.infolist()
        if len(infos) > maximum_entries:
            self.close()
            raise BackendExecutionError(
                f"Office archive has {len(infos)} entries; limit is {maximum_entries}"
            )
        total = 0
        for info in infos:
            member = PurePosixPath(info.filename)
            if (
                member.is_absolute()
                or "\\" in info.filename
                or any(part in {"", ".", ".."} for part in member.parts)
                or info.flag_bits & 0x1
            ):
                self.close()
                raise BackendExecutionError("Office archive contains an unsafe entry")
            total += info.file_size
            if total > maximum_uncompressed_bytes:
                self.close()
                raise BackendExecutionError(
                    "Office archive exceeds the uncompressed size limit"
                )
            if (
                info.file_size > 1_000_000
                and info.compress_size > 0
                and info.file_size / info.compress_size > 1000
            ):
                self.close()
                raise BackendExecutionError(
                    "Office archive contains a suspicious compression ratio"
                )

    def close(self) -> None:
        self.archive.close()

    def names(self) -> set[str]:
        return set(self.archive.namelist())

    def xml(self, name: str, *, required: bool = True) -> ElementTree.Element | None:
        try:
            info = self.archive.getinfo(name)
        except KeyError:
            if required:
                raise BackendExecutionError(
                    f"Office archive is missing required member {name}"
                ) from None
            return None
        if info.file_size > self.maximum_xml_bytes:
            raise BackendExecutionError(f"Office XML member {name} exceeds the limit")
        try:
            payload = self.archive.read(info)
        except (OSError, RuntimeError, zipfile.BadZipFile) as exc:
            raise BackendExecutionError(
                f"Office member {name} could not be read"
            ) from exc
        lowered = payload[:4096].lower()
        if b"<!doctype" in lowered or b"<!entity" in lowered:
            raise BackendExecutionError("Office XML declarations are not allowed")
        try:
            return ElementTree.fromstring(payload)
        except ElementTree.ParseError as exc:
            raise BackendExecutionError(f"Office member {name} is invalid XML") from exc

    def __enter__(self) -> _SafeOfficeArchive:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()


def _text(element: ElementTree.Element, namespace: str) -> str:
    return "".join(
        node.text or "" for node in element.iter(f"{{{namespace}}}t")
    ).strip()


def _docx(
    archive: _SafeOfficeArchive,
) -> tuple[list[ContentBlock], ContentMetadata]:
    root = archive.xml("word/document.xml")
    assert root is not None
    body = root.find(f"{{{_WORD_NS}}}body")
    if body is None:
        raise BackendExecutionError("DOCX document body is missing")
    blocks: list[ContentBlock] = []
    for child in body:
        if child.tag == f"{{{_WORD_NS}}}p":
            value = _text(child, _WORD_NS)
            if value:
                blocks.append(
                    TextBlock(
                        type="text",
                        block_id=f"block_{uuid4().hex}",
                        text=value,
                    )
                )
        elif child.tag == f"{{{_WORD_NS}}}tbl":
            rows = [
                [_text(cell, _WORD_NS) for cell in row.findall(f"{{{_WORD_NS}}}tc")]
                for row in child.findall(f"{{{_WORD_NS}}}tr")
            ]
            if rows:
                blocks.append(
                    TableBlock(
                        type="table",
                        block_id=f"block_{uuid4().hex}",
                        rows=rows,
                    )
                )
    title: str | None = None
    core = archive.xml("docProps/core.xml", required=False)
    if core is not None:
        title_node = core.find(f"{{{_CORE_NS}}}title")
        if title_node is not None and title_node.text:
            title = title_node.text.strip() or None
    return blocks, ContentMetadata(
        title=title,
        attributes={"office_format": "docx"},
    )


def _pptx(
    archive: _SafeOfficeArchive,
) -> tuple[list[ContentBlock], ContentMetadata]:
    slides = sorted(
        (
            (int(match.group(1)), name)
            for name in archive.names()
            if (match := _SLIDE_NAME.match(name)) is not None
        ),
        key=lambda item: item[0],
    )
    if not slides:
        raise BackendExecutionError("PPTX archive contains no slides")
    blocks: list[ContentBlock] = []
    for slide_number, name in slides:
        root = archive.xml(name)
        assert root is not None
        values = [
            (node.text or "").strip()
            for node in root.iter(f"{{{_DRAWING_NS}}}t")
            if (node.text or "").strip()
        ]
        if values:
            blocks.append(
                TextBlock(
                    type="text",
                    block_id=f"block_{uuid4().hex}",
                    text="\n".join(values),
                    location=BlockLocation(slide_number=slide_number),
                )
            )
    return blocks, ContentMetadata(
        page_count=len(slides),
        attributes={"office_format": "pptx", "slide_count": len(slides)},
    )


def _column_index(reference: str) -> int:
    match = _CELL_REFERENCE.match(reference)
    if match is None:
        raise BackendExecutionError("XLSX contains an invalid cell reference")
    result = 0
    for character in match.group(1):
        result = result * 26 + ord(character) - ord("A") + 1
    return result - 1


def _shared_strings(archive: _SafeOfficeArchive) -> list[str]:
    root = archive.xml("xl/sharedStrings.xml", required=False)
    if root is None:
        return []
    return [_text(item, _SHEET_NS) for item in root.findall(f"{{{_SHEET_NS}}}si")]


def _sheet_targets(
    archive: _SafeOfficeArchive,
) -> list[tuple[str, str]]:
    workbook = archive.xml("xl/workbook.xml")
    relationships = archive.xml("xl/_rels/workbook.xml.rels")
    assert workbook is not None and relationships is not None
    targets = {
        relation.attrib.get("Id", ""): relation.attrib.get("Target", "")
        for relation in relationships.findall(f"{{{_PACKAGE_REL_NS}}}Relationship")
    }
    resolved: list[tuple[str, str]] = []
    sheets = workbook.find(f"{{{_SHEET_NS}}}sheets")
    if sheets is None:
        return resolved
    for sheet in sheets.findall(f"{{{_SHEET_NS}}}sheet"):
        relationship_id = sheet.attrib.get(f"{{{_REL_NS}}}id", "")
        target = targets.get(relationship_id, "").lstrip("/")
        if target.startswith("worksheets/"):
            target = f"xl/{target}"
        elif not target.startswith("xl/"):
            raise BackendExecutionError("XLSX worksheet target is unsafe")
        resolved.append((sheet.attrib.get("name", "Sheet"), target))
    return resolved


def _cell_value(
    cell: ElementTree.Element,
    shared_strings: list[str],
) -> str:
    cell_type = cell.attrib.get("t")
    if cell_type == "inlineStr":
        return _text(cell, _SHEET_NS)
    value = cell.find(f"{{{_SHEET_NS}}}v")
    raw = value.text if value is not None and value.text is not None else ""
    if cell_type == "s" and raw:
        try:
            return shared_strings[int(raw)]
        except (ValueError, IndexError) as exc:
            raise BackendExecutionError(
                "XLSX shared string reference is invalid"
            ) from exc
    if cell_type == "b":
        return "true" if raw == "1" else "false"
    return raw


def _xlsx(
    archive: _SafeOfficeArchive,
) -> tuple[list[ContentBlock], ContentMetadata]:
    shared_strings = _shared_strings(archive)
    sheets = _sheet_targets(archive)
    blocks: list[ContentBlock] = []
    for sheet_name, target in sheets:
        root = archive.xml(target)
        assert root is not None
        rows: list[list[str]] = []
        for row in root.iter(f"{{{_SHEET_NS}}}row"):
            cells: list[str] = []
            for cell in row.findall(f"{{{_SHEET_NS}}}c"):
                index = _column_index(cell.attrib.get("r", ""))
                while len(cells) <= index:
                    cells.append("")
                cells[index] = _cell_value(cell, shared_strings)
            while cells and not cells[-1]:
                cells.pop()
            if cells:
                rows.append(cells)
        if rows:
            blocks.append(
                TableBlock(
                    type="table",
                    block_id=f"block_{uuid4().hex}",
                    rows=rows,
                    location=BlockLocation(sheet_name=sheet_name),
                )
            )
    return blocks, ContentMetadata(
        attributes={"office_format": "xlsx", "sheet_count": len(sheets)}
    )


class OfficeOpenXmlBackend:
    capability = BackendCapability(
        name="builtin_office",
        version="1.0",
        media_categories=[MediaCategory.DOCUMENT],
        mime_types=[
            "application/msword",
            "application/vnd.ms-excel",
            "application/vnd.ms-powerpoint",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "application/vnd.openxmlformats-officedocument.presentationml.presentation",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        ],
        runtimes=[DeviceRuntime.CPU],
        maximum_concurrency=4,
    )

    async def execute(self, context: BackendContext) -> BackendOutput:
        if context.source_path is None:
            raise BackendExecutionError(
                "Office Backend requires a downloaded source file"
            )
        await context.report_progress(10.0)
        blocks, metadata = await asyncio.to_thread(
            self._extract,
            context.source_path,
            context.lease.source_metadata.mime_type,
            maximum_entries=self._positive_parameter(
                context,
                "maximum_archive_entries",
                10_000,
            ),
            maximum_uncompressed_bytes=self._positive_parameter(
                context,
                "maximum_uncompressed_bytes",
                256 * 1024 * 1024,
            ),
            maximum_xml_bytes=self._positive_parameter(
                context,
                "maximum_xml_bytes",
                32 * 1024 * 1024,
            ),
        )
        await context.report_progress(90.0)
        result = ParseResult(
            schema_version="1.0",
            task_id=context.lease.task_id,
            source=context.lease.source_metadata,
            metadata=metadata,
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
    def _extract(
        source: Path,
        mime_type: str,
        *,
        maximum_entries: int,
        maximum_uncompressed_bytes: int,
        maximum_xml_bytes: int,
    ) -> tuple[list[ContentBlock], ContentMetadata]:
        with _SafeOfficeArchive(
            source,
            maximum_entries=maximum_entries,
            maximum_uncompressed_bytes=maximum_uncompressed_bytes,
            maximum_xml_bytes=maximum_xml_bytes,
        ) as archive:
            archive.xml("[Content_Types].xml")
            suffix = source.suffix.casefold()
            if suffix == ".docx" or mime_type.endswith("wordprocessingml.document"):
                return _docx(archive)
            if suffix == ".pptx" or mime_type.endswith("presentationml.presentation"):
                return _pptx(archive)
            if suffix == ".xlsx" or mime_type.endswith("spreadsheetml.sheet"):
                return _xlsx(archive)
            raise BackendExecutionError("unsupported Office Open XML MIME type")

    @staticmethod
    def _positive_parameter(
        context: BackendContext,
        key: str,
        default: int,
    ) -> int:
        value = context.lease.parameters.get(key, default)
        if not isinstance(value, int) or isinstance(value, bool) or value < 1:
            raise BackendExecutionError(f"{key} must be a positive integer")
        return value


__all__ = ["OfficeOpenXmlBackend"]
