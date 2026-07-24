from __future__ import annotations

import json
import tempfile
import unittest
import zipfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from parser_serve.backends import (
    BackendContext,
    BackendExecutionError,
    BackendRegistry,
    FFmpegBackend,
    ImageMetadataBackend,
    OfficeOpenXmlBackend,
    PdfBackend,
    StaticWebBackend,
    TextBackend,
    builtin_cpu_backends,
)
from parser_serve.schema.common import MediaCategory
from parser_serve.schema.base import JsonValue
from parser_serve.schema.hardware import DeviceRuntime
from parser_serve.schema.media import MediaProbe
from parser_serve.schema.result import LinkBlock, ParseResult, TableBlock, TextBlock
from parser_serve.schema.source import SourceMetadata, TextSource, UploadedFileSource
from parser_serve.schema.worker import LeasedStage
from parser_serve.schema.task import TaskOptions
from parser_serve.worker.preprocessors import LegacyOfficePreprocessor


NOW = datetime(2026, 7, 24, 12, 0, tzinfo=UTC)


def lease(
    *,
    backend_name: str,
    media_category: MediaCategory,
    mime_type: str,
    filename: str,
    source_text: str | None = None,
    parameters: dict[str, JsonValue] | None = None,
) -> LeasedStage:
    source = (
        TextSource(
            type="text", text=source_text, filename=filename, mime_type=mime_type
        )
        if source_text is not None
        else UploadedFileSource(type="uploaded_file", file_id="file_source123")
    )
    return LeasedStage(
        task_id="task_backend123",
        stage_id="stage_backend123",
        stage_name="parse",
        backend_id="backend_builtin123",
        backend_name=backend_name,
        backend_version="1.0",
        backend_candidates=["backend_builtin123"],
        runtime=DeviceRuntime.CPU,
        source=source,
        source_metadata=SourceMetadata(
            filename=filename,
            mime_type=mime_type,
            media_category=media_category,
        ),
        task_options=TaskOptions(),
        parameters=parameters or {},
        timeout_seconds=60,
        attempt=1,
        maximum_attempts=2,
        lease_token=f"lease_{'a' * 32}",
        lease_expires_at=NOW + timedelta(seconds=60),
    )


async def ignore_progress(_: float) -> None:
    return None


class BackendRegistryTests(unittest.TestCase):
    def test_builtin_cpu_registry_has_stable_capabilities(self) -> None:
        registry = builtin_cpu_backends(include_unavailable_system_tools=True)

        self.assertEqual(
            [capability.name for capability in registry.capabilities],
            [
                "builtin_ffmpeg",
                "builtin_image",
                "builtin_office",
                "builtin_pdf",
                "builtin_text",
                "builtin_web",
            ],
        )
        self.assertIsInstance(registry.get("builtin_text", "1.0"), TextBackend)
        with self.assertRaises(ValueError):
            registry.register(TextBackend())

    def test_empty_backend_output_is_rejected(self) -> None:
        registry = BackendRegistry()
        registry.register(TextBackend())
        self.assertEqual(len(registry.capabilities), 1)

    def test_unavailable_system_tools_are_not_advertised(self) -> None:
        with (
            patch("parser_serve.backends.ffmpeg_available", return_value=False),
            patch("parser_serve.backends.find_spec", return_value=None),
        ):
            registry = builtin_cpu_backends()

        self.assertEqual(
            [capability.name for capability in registry.capabilities],
            ["builtin_office", "builtin_text", "builtin_web"],
        )

    def test_registry_propagates_worker_resource_ceilings(self) -> None:
        registry = builtin_cpu_backends(
            include_unavailable_system_tools=True,
            maximum_pdf_pages=25,
            maximum_image_pixels=2_000_000,
            maximum_media_duration_seconds=600,
        )

        pdf = registry.get("builtin_pdf", "1.0")
        image = registry.get("builtin_image", "1.0")
        media = registry.get("builtin_ffmpeg", "1.0")
        self.assertIsInstance(pdf, PdfBackend)
        self.assertIsInstance(image, ImageMetadataBackend)
        self.assertIsInstance(media, FFmpegBackend)
        if isinstance(pdf, PdfBackend):
            self.assertEqual(pdf.maximum_pages, 25)
        if isinstance(image, ImageMetadataBackend):
            self.assertEqual(image.maximum_pixels, 2_000_000)
        if isinstance(media, FFmpegBackend):
            self.assertEqual(media.maximum_duration_seconds, 600)


