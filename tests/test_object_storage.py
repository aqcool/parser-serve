from __future__ import annotations

import tempfile
import unittest
from io import BytesIO
from pathlib import Path

from pydantic import AnyUrl

from parser_serve.backends import BackendExecutionError
from parser_serve.worker.object_storage import download_object_storage_source


class FakeBody:
    def __init__(self, content: bytes) -> None:
        self.content = BytesIO(content)
        self.closed = False

    def read(self, amount: int = -1) -> bytes:
        return self.content.read(amount)

    def close(self) -> None:
        self.closed = True
        self.content.close()


class FakeS3Client:
    def __init__(self, content: bytes, *, declared_length: int | None = None) -> None:
        self.content = content
        self.declared_length = (
            len(content) if declared_length is None else declared_length
        )
        self.arguments: dict[str, str] = {}
        self.body = FakeBody(content)

    def get_object(self, **kwargs: str) -> dict[str, object]:
        self.arguments = kwargs
        return {
            "ContentLength": self.declared_length,
            "Body": self.body,
        }


class ObjectStorageSourceTests(unittest.IsolatedAsyncioTestCase):
    async def test_downloads_allowlisted_versioned_object(self) -> None:
        client = FakeS3Client(b"object data")
        with tempfile.TemporaryDirectory() as temporary:
            destination = Path(temporary) / "source.txt"
            result = await download_object_storage_source(
                AnyUrl("s3://documents/path/source.txt"),
                destination,
                allowed_buckets={"documents"},
                maximum_bytes=1024,
                version_id="version-42",
                client=client,
            )
            self.assertEqual(result.read_bytes(), b"object data")
        self.assertEqual(
            client.arguments,
            {
                "Bucket": "documents",
                "Key": "path/source.txt",
                "VersionId": "version-42",
            },
        )
        self.assertTrue(client.body.closed)

    async def test_rejects_bucket_outside_allowlist_and_unsafe_key(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            destination = Path(temporary) / "source.txt"
            with self.assertRaisesRegex(BackendExecutionError, "allowlist"):
                await download_object_storage_source(
                    AnyUrl("s3://private/source.txt"),
                    destination,
                    allowed_buckets={"documents"},
                    maximum_bytes=1024,
                    client=FakeS3Client(b"data"),
                )
            with self.assertRaisesRegex(BackendExecutionError, "unsafe"):
                await download_object_storage_source(
                    AnyUrl("s3://documents/path/%5Csecret.txt"),
                    destination,
                    allowed_buckets={"documents"},
                    maximum_bytes=1024,
                    client=FakeS3Client(b"data"),
                )

    async def test_rejects_size_and_length_mismatch_without_partial_file(self) -> None:
        cases = [
            (FakeS3Client(b"x" * 20), 10, "size limit"),
            (FakeS3Client(b"short", declared_length=10), 20, "does not match"),
        ]
        for client, maximum, message in cases:
            with tempfile.TemporaryDirectory() as temporary:
                destination = Path(temporary) / "source.txt"
                with self.assertRaisesRegex(BackendExecutionError, message):
                    await download_object_storage_source(
                        AnyUrl("s3://documents/source.txt"),
                        destination,
                        allowed_buckets={"documents"},
                        maximum_bytes=maximum,
                        client=client,
                    )
                self.assertFalse(destination.exists())

    async def test_rejects_object_whose_signature_disagrees_with_metadata(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            destination = Path(temporary) / "photo.jpg"
            with self.assertRaisesRegex(BackendExecutionError, "signature"):
                await download_object_storage_source(
                    AnyUrl("s3://documents/photo.jpg"),
                    destination,
                    allowed_buckets={"documents"},
                    maximum_bytes=1024,
                    declared_mime_type="image/jpeg",
                    client=FakeS3Client(b"%PDF-1.7"),
                )
            self.assertFalse(destination.exists())


if __name__ == "__main__":
    unittest.main()
