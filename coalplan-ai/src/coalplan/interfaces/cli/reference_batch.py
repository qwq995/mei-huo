from __future__ import annotations

import argparse
import json
from pathlib import Path

from coalplan.application.reference_batch_workbench import (
    ingest_reference_decisions,
    prepare_reference_batches,
    sync_reference_library_to_database,
)
from coalplan.infrastructure.database.reference_repository import ReferenceLibraryRepository
from coalplan.infrastructure.database.session import create_session_factory, init_database, sqlite_url_for_storage
from coalplan.settings import get_settings


def main() -> int:
    parser = argparse.ArgumentParser(description="Prepare and ingest model-only large-batch reference atom reviews.")
    sub = parser.add_subparsers(dest="command", required=True)
    prepare = sub.add_parser("prepare")
    prepare.add_argument("--source-root", type=Path, default=Path(r"D:\Task_md\安能-数据-markdown"))
    prepare.add_argument("--catalog", type=Path, default=Path(".coalplan-data/reference-library/catalog/reference_corpus_catalog.json"))
    prepare.add_argument("--output-dir", type=Path, default=Path(".coalplan-data/reference-library/large-batch"))
    prepare.add_argument("--batch-size", type=int, default=3)
    ingest = sub.add_parser("ingest")
    ingest.add_argument("--task-dir", type=Path, required=True)
    ingest.add_argument("--decision-dir", type=Path, required=True)
    ingest.add_argument("--output-dir", type=Path, required=True)
    ingest.add_argument("--sync-database", action="store_true", help="同步到管理台使用的 SQLite 参考库")
    ingest.add_argument("--storage-dir", type=Path, help="SQLite 所在存储目录，默认使用应用配置")
    args = parser.parse_args()
    if args.command == "prepare":
        result = prepare_reference_batches(source_root=args.source_root, catalog_path=args.catalog, output_dir=args.output_dir, batch_size=args.batch_size)
        print(json.dumps({"run_id": result.run_id, "task_dir": str(result.task_dir), "documents": result.document_count, "batches": result.batch_count, "skipped": result.skipped_count}, ensure_ascii=False))
        return 0
    result = ingest_reference_decisions(task_dir=args.task_dir, decision_dir=args.decision_dir, output_dir=args.output_dir)
    if args.sync_database:
        settings = get_settings()
        storage_dir = (args.storage_dir or settings.storage_dir).resolve()
        session_factory = create_session_factory(settings.database_url or sqlite_url_for_storage(storage_dir))
        init_database(session_factory)
        result["database_sync"] = sync_reference_library_to_database(
            task_dir=args.task_dir,
            library_path=args.output_dir / "reference_atom_library.jsonl",
            repository=ReferenceLibraryRepository(session_factory),
        )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
