"""Import an isolated generation database into the active workspace database."""

from __future__ import annotations

import argparse
import shutil
import sqlite3
from datetime import datetime
from pathlib import Path


SKIP_TABLES = {
    "standard_document_search",
    "constraint_atom_search",
    "standard_document_search_config",
    "standard_document_search_content",
    "standard_document_search_data",
    "standard_document_search_docsize",
    "standard_document_search_idx",
    "constraint_atom_search_config",
    "constraint_atom_search_content",
    "constraint_atom_search_data",
    "constraint_atom_search_docsize",
    "constraint_atom_search_idx",
}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--target", type=Path, required=True)
    parser.add_argument("--project-id", required=True)
    args = parser.parse_args()

    source_root = args.source.resolve()
    target_root = args.target.resolve()
    source_db = source_root / "storage" / "coalplan.db"
    target_db = target_root / "coalplan.db"
    if not source_db.exists() or not target_db.exists():
        raise FileNotFoundError("source or target database does not exist")

    backup = target_db.with_name(f"coalplan.db.before-import-{datetime.now().strftime('%Y%m%d-%H%M%S')}.bak")
    shutil.copy2(target_db, backup)
    source_artifacts = source_root / "storage" / "artifacts" / args.project_id
    target_artifacts = target_root / "artifacts" / args.project_id

    target = sqlite3.connect(target_db)
    target.execute("PRAGMA foreign_keys=OFF")
    target.execute("ATTACH DATABASE ? AS source_db", (str(source_db),))
    tables = [
        row[0]
        for row in target.execute(
            "SELECT name FROM main.sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        ).fetchall()
        if row[0] not in SKIP_TABLES
    ]
    imported = {}
    for table in tables:
        source_exists = target.execute(
            "SELECT 1 FROM source_db.sqlite_master WHERE type='table' AND name=?", (table,)
        ).fetchone()
        if not source_exists:
            continue
        columns = [row[1] for row in target.execute(f'PRAGMA main.table_info("{table}")').fetchall()]
        if not columns:
            continue
        quoted = ", ".join(f'"{column}"' for column in columns)
        sql = f'INSERT OR IGNORE INTO main."{table}" ({quoted}) SELECT {quoted} FROM source_db."{table}"'
        before = target.total_changes
        target.execute(sql)
        imported[table] = target.total_changes - before
    target.commit()
    target.execute("DETACH DATABASE source_db")
    target.close()

    if source_artifacts.exists():
        target_artifacts.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(source_artifacts, target_artifacts, dirs_exist_ok=True)

    print(f"backup={backup}")
    print(f"source={source_db}")
    print(f"target={target_db}")
    print(f"artifacts={target_artifacts}")
    print("imported=" + ", ".join(f"{key}:{value}" for key, value in sorted(imported.items())))


if __name__ == "__main__":
    main()