class TextBackendTests(unittest.IsolatedAsyncioTestCase):
    async def test_parses_markdown_into_typed_result(self) -> None:
        progress: list[float] = []

        async def report(value: float) -> None:
            progress.append(value)

        with tempfile.TemporaryDirectory() as temporary:
            output = await TextBackend().execute(
                BackendContext(
                    lease=lease(
                        backend_name="builtin_text",
                        media_category=MediaCategory.TEXT,
                        mime_type="text/markdown",
                        filename="README.md",
                        source_text="# Title\n\nParagraph\n\n## Section",
                    ),
                    work_dir=Path(temporary),
                    source_path=None,
                    source_text="# Title\n\nParagraph\n\n## Section",
                    report_progress=report,
                )
            )

        self.assertEqual(progress, [10.0, 80.0])
        artifact = output.artifacts[0]
        self.assertIsNotNone(artifact.data)
        result = ParseResult.model_validate_json(artifact.data or b"")
        self.assertEqual(result.metadata.title, "Title")
        self.assertEqual(
            [block.type for block in result.blocks],
            ["heading", "text", "heading"],
        )
        self.assertEqual(result.metadata.attributes["character_count"], 30)

    async def test_reads_utf8_file(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "note.txt"
            source.write_text("你好", encoding="utf-8")
            output = await TextBackend().execute(
                BackendContext(
                    lease=lease(
                        backend_name="builtin_text",
                        media_category=MediaCategory.TEXT,
                        mime_type="text/plain",
                        filename="note.txt",
                    ),
                    work_dir=Path(temporary),
                    source_path=source,
                    source_text=None,
                    report_progress=ignore_progress,
                )
            )
        result = ParseResult.model_validate_json(output.artifacts[0].data or b"")
        self.assertIsInstance(result.blocks[0], TextBlock)
        if isinstance(result.blocks[0], TextBlock):
            self.assertEqual(result.blocks[0].text, "你好")


class SystemToolBackendTests(unittest.IsolatedAsyncioTestCase):
    async def test_libreoffice_preprocessor_returns_converted_file(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "legacy.doc"
            source.write_bytes(b"legacy")

            def convert(*_: object, **__: object) -> Path:
                converted = root / "converted" / "legacy.docx"
                converted.parent.mkdir()
                converted.write_bytes(b"modern")
                return converted

            with patch(
                "parser_serve.worker.preprocessors.convert_legacy_office",
                side_effect=convert,
            ):
                output = await LegacyOfficePreprocessor().prepare(
                    source,
                    work_dir=root,
                    timeout_seconds=60,
                )

            self.assertEqual(output.name, "legacy.docx")
            self.assertEqual(output.read_bytes(), b"modern")

    async def test_ffmpeg_backend_probe_and_audio_operations(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "video.mp4"
            source.write_bytes(b"video")
            probe_payload = MediaProbe(
                format_name="mov,mp4",
                duration_seconds=120.0,
            )
            with patch(
                "parser_serve.backends.media.probe_media",
                return_value=probe_payload,
            ):
                output = await FFmpegBackend().execute(
                    BackendContext(
                        lease=lease(
                            backend_name="builtin_ffmpeg",
                            media_category=MediaCategory.VIDEO,
                            mime_type="video/mp4",
                            filename="video.mp4",
                        ),
                        work_dir=root,
                        source_path=source,
                        source_text=None,
                        report_progress=ignore_progress,
                    )
                )
            self.assertEqual(
                json.loads(output.artifacts[0].data or b"{}")["format_name"],
                "mov,mp4",
            )

            def extract(*_: object, **__: object) -> Path:
                audio = root / "audio.wav"
                audio.write_bytes(b"wave")
                return audio

            with (
                patch(
                    "parser_serve.backends.media.probe_media",
                    return_value=probe_payload,
                ),
                patch(
                    "parser_serve.backends.media.extract_audio_track",
                    side_effect=extract,
                ),
            ):
                output = await FFmpegBackend().execute(
                    BackendContext(
                        lease=lease(
                            backend_name="builtin_ffmpeg",
                            media_category=MediaCategory.VIDEO,
                            mime_type="video/mp4",
                            filename="video.mp4",
                            parameters={
                                "operation": "extract_audio",
                                "sample_rate": 16_000,
                            },
                        ),
                        work_dir=root,
                        source_path=source,
                        source_text=None,
                        report_progress=ignore_progress,
                    )
                )
            self.assertEqual(output.artifacts[0].filename, "audio.wav")

    async def test_worker_resource_ceilings_cannot_be_relaxed_by_pipeline(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source.bin"
            source.write_bytes(b"source")

            with self.assertRaisesRegex(
                BackendExecutionError,
                "Worker limit 10",
            ):
                await PdfBackend(maximum_pages=10).execute(
                    BackendContext(
                        lease=lease(
                            backend_name="builtin_pdf",
                            media_category=MediaCategory.DOCUMENT,
                            mime_type="application/pdf",
                            filename="source.pdf",
                            parameters={"maximum_pages": 11},
                        ),
                        work_dir=root,
                        source_path=source,
                        source_text=None,
                        report_progress=ignore_progress,
                    )
                )

            with self.assertRaisesRegex(
                BackendExecutionError,
                "Worker limit 1000",
            ):
                await ImageMetadataBackend(maximum_pixels=1000).execute(
                    BackendContext(
                        lease=lease(
                            backend_name="builtin_image",
                            media_category=MediaCategory.IMAGE,
                            mime_type="image/png",
                            filename="source.png",
                            parameters={"maximum_pixels": 1001},
                        ),
                        work_dir=root,
                        source_path=source,
                        source_text=None,
                        report_progress=ignore_progress,
                    )
                )

            with (
                patch(
                    "parser_serve.backends.media.probe_media",
                    return_value=MediaProbe(duration_seconds=61.0),
                ),
                self.assertRaisesRegex(
                    BackendExecutionError,
                    "Worker limit is 60 seconds",
                ),
            ):
                await FFmpegBackend(maximum_duration_seconds=60).execute(
                    BackendContext(
                        lease=lease(
                            backend_name="builtin_ffmpeg",
                            media_category=MediaCategory.VIDEO,
                            mime_type="video/mp4",
                            filename="source.mp4",
                        ),
                        work_dir=root,
                        source_path=source,
                        source_text=None,
                        report_progress=ignore_progress,
                    )
                )


class BasicContentBackendTests(unittest.IsolatedAsyncioTestCase):
    async def execute_office(
        self,
        *,
        filename: str,
        mime_type: str,
        members: dict[str, str],
        parameters: dict[str, JsonValue] | None = None,
    ) -> ParseResult:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / filename
            with zipfile.ZipFile(source, "w", zipfile.ZIP_DEFLATED) as archive:
                if "[Content_Types].xml" not in members:
                    archive.writestr(
                        "[Content_Types].xml",
                        (
                            '<Types xmlns="http://schemas.openxmlformats.org/'
                            'package/2006/content-types"/>'
                        ),
                    )
                for name, content in members.items():
                    archive.writestr(name, content)
            output = await OfficeOpenXmlBackend().execute(
                BackendContext(
                    lease=lease(
                        backend_name="builtin_office",
                        media_category=MediaCategory.DOCUMENT,
                        mime_type=mime_type,
                        filename=filename,
                        parameters=parameters,
                    ),
                    work_dir=root,
                    source_path=source,
                    source_text=None,
                    report_progress=ignore_progress,
                )
            )
        return ParseResult.model_validate_json(output.artifacts[0].data or b"")

    async def test_office_backend_extracts_docx_paragraphs_and_tables(self) -> None:
        result = await self.execute_office(
            filename="report.docx",
            mime_type=(
                "application/vnd.openxmlformats-officedocument."
                "wordprocessingml.document"
            ),
            members={
                "word/document.xml": """
                    <w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
                      <w:body>
                        <w:p><w:r><w:t>Hello Office</w:t></w:r></w:p>
                        <w:tbl><w:tr>
                          <w:tc><w:p><w:r><w:t>Name</w:t></w:r></w:p></w:tc>
                          <w:tc><w:p><w:r><w:t>Value</w:t></w:r></w:p></w:tc>
                        </w:tr></w:tbl>
                      </w:body>
                    </w:document>
                """,
                "docProps/core.xml": """
                    <cp:coreProperties
                      xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties"
                      xmlns:dc="http://purl.org/dc/elements/1.1/">
                      <dc:title>Quarterly Report</dc:title>
                    </cp:coreProperties>
                """,
            },
        )
        self.assertEqual(result.metadata.title, "Quarterly Report")
        self.assertIsInstance(result.blocks[0], TextBlock)
        self.assertIsInstance(result.blocks[1], TableBlock)
        if isinstance(result.blocks[1], TableBlock):
            self.assertEqual(result.blocks[1].rows, [["Name", "Value"]])

    async def test_office_backend_extracts_pptx_slides(self) -> None:
        result = await self.execute_office(
            filename="deck.pptx",
            mime_type=(
                "application/vnd.openxmlformats-officedocument."
                "presentationml.presentation"
            ),
            members={
                "ppt/slides/slide2.xml": """
                  <p:sld xmlns:p="urn:p" xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">
                    <a:t>Second slide</a:t>
                  </p:sld>
                """,
                "ppt/slides/slide1.xml": """
                  <p:sld xmlns:p="urn:p" xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">
                    <a:t>Title</a:t><a:t>First slide</a:t>
                  </p:sld>
                """,
            },
        )
        self.assertEqual(result.metadata.attributes["slide_count"], 2)
        self.assertEqual(
            [
                block.location.slide_number
                for block in result.blocks
                if isinstance(block, TextBlock) and block.location
            ],
            [1, 2],
        )

    async def test_office_backend_extracts_xlsx_shared_and_inline_cells(self) -> None:
        result = await self.execute_office(
            filename="data.xlsx",
            mime_type=(
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            ),
            members={
                "xl/workbook.xml": """
                  <workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"
                    xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
                    <sheets><sheet name="Data" sheetId="1" r:id="rId1"/></sheets>
                  </workbook>
                """,
                "xl/_rels/workbook.xml.rels": """
                  <Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
                    <Relationship Id="rId1" Target="worksheets/sheet1.xml"/>
                  </Relationships>
                """,
                "xl/sharedStrings.xml": """
                  <sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
                    <si><t>Name</t></si><si><t>Alice</t></si>
                  </sst>
                """,
                "xl/worksheets/sheet1.xml": """
                  <worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
                    <sheetData>
                      <row r="1"><c r="A1" t="s"><v>0</v></c><c r="B1" t="inlineStr"><is><t>Score</t></is></c></row>
                      <row r="2"><c r="A2" t="s"><v>1</v></c><c r="B2"><v>98</v></c></row>
                    </sheetData>
                  </worksheet>
                """,
            },
        )
        self.assertIsInstance(result.blocks[0], TableBlock)
        if isinstance(result.blocks[0], TableBlock):
            self.assertEqual(
                result.blocks[0].rows,
                [["Name", "Score"], ["Alice", "98"]],
            )
            self.assertIsNotNone(result.blocks[0].location)
            if result.blocks[0].location is not None:
                self.assertEqual(result.blocks[0].location.sheet_name, "Data")

    async def test_office_backend_rejects_unsafe_or_oversized_archives(self) -> None:
        with self.assertRaisesRegex(
            Exception,
            "uncompressed size limit",
        ):
            await self.execute_office(
                filename="large.docx",
                mime_type=(
                    "application/vnd.openxmlformats-officedocument."
                    "wordprocessingml.document"
                ),
                members={"word/document.xml": "<root>" + ("x" * 1000) + "</root>"},
                parameters={"maximum_uncompressed_bytes": 100},
            )
        with self.assertRaisesRegex(Exception, "unsafe entry"):
            await self.execute_office(
                filename="unsafe.docx",
                mime_type=(
                    "application/vnd.openxmlformats-officedocument."
                    "wordprocessingml.document"
                ),
                members={
                    "../escape.xml": "<escape/>",
                    "word/document.xml": (
                        '<w:document xmlns:w="'
                        "http://schemas.openxmlformats.org/"
                        'wordprocessingml/2006/main"><w:body/></w:document>'
                    ),
                },
            )
        with self.assertRaisesRegex(Exception, "suspicious compression ratio"):
            await self.execute_office(
                filename="bomb.docx",
                mime_type=(
                    "application/vnd.openxmlformats-officedocument."
                    "wordprocessingml.document"
                ),
                members={"word/document.xml": "0" * 2_000_000},
                parameters={"maximum_uncompressed_bytes": 3_000_000},
            )

    async def test_pdf_backend_creates_page_blocks(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "document.pdf"
            source.write_bytes(b"%PDF")
            with patch(
                "parser_serve.backends.pdf._extract_pdf",
                return_value=(["first page", "", "third page"], {"Title": "Report"}),
            ):
                output = await PdfBackend().execute(
                    BackendContext(
                        lease=lease(
                            backend_name="builtin_pdf",
                            media_category=MediaCategory.DOCUMENT,
                            mime_type="application/pdf",
                            filename="document.pdf",
                        ),
                        work_dir=root,
                        source_path=source,
                        source_text=None,
                        report_progress=ignore_progress,
                    )
                )
        result = ParseResult.model_validate_json(output.artifacts[0].data or b"")
        self.assertEqual(result.metadata.title, "Report")
        self.assertEqual(result.metadata.page_count, 3)
        self.assertEqual(len(result.blocks), 2)
        for block, page_number in zip(result.blocks, (1, 3), strict=True):
            self.assertIsInstance(block, TextBlock)
            if isinstance(block, TextBlock):
                self.assertIsNotNone(block.location)
                if block.location is not None:
                    self.assertEqual(block.location.page_number, page_number)

    async def test_image_backend_creates_dimensions_and_exif(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "photo.jpg"
            source.write_bytes(b"image")
            with patch(
                "parser_serve.backends.image._image_metadata",
                return_value=(
                    4032,
                    3024,
                    {
                        "format": "JPEG",
                        "mode": "RGB",
                        "exif": {"Make": "Camera"},
                    },
                ),
            ):
                output = await ImageMetadataBackend().execute(
                    BackendContext(
                        lease=lease(
                            backend_name="builtin_image",
                            media_category=MediaCategory.IMAGE,
                            mime_type="image/jpeg",
                            filename="photo.jpg",
                        ),
                        work_dir=root,
                        source_path=source,
                        source_text=None,
                        report_progress=ignore_progress,
                    )
                )
        result = ParseResult.model_validate_json(output.artifacts[0].data or b"")
        self.assertEqual(result.metadata.width_pixels, 4032)
        self.assertEqual(result.metadata.height_pixels, 3024)
        self.assertEqual(
            result.metadata.attributes["exif"],
            {"Make": "Camera"},
        )

    async def test_static_web_backend_ignores_scripts_and_extracts_links(self) -> None:
        html = """
        <html><head><title>Example</title><style>hidden</style></head>
        <body><h1>Hello</h1><script>ignored()</script>
        <a href="/docs">Documentation</a></body></html>
        """
        with tempfile.TemporaryDirectory() as temporary:
            output = await StaticWebBackend().execute(
                BackendContext(
                    lease=lease(
                        backend_name="builtin_web",
                        media_category=MediaCategory.WEB,
                        mime_type="text/html",
                        filename="page.html",
                        source_text=html,
                        parameters={"base_url": "https://example.com/root"},
                    ),
                    work_dir=Path(temporary),
                    source_path=None,
                    source_text=html,
                    report_progress=ignore_progress,
                )
            )
        result = ParseResult.model_validate_json(output.artifacts[0].data or b"")
        self.assertEqual(result.metadata.title, "Example")
        self.assertEqual(result.metadata.attributes["link_count"], 1)
        self.assertIsInstance(result.blocks[0], TextBlock)
        if isinstance(result.blocks[0], TextBlock):
            self.assertNotIn("ignored", result.blocks[0].text)
        self.assertIsInstance(result.blocks[1], LinkBlock)
        if isinstance(result.blocks[1], LinkBlock):
            self.assertEqual(str(result.blocks[1].url), "https://example.com/docs")


if __name__ == "__main__":
    unittest.main()
