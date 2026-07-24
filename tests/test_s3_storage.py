from __future__ import annotations

import io
import unittest
from collections.abc import AsyncIterator
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from parser_serve.api import create_app
from parser_serve.settings import Environment, Settings, StorageBackend
from parser_serve.storage import (
    S3Storage,
    StorageObjectNotFoundError,
    StorageObjectTooLargeError,
)


async def chunks(*values: bytes) -> AsyncIterator[bytes]:
    for value in values:
        yield value


class FakeS3Error(Exception):
    def __init__(self, code: str) -> None:
        self.response = {"Error": {"Code": code}}


class FakeBody(io.BytesIO):
    closed_by_storage = False

    def close(self) -> None:
        self.closed_by_storage = True
        super().close()


class FakeS3Client:
    def __init__(self) -> None:
        self.objects: dict[tuple[str, str], bytes] = {}
        self.metadata: dict[tuple[str, str], dict[str, str]] = {}
        self.last_body: FakeBody | None = None

    def upload_file(
        self,
        filename: str,
        bucket: str,
        key: str,
        *,
        ExtraArgs: dict[str, dict[str, str]],
    ) -> None:
        self.objects[(bucket, key)] = Path(filename).read_bytes()
        self.metadata[(bucket, key)] = ExtraArgs["Metadata"]

    def get_object(self, *, Bucket: str, Key: str) -> dict[str, FakeBody]:
        try:
            content = self.objects[(Bucket, Key)]
        except KeyError as exc:
            raise FakeS3Error("NoSuchKey") from exc
        self.last_body = FakeBody(content)
        return {"Body": self.last_body}

    def head_object(self, *, Bucket: str, Key: str) -> dict[str, object]:
        if (Bucket, Key) not in self.objects:
            raise FakeS3Error("404")
        return {}

    def delete_object(self, *, Bucket: str, Key: str) -> dict[str, object]:
        self.objects.pop((Bucket, Key), None)
        return {}

    def generate_presigned_url(
        self,
        operation: str,
        *,
        Params: dict[str, str],
        ExpiresIn: int,
        HttpMethod: str,
    ) -> str:
        return (
            f"https://objects.example/{Params['Bucket']}/{Params['Key']}"
            f"?operation={operation}&expires={ExpiresIn}&method={HttpMethod}"
        )


class S3StorageTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.client = FakeS3Client()
        self.storage = S3Storage(
            bucket="parser-test",
            prefix="tenant-a/parser",
            client=self.client,
        )

    async def test_streams_write_read_exists_and_delete(self) -> None:
        stored = await self.storage.write(
            "uploads/file_12345678",
            chunks(b"hello", b"", b" world"),
            maximum_bytes=32,
        )

        self.assertEqual(stored.key, "uploads/file_12345678")
        self.assertEqual(
            stored.uri,
            "s3://parser-test/tenant-a/parser/uploads/file_12345678",
        )
        self.assertEqual(stored.size_bytes, 11)
        self.assertEqual(
            self.client.metadata[
                ("parser-test", "tenant-a/parser/uploads/file_12345678")
            ]["parser-serve-sha256"],
            stored.sha256,
        )
        self.assertTrue(await self.storage.exists(stored.key))
        content = b"".join(
            [chunk async for chunk in self.storage.read(stored.key, chunk_size=3)]
        )
        self.assertEqual(content, b"hello world")
        self.assertIsNotNone(self.client.last_body)
        if self.client.last_body is not None:
            self.assertTrue(self.client.last_body.closed_by_storage)
        await self.storage.delete(stored.key)
        self.assertFalse(await self.storage.exists(stored.key))

    async def test_rejects_traversal_keys_before_contacting_s3(self) -> None:
        for key in ("../escape", "/absolute", "a/../../escape", r"a\escape"):
            with self.subTest(key=key), self.assertRaises(ValueError):
                await self.storage.write(
                    key,
                    chunks(b"content"),
                    maximum_bytes=100,
                )
        self.assertEqual(self.client.metadata, {})

    async def test_generates_bounded_get_url(self) -> None:
        url = await self.storage.presign_get("artifacts/result", expires_seconds=300)

        self.assertEqual(
            url,
            "https://objects.example/parser-test/tenant-a/parser/artifacts/result"
            "?operation=get_object&expires=300&method=GET",
        )
        with self.assertRaises(ValueError):
            await self.storage.presign_get("artifacts/result", expires_seconds=0)

    async def test_missing_read_and_invalid_keys_are_rejected(self) -> None:
        with self.assertRaises(StorageObjectNotFoundError):
            _ = b"".join([chunk async for chunk in self.storage.read("missing")])
        for invalid in ("", "../secret", "/absolute", r"folder\file"):
            with self.subTest(key=invalid), self.assertRaises(ValueError):
                await self.storage.exists(invalid)

    async def test_size_and_stream_type_limits_prevent_upload(self) -> None:
        with self.assertRaises(StorageObjectTooLargeError):
            await self.storage.write("large", chunks(b"123", b"456"), maximum_bytes=5)
        self.assertEqual(self.client.objects, {})

        async def invalid() -> AsyncIterator[bytes]:
            yield "not bytes"  # type: ignore[misc]

        with self.assertRaises(TypeError):
            await self.storage.write("invalid", invalid(), maximum_bytes=10)
        self.assertEqual(self.client.objects, {})

    async def test_non_not_found_errors_are_not_hidden(self) -> None:
        class FailingClient(FakeS3Client):
            def head_object(self, *, Bucket: str, Key: str) -> dict[str, object]:
                raise FakeS3Error("AccessDenied")

        storage = S3Storage(bucket="parser-test", client=FailingClient())
        with self.assertRaises(FakeS3Error):
            await storage.exists("file")


class S3StorageSettingsTests(unittest.TestCase):
    def test_s3_settings_require_bucket(self) -> None:
        with self.assertRaisesRegex(ValueError, "s3_storage_bucket"):
            Settings(storage_backend=StorageBackend.S3)

    def test_application_factory_selects_s3_backend(self) -> None:
        sentinel = S3Storage(
            bucket="sentinel",
            client=FakeS3Client(),
        )
        with (
            TemporaryDirectory() as temporary,
            patch(
                "parser_serve.api.app.S3Storage",
                return_value=sentinel,
            ) as constructor,
        ):
            app = create_app(
                Settings(
                    environment=Environment.TEST,
                    storage_backend=StorageBackend.S3,
                    s3_storage_bucket="parser-data",
                    s3_storage_prefix="environment/test",
                    local_storage_path=Path(temporary),
                )
            )

        self.assertIs(app.state.storage, sentinel)
        constructor.assert_called_once_with(
            bucket="parser-data",
            prefix="environment/test",
            endpoint_url=None,
            region_name=None,
        )


if __name__ == "__main__":
    unittest.main()
