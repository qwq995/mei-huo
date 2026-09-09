from __future__ import annotations

import argparse
import json
from pathlib import Path

from coalplan.application.reference_v2_corpus import (
    curate_v2_corpus,
    prepare_v2_corpus,
    process_v2_corpus,
    route_v2_corpus,
    sync_v2_corpus,
)
from coalplan.infrastructure.database.reference_repository import ReferenceLibraryRepository
from coalplan.infrastructure.database.session import create_session_factory, init_database, sqlite_url_for_storage
from coalplan.domain.reference_library import ReferenceReviewStatus
from coalplan.main import _build_llm
from coalplan.settings import get_settings


def main() -> int:
    parser = argparse.ArgumentParser(description="Prepare or resume the V2 reference atom corpus.")
    sub = parser.add_subparsers(dest="command", required=True)
    prepare = sub.add_parser("prepare")
    prepare.add_argument("--source-root", type=Path, required=True)
    prepare.add_argument("--output-dir", type=Path, required=True)
    run = sub.add_parser("run")
    run.add_argument("--manifest", type=Path, required=True)
    run.add_argument("--output-dir", type=Path, required=True)
    run.add_argument("--max-documents", type=int)
    run.add_argument("--start-document", type=int, default=0)
    run.add_argument("--max-batches-per-document", type=int)
    run.add_argument("--concurrency", type=int, default=1)
    run.add_argument("--llm-provider", choices=["configured", "codex-cli"], default="configured")
    run.add_argument("--codex-model", default="gpt-5.6-sol")
    run.add_argument("--codex-timeout", type=int, default=900)
    run.add_argument("--sync-database", action="store_true")
    route = sub.add_parser("route")
    route.add_argument("--manifest", type=Path, required=True)
    route.add_argument("--output-dir", type=Path, required=True)
    route.add_argument("--max-documents", type=int)
    route.add_argument("--concurrency", type=int, default=4)
    route.add_argument("--batch-concurrency", type=int, default=1)
    route.add_argument("--force", action="store_true")
    route.add_argument("--llm-provider", choices=["configured", "codex-cli"], default="configured")
    route.add_argument("--codex-model", default="gpt-5.6-sol")
    route.add_argument("--codex-timeout", type=int, default=900)
    curate = sub.add_parser("curate")
    curate.add_argument("--output-dir", type=Path, required=True)
    sync = sub.add_parser("sync")
    sync.add_argument("--output-dir", type=Path, required=True)
    index = sub.add_parser("index")
    index.add_argument("--model")
    index.add_argument("--path", type=Path)
    index.add_argument("--recreate", action="store_true")
    args = parser.parse_args()
    settings = get_settings()
    if args.command == "prepare":
        result = prepare_v2_corpus(args.source_root, args.output_dir)
        print(json.dumps(result.__dict__, ensure_ascii=False, indent=2, default=str))
        return 0
    if args.command == "curate":
        print(json.dumps(curate_v2_corpus(args.output_dir), ensure_ascii=False, indent=2))
        return 0
    if args.command == "sync":
        settings = get_settings()
        factory = create_session_factory(settings.database_url or sqlite_url_for_storage(settings.storage_dir.resolve()))
        init_database(factory)
        repository = ReferenceLibraryRepository(factory)
        print(json.dumps(sync_v2_corpus(args.output_dir, repository), ensure_ascii=False, indent=2))
        return 0
    if args.command == "index":
        from coalplan.infrastructure.vector.qdrant_atom_index import QdrantAtomVectorIndex, SentenceTransformerEmbedder

        factory = create_session_factory(settings.database_url or sqlite_url_for_storage(settings.storage_dir.resolve()))
        init_database(factory)
        repository = ReferenceLibraryRepository(factory)
        embedder = SentenceTransformerEmbedder(args.model or settings.reference_vector_model)
        vector_path = (args.path or settings.reference_vector_path)
        if not vector_path.is_absolute():
            vector_path = settings.storage_dir.resolve() / vector_path
        vector_index = QdrantAtomVectorIndex(
            embed=embedder, dimension=embedder.dimension,
            url=settings.reference_vector_url, path=vector_path,
        )
        if args.recreate:
            vector_index.reset()
        atoms = repository.list_atoms(status=ReferenceReviewStatus.published)
        indexed = vector_index.upsert(atoms)
        vector_index.close()
        print(json.dumps({
            "published_atoms": len(atoms), "indexed_atoms": indexed,
            "model": args.model or settings.reference_vector_model,
            "path": str(vector_path), "recreated": bool(args.recreate),
        }, ensure_ascii=False, indent=2))
        return 0
    if getattr(args, "llm_provider", "configured") == "codex-cli":
        from coalplan.infrastructure.llm.codex_cli import CodexCliStructuredLLMClient

        llm = CodexCliStructuredLLMClient(
            model=args.codex_model,
            workdir=Path.cwd(),
            trace_dir=args.output_dir / "codex-traces",
            timeout=max(60, args.codex_timeout),
        )
    else:
        llm = _build_llm(settings.structured_llm_provider or settings.llm_provider, settings)
    if args.command == "route":
        result = route_v2_corpus(
            manifest_path=args.manifest, output_dir=args.output_dir, llm=llm,
            max_documents=args.max_documents, concurrency=args.concurrency,
            batch_concurrency=args.batch_concurrency, force=args.force,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    repository = None
    if args.sync_database:
        factory = create_session_factory(settings.database_url or sqlite_url_for_storage(settings.storage_dir.resolve()))
        init_database(factory)
        repository = ReferenceLibraryRepository(factory)
    result = process_v2_corpus(
        manifest_path=args.manifest, output_dir=args.output_dir, llm=llm, repository=repository,
        start_document=args.start_document,
        max_documents=args.max_documents, max_batches_per_document=args.max_batches_per_document,
        concurrency=args.concurrency,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
