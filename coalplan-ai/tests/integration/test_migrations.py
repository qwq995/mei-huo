from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect


class MigrationTest(unittest.TestCase):
    def test_empty_database_upgrades_to_reference_atom_schema(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            database_path = Path(temp_dir) / "migration.db"
            config = Config(str(Path(__file__).resolve().parents[2] / "alembic.ini"))
            config.set_main_option("sqlalchemy.url", f"sqlite:///{database_path.as_posix()}")

            command.upgrade(config, "head")

            engine = create_engine(f"sqlite:///{database_path.as_posix()}")
            tables = set(inspect(engine).get_table_names())
            engine.dispose()
            self.assertTrue(
                {"reference_documents", "reference_chapters", "reference_atoms", "chapter_atom_usages"} <= tables
            )


if __name__ == "__main__":
    unittest.main()
