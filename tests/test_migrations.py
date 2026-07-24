from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy import create_engine, inspect

from parser_serve.persistence import Base


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class MigrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        database_path = Path(self.temporary_directory.name) / "migration.sqlite3"
        self.database_url = f"sqlite+aiosqlite:///{database_path}"
        self.sync_database_url = f"sqlite:///{database_path}"
        self.config = Config(PROJECT_ROOT / "alembic.ini")
        self.config.set_main_option("sqlalchemy.url", self.database_url)

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def test_initial_migration_upgrades_and_downgrades(self) -> None:
        command.upgrade(self.config, "head")

        engine = create_engine(self.sync_database_url)
        try:
            with engine.connect() as connection:
                upgraded_tables = set(inspect(connection).get_table_names())
                migration_context = MigrationContext.configure(
                    connection,
                    opts={
                        "compare_type": True,
                        "compare_server_default": True,
                    },
                )
                schema_differences = compare_metadata(
                    migration_context,
                    Base.metadata,
                )
        finally:
            engine.dispose()

        self.assertEqual(
            upgraded_tables,
            {*Base.metadata.tables, "alembic_version"},
        )
        self.assertEqual(schema_differences, [])

        command.downgrade(self.config, "base")

        engine = create_engine(self.sync_database_url)
        try:
            downgraded_tables = set(inspect(engine).get_table_names())
        finally:
            engine.dispose()

        self.assertEqual(downgraded_tables, {"alembic_version"})


if __name__ == "__main__":
    unittest.main()
