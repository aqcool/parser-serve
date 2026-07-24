from __future__ import annotations

import hashlib
import tempfile
import unittest
from collections.abc import AsyncIterator
from pathlib import Path

from parser_serve.storage import (
    LocalFileStorage,
    StorageObjectTooLargeError,
)


async def chunks(*values: bytes) -> AsyncIterator[bytes]:
    for value in values:
        yield value


class LocalFileStorageTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_directory.name)
        self.storage = LocalFileStorage(self.root)

    async def asyncTearDown(self) -> None:
        self.temporary_directory.cleanup()

    async def test_atomically_writes_hashes_reads_and_deletes(self) -> None:
        stored = await self.storage.write(
            "uploads/ab/file_abcdefgh",
            chunks(b"hello", b" ", b"world"),
            maximum_bytes=100,
        )

        self.assertEqual(stored.size_bytes, 11)
        self.assertEqual(stored.sha256, hashlib.sha256(b"hello world").hexdigest())
        self.assertEqual(
            stored.uri,
            "local:///uploads/ab/file_abcdefgh",
        )
        self.assertTrue(await self.storage.exists(stored.key))
        content = b"".join([part async for part in self.storage.read(stored.key)])
        self.assertEqual(content, b"hello world")

        await self.storage.delete(stored.key)
        self.assertFalse(await self.storage.exists(stored.key))

    async def test_rejects_traversal_keys(self) -> None:
        for key in ("../escape", "/absolute", "a/../../escape", r"a\escape"):
            with self.subTest(key=key), self.assertRaises(ValueError):
                await self.storage.write(
                    key,
                    chunks(b"content"),
                    maximum_bytes=100,
                )

    async def test_size_limit_removes_partial_object(self) -> None:
        with self.assertRaises(StorageObjectTooLargeError):
            await self.storage.write(
                "uploads/large",
                chunks(b"1234", b"5678"),
                maximum_bytes=6,
            )

        self.assertFalse(await self.storage.exists("uploads/large"))
        self.assertEqual(list(self.root.rglob("*.upload")), [])


if __name__ == "__main__":
    unittest.main()
