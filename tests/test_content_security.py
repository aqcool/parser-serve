from __future__ import annotations

import hashlib
import tempfile
import unittest
from pathlib import Path

import httpx

from parser_serve.schema.common import MediaCategory
from parser_serve.schema.content import ContentContainer
from parser_serve.security import ContentValidationError, inspect_content
from parser_serve.worker import ControlPlaneError, HttpWorkerControlClient


class ContentInspectionTests(unittest.TestCase):
    def test_recognizes_supported_binary_families(self) -> None:
        cases = [
            (
                "paper.pdf",
                "application/pdf",
                b"%PDF-1.7\n",
                MediaCategory.DOCUMENT,
                "application/pdf",
            ),
            (
                "legacy.doc",
                "application/msword",
                b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1",
                MediaCategory.DOCUMENT,
                "application/msword",
            ),
            (
                "report.docx",
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                b"PK\x03\x04container",
                MediaCategory.DOCUMENT,
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            ),
            (
                "photo.png",
                "image/png",
                b"\x89PNG\r\n\x1a\ncontent",
                MediaCategory.IMAGE,
                "image/png",
            ),
            (
                "speech.wav",
                "audio/wav",
                b"RIFF\x10\x00\x00\x00WAVEcontent",
                MediaCategory.AUDIO,
                "audio/wav",
            ),
            (
                "video.mp4",
                "video/mp4",
                b"\x00\x00\x00\x18ftypisomcontent",
                MediaCategory.VIDEO,
                "video/mp4",
            ),
        ]
        for filename, declared, sample, category, detected in cases:
            with self.subTest(filename=filename):
                inspection = inspect_content(
                    filename=filename,
                    declared_mime_type=declared,
                    sample=sample,
                )
                self.assertEqual(inspection.media_category, category)
                self.assertEqual(inspection.detected_mime_type, detected)

    def test_recognizes_utf8_text_and_html(self) -> None:
        text = inspect_content(
            filename="notes.md",
            declared_mime_type="text/markdown",
            sample="# 标题".encode(),
        )
        html = inspect_content(
            filename="page.html",
            declared_mime_type="text/html",
            sample=b"<!doctype html><html></html>",
        )

        self.assertTrue(text.textual)
        self.assertEqual(text.media_category, MediaCategory.TEXT)
        self.assertTrue(html.textual)
        self.assertEqual(html.media_category, MediaCategory.WEB)

    def test_rejects_extension_mime_and_signature_mismatches(self) -> None:
        cases = [
            ("photo.jpg", "image/jpeg", b"%PDF-1.7"),
            ("paper.pdf", "image/png", b"%PDF-1.7"),
            ("page.html", "text/html", b"plain text without markup"),
            ("notes.txt", "text/plain", b"\x00\x01\x02"),
            ("empty.txt", "text/plain", b""),
        ]
        for filename, declared, sample in cases:
            with self.subTest(filename=filename):
                with self.assertRaises(ContentValidationError):
                    inspect_content(
                        filename=filename,
                        declared_mime_type=declared,
                        sample=sample,
                    )

    def test_reports_container_for_archive_and_media_formats(self) -> None:
        archive = inspect_content(
            filename="book.epub",
            declared_mime_type="application/epub+zip",
            sample=b"PK\x03\x04book",
        )
        video = inspect_content(
            filename="clip.mkv",
            declared_mime_type="video/x-matroska",
            sample=b"\x1aE\xdf\xa3content",
        )

        self.assertEqual(archive.container, ContentContainer.ZIP)
        self.assertEqual(video.container, ContentContainer.MATROSKA)


class WorkerSourceIntegrityTests(unittest.IsolatedAsyncioTestCase):
    async def test_download_validates_headers_size_and_sha256(self) -> None:
        content = b"# trusted"
        digest = hashlib.sha256(content).hexdigest()

        def handler(_: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                headers={
                    "Content-Length": str(len(content)),
                    "X-Content-SHA256": digest,
                },
                content=content,
            )

        http = httpx.AsyncClient(
            transport=httpx.MockTransport(handler),
            base_url="http://control.internal",
        )
        client = HttpWorkerControlClient(
            base_url="http://control.internal",
            api_key=f"parser_{'i' * 32}",
            client=http,
        )
        try:
            with tempfile.TemporaryDirectory() as temporary:
                destination = Path(temporary) / "source.md"
                result = await client.download_source(
                    worker_id="worker_integrity",
                    file_id="file_integrity",
                    destination=destination,
                    expected_size_bytes=len(content),
                    expected_sha256=digest,
                )
                self.assertEqual(result.read_bytes(), content)
        finally:
            await http.aclose()

    async def test_download_rejects_integrity_mismatch_without_partial_file(
        self,
    ) -> None:
        content = b"tampered"
        expected_digest = hashlib.sha256(b"expected").hexdigest()

        def handler(_: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                headers={
                    "Content-Length": str(len(content)),
                    "X-Content-SHA256": expected_digest,
                },
                content=content,
            )

        http = httpx.AsyncClient(
            transport=httpx.MockTransport(handler),
            base_url="http://control.internal",
        )
        client = HttpWorkerControlClient(
            base_url="http://control.internal",
            api_key=f"parser_{'i' * 32}",
            client=http,
        )
        try:
            with tempfile.TemporaryDirectory() as temporary:
                destination = Path(temporary) / "source.md"
                with self.assertRaisesRegex(ControlPlaneError, "integrity"):
                    await client.download_source(
                        worker_id="worker_integrity",
                        file_id="file_integrity",
                        destination=destination,
                        expected_size_bytes=len(content),
                        expected_sha256=expected_digest,
                    )
                self.assertFalse(destination.exists())
        finally:
            await http.aclose()


if __name__ == "__main__":
    unittest.main()
