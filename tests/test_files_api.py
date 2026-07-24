from __future__ import annotations

import asyncio
import hashlib
import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
from pydantic import SecretStr

from parser_serve.api import create_app
from parser_serve.persistence import Database
from parser_serve.persistence.files import ArtifactRepository
from parser_serve.schema.artifact import (
    ArtifactDownloadResponse,
    ArtifactListResponse,
    ArtifactType,
)
from parser_serve.schema.error import ErrorCode
from parser_serve.schema.file import UploadedFileResponse
from parser_serve.schema.task import CreateTaskResponse, TaskDetailResponse
from parser_serve.settings import Environment, Settings
from parser_serve.storage import LocalFileStorage


NOW = datetime(2026, 7, 24, 12, 0, tzinfo=UTC)
API_KEY = f"parser_{'f' * 32}"
AUTH_HEADERS = {"Authorization": f"Bearer {API_KEY}"}
LEGACY_WORD_CONTENT = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1legacy"


class FileApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        root = Path(self.temporary_directory.name)
        self.storage_root = root / "objects"
        self.database = Database(f"sqlite+aiosqlite:///{root / 'files.sqlite3'}")
        asyncio.run(self.database.create_schema_for_testing())
        self.storage = LocalFileStorage(self.storage_root)
        self.client = TestClient(
            create_app(
                Settings(
                    environment=Environment.TEST,
                    api_keys=[SecretStr(API_KEY)],
                    maximum_upload_bytes=16,
                ),
                clock=lambda: NOW,
                database=self.database,
                storage=self.storage,
            )
        )

    def tearDown(self) -> None:
        self.client.close()
        asyncio.run(self.database.dispose())
        self.temporary_directory.cleanup()

    def upload(
        self,
        *,
        filename: str = "legacy.doc",
        content: bytes = LEGACY_WORD_CONTENT,
        mime_type: str = "application/msword",
    ) -> UploadedFileResponse:
        response = self.client.post(
            "/api/v1/files",
            headers=AUTH_HEADERS,
            files={"file": (filename, content, mime_type)},
        )
        self.assertEqual(response.status_code, 201, response.text)
        return UploadedFileResponse.model_validate_json(response.content)

    def test_upload_metadata_download_and_task_source_resolution(self) -> None:
        content = LEGACY_WORD_CONTENT
        uploaded = self.upload(content=content)

        self.assertEqual(uploaded.data.filename, "legacy.doc")
        self.assertEqual(uploaded.data.media_category, "document")
        self.assertEqual(uploaded.data.size_bytes, len(content))
        self.assertEqual(
            uploaded.data.sha256,
            hashlib.sha256(content).hexdigest(),
        )

        response = self.client.get(
            f"/api/v1/files/{uploaded.data.file_id}",
            headers=AUTH_HEADERS,
        )
        self.assertEqual(response.status_code, 200)
        metadata = UploadedFileResponse.model_validate_json(response.content)
        self.assertEqual(metadata.data, uploaded.data)

        response = self.client.get(
            f"/api/v1/files/{uploaded.data.file_id}/content",
            headers=AUTH_HEADERS,
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, content)
        self.assertEqual(response.headers["content-type"], "application/msword")
        self.assertIn(
            "filename*=UTF-8''legacy.doc", response.headers["content-disposition"]
        )

        response = self.client.post(
            "/api/v1/tasks",
            headers=AUTH_HEADERS,
            json={
                "source": {
                    "type": "uploaded_file",
                    "file_id": uploaded.data.file_id,
                }
            },
        )
        self.assertEqual(response.status_code, 201, response.text)
        task = CreateTaskResponse.model_validate_json(response.content)
        response = self.client.get(
            f"/api/v1/tasks/{task.data.task_id}",
            headers=AUTH_HEADERS,
        )
        detail = TaskDetailResponse.model_validate_json(response.content)
        self.assertIsNotNone(detail.data.source_metadata)
        if detail.data.source_metadata is not None:
            self.assertEqual(detail.data.source_metadata.filename, "legacy.doc")
            self.assertEqual(detail.data.source_metadata.sha256, uploaded.data.sha256)
            self.assertEqual(detail.data.source_metadata.media_category, "document")

    def test_rejects_oversized_and_unsupported_uploads_without_partial_files(
        self,
    ) -> None:
        response = self.client.post(
            "/api/v1/files",
            headers=AUTH_HEADERS,
            files={"file": ("large.mp4", b"x" * 17, "video/mp4")},
        )
        self.assertEqual(response.status_code, 413)
        self.assertEqual(response.json()["error"]["code"], ErrorCode.FILE_TOO_LARGE)

        response = self.client.post(
            "/api/v1/files",
            headers=AUTH_HEADERS,
            files={
                "file": (
                    "payload.unknown",
                    b"unknown",
                    "application/octet-stream",
                )
            },
        )
        self.assertEqual(response.status_code, 415)
        self.assertEqual(
            response.json()["error"]["code"],
            ErrorCode.UNSUPPORTED_MEDIA_TYPE,
        )

        response = self.client.post(
            "/api/v1/files",
            headers=AUTH_HEADERS,
            files={"file": ("photo.jpg", b"%PDF-1.7", "image/jpeg")},
        )
        self.assertEqual(response.status_code, 415)
        self.assertIn("signature", response.json()["error"]["message"])
        self.assertEqual(
            [path for path in self.storage_root.rglob("*") if path.is_file()],
            [],
        )

    def test_missing_file_reference_and_artifact_listing(self) -> None:
        response = self.client.post(
            "/api/v1/tasks",
            headers=AUTH_HEADERS,
            json={
                "source": {
                    "type": "uploaded_file",
                    "file_id": "file_missing12",
                }
            },
        )
        self.assertEqual(response.status_code, 404)

        response = self.client.post(
            "/api/v1/tasks",
            headers=AUTH_HEADERS,
            json={"source": {"type": "text", "text": "artifact owner"}},
        )
        task = CreateTaskResponse.model_validate_json(response.content)

        async def create_artifact() -> None:
            async def content():
                yield b"result"

            stored = await self.storage.write(
                "artifacts/result",
                content(),
                maximum_bytes=16,
            )
            async with self.database.session_factory() as session:
                await ArtifactRepository().create(
                    session,
                    task_id=task.data.task_id,
                    artifact_type=ArtifactType.RESULT_TEXT,
                    filename="result.txt",
                    mime_type="text/plain",
                    stored=stored,
                    now=NOW,
                    metadata={"language": "zh"},
                )
                await session.commit()

        asyncio.run(create_artifact())
        response = self.client.get(
            f"/api/v1/tasks/{task.data.task_id}/artifacts",
            headers=AUTH_HEADERS,
        )
        listing = ArtifactListResponse.model_validate_json(response.content)
        self.assertEqual(len(listing.items), 1)
        self.assertEqual(listing.items[0].filename, "result.txt")
        self.assertEqual(listing.items[0].metadata, {"language": "zh"})

        response = self.client.get(
            (
                f"/api/v1/tasks/{task.data.task_id}/artifacts/"
                f"{listing.items[0].artifact_id}/download-url"
            ),
            headers=AUTH_HEADERS,
        )
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["error"]["code"], ErrorCode.CONFLICT)

        async def signed_url(
            storage: LocalFileStorage,
            key: str,
            *,
            expires_seconds: int,
        ) -> str:
            self.assertEqual(key, "artifacts/result")
            self.assertEqual(expires_seconds, 300)
            return "https://objects.example/result?signature=test"

        with patch.object(
            LocalFileStorage,
            "presign_get",
            new=signed_url,
        ):
            response = self.client.get(
                (
                    f"/api/v1/tasks/{task.data.task_id}/artifacts/"
                    f"{listing.items[0].artifact_id}/download-url"
                ),
                headers=AUTH_HEADERS,
            )
        self.assertEqual(response.status_code, 200)
        download = ArtifactDownloadResponse.model_validate_json(response.content)
        self.assertEqual(download.data.method, "GET")
        self.assertEqual(download.data.expires_at, NOW + timedelta(seconds=300))

    def test_artifact_listing_supports_filter_sort_and_stable_cursor(self) -> None:
        response = self.client.post(
            "/api/v1/tasks",
            headers=AUTH_HEADERS,
            json={"source": {"type": "text", "text": "artifact pages"}},
        )
        task = CreateTaskResponse.model_validate_json(response.content)

        async def create_artifacts() -> None:
            for index, (filename, artifact_type, content) in enumerate(
                [
                    ("charlie.txt", ArtifactType.RESULT_TEXT, b"ccc"),
                    ("alpha.md", ArtifactType.RESULT_MARKDOWN, b"a"),
                    ("bravo.txt", ArtifactType.RESULT_TEXT, b"bb"),
                ]
            ):

                async def stream(payload: bytes = content):
                    yield payload

                stored = await self.storage.write(
                    f"artifacts/page-{index}",
                    stream(),
                    maximum_bytes=16,
                )
                async with self.database.session_factory() as session:
                    await ArtifactRepository().create(
                        session,
                        task_id=task.data.task_id,
                        artifact_type=artifact_type,
                        filename=filename,
                        mime_type=(
                            "text/markdown"
                            if artifact_type is ArtifactType.RESULT_MARKDOWN
                            else "text/plain"
                        ),
                        stored=stored,
                        now=NOW + timedelta(seconds=index),
                    )
                    await session.commit()

        asyncio.run(create_artifacts())
        response = self.client.get(
            f"/api/v1/tasks/{task.data.task_id}/artifacts",
            headers=AUTH_HEADERS,
            params={
                "types": "result_text",
                "sort_by": "filename",
                "sort_direction": "asc",
                "limit": 1,
            },
        )
        first_page = ArtifactListResponse.model_validate_json(response.content)
        self.assertEqual([item.filename for item in first_page.items], ["bravo.txt"])
        self.assertTrue(first_page.page.has_more)

        response = self.client.get(
            f"/api/v1/tasks/{task.data.task_id}/artifacts",
            headers=AUTH_HEADERS,
            params={
                "types": "result_text",
                "sort_by": "filename",
                "sort_direction": "asc",
                "limit": 1,
                "cursor": first_page.page.next_cursor,
            },
        )
        second_page = ArtifactListResponse.model_validate_json(response.content)
        self.assertEqual([item.filename for item in second_page.items], ["charlie.txt"])
        self.assertFalse(second_page.page.has_more)

        response = self.client.get(
            f"/api/v1/tasks/{task.data.task_id}/artifacts",
            headers=AUTH_HEADERS,
            params={
                "sort_by": "size_bytes",
                "cursor": first_page.page.next_cursor,
            },
        )
        self.assertEqual(response.status_code, 422)


if __name__ == "__main__":
    unittest.main()
