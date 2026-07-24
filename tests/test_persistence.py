from __future__ import annotations

import unittest
from datetime import UTC, datetime, timedelta

from pydantic import TypeAdapter
from sqlalchemy import inspect, select

from parser_serve.persistence import Base, Database
from parser_serve.persistence.api_keys import (
    ApiKeyRepository,
    LastActiveApiKeyError,
    api_key_digest,
    generate_api_key,
)
from parser_serve.persistence.models import ApiKeyRecord
from parser_serve.schema.authentication import ApiKeyStatus, ApiKeyValue


NOW = datetime(2026, 7, 24, 12, 0, tzinfo=UTC)


class PersistenceMetadataTests(unittest.TestCase):
    def test_contains_control_plane_tables(self) -> None:
        self.assertEqual(
            set(Base.metadata.tables),
            {
                "api_keys",
                "artifacts",
                "backends",
                "callback_attempts",
                "callback_deliveries",
                "events",
                "pipelines",
                "stages",
                "system_settings",
                "tasks",
                "uploaded_files",
                "workers",
            },
        )

    def test_api_key_digest_is_stable_without_exposing_plaintext(self) -> None:
        api_key = f"parser_{'a' * 32}"
        digest = api_key_digest(api_key)

        self.assertEqual(len(digest), 32)
        self.assertEqual(digest, api_key_digest(api_key))
        self.assertNotIn(api_key.encode(), digest)

    def test_generated_api_key_matches_public_schema(self) -> None:
        api_key = generate_api_key()

        self.assertEqual(TypeAdapter(ApiKeyValue).validate_python(api_key), api_key)


class ApiKeyRepositoryTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.database = Database("sqlite+aiosqlite:///:memory:")
        await self.database.create_schema_for_testing()
        self.repository = ApiKeyRepository()

    async def asyncTearDown(self) -> None:
        await self.database.dispose()

    async def test_schema_is_created_in_database(self) -> None:
        async with self.database.engine.connect() as connection:
            tables = await connection.run_sync(
                lambda sync_connection: inspect(sync_connection).get_table_names()
            )

        self.assertEqual(set(tables), set(Base.metadata.tables))

    async def test_create_and_authenticate_api_key(self) -> None:
        async with self.database.session_factory() as session:
            created = await self.repository.create(
                session,
                name="automation",
                expires_at=NOW + timedelta(days=30),
                now=NOW,
            )
            await session.commit()

        self.assertEqual(created.summary.status, ApiKeyStatus.ACTIVE)
        self.assertNotEqual(created.api_key, created.summary.prefix)

        async with self.database.session_factory() as session:
            record = await self.repository.authenticate(
                session,
                api_key=created.api_key,
                now=NOW + timedelta(seconds=1),
            )
            await session.commit()

        self.assertIsNotNone(record)
        if record is not None:
            self.assertEqual(record.api_key_id, created.summary.api_key_id)
            self.assertEqual(record.last_used_at, NOW + timedelta(seconds=1))

    async def test_rejects_unknown_api_key(self) -> None:
        async with self.database.session_factory() as session:
            record = await self.repository.authenticate(
                session,
                api_key=f"parser_{'z' * 32}",
                now=NOW,
            )

        self.assertIsNone(record)

    async def test_rejects_expired_api_key(self) -> None:
        async with self.database.session_factory() as session:
            created = await self.repository.create(
                session,
                name="temporary",
                expires_at=NOW + timedelta(seconds=1),
                now=NOW,
            )
            await session.commit()

        async with self.database.session_factory() as session:
            record = await self.repository.authenticate(
                session,
                api_key=created.api_key,
                now=NOW + timedelta(seconds=2),
            )

        self.assertIsNone(record)

    async def test_rejects_disabled_api_key(self) -> None:
        async with self.database.session_factory() as session:
            created = await self.repository.create(
                session,
                name="disabled",
                expires_at=None,
                now=NOW,
            )
            await self.repository.create(
                session,
                name="remaining",
                expires_at=None,
                now=NOW,
            )
            await self.repository.set_enabled(
                session,
                api_key_id=created.summary.api_key_id,
                enabled=False,
                now=NOW + timedelta(seconds=1),
            )
            await session.commit()

        async with self.database.session_factory() as session:
            record = await self.repository.authenticate(
                session,
                api_key=created.api_key,
                now=NOW + timedelta(seconds=2),
            )

        self.assertIsNone(record)

    async def test_prevents_disabling_final_active_api_key(self) -> None:
        async with self.database.session_factory() as session:
            created = await self.repository.create(
                session,
                name="only",
                expires_at=None,
                now=NOW,
            )
            await session.commit()

        async with self.database.session_factory() as session:
            with self.assertRaises(LastActiveApiKeyError):
                await self.repository.set_enabled(
                    session,
                    api_key_id=created.summary.api_key_id,
                    enabled=False,
                    now=NOW + timedelta(seconds=1),
                )

    async def test_database_stores_digest_not_plaintext(self) -> None:
        async with self.database.session_factory() as session:
            created = await self.repository.create(
                session,
                name="secure",
                expires_at=None,
                now=NOW,
            )
            await session.commit()

        async with self.database.session_factory() as session:
            result = await session.execute(select(ApiKeyRecord))
            record = result.scalar_one()

        self.assertEqual(record.digest, api_key_digest(created.api_key))
        self.assertNotEqual(record.prefix, created.api_key)


if __name__ == "__main__":
    unittest.main()
