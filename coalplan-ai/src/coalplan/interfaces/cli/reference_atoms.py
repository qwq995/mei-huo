from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from coalplan.application.reference_atom_retrieval import retrieve_reference_atoms
from coalplan.application.reference_atomization import atomize_reference_markdown
from coalplan.application.serialization import dump_model
from coalplan.domain.documents import stable_id
from coalplan.domain.reference_library import AtomRetrievalQuery, ReferenceDocument, ReferenceDocumentKind
from coalplan.infrastructure.database.reference_repository import ReferenceLibraryRepository
from coalplan.infrastructure.database.session import create_session_factory, init_database, sqlite_url_for_storage
from coalplan.main import _build_llm
from coalplan.settings import get_settings


def main() -> int:
    parser = argparse.ArgumentParser(description="Import and retrieve AI-tagged construction-plan reference atoms.")
    parser.add_argument("--storage-dir", type=Path)
    subparsers = parser.add_subparsers(dest="command", required=True)

    import_parser = subparsers.add_parser("import")
    import_parser.add_argument("source_path", type=Path)
    import_parser.add_argument("--project-name", required=True)
    import_parser.add_argument("--project-type", required=True)
    import_parser.add_argument("--document-kind", choices=[item.value for item in ReferenceDocumentKind], default="special_plan")
    import_parser.add_argument("--focus", action="append", default=[])
    import_parser.add_argument("--max-batches", type=int)
    import_parser.add_argument("--publish-for-validation", action="store_true")

    retrieve_parser = subparsers.add_parser("retrieve")
    retrieve_parser.add_argument("--project-name", required=True)
    retrieve_parser.add_argument("--project-type", required=True)
    retrieve_parser.add_argument("--chapter-title", required=True)
    retrieve_parser.add_argument("--evidence-summary", default="")
    retrieve_parser.add_argument("--topic", action="append", default=[])
    retrieve_parser.add_argument("--top-k", type=int, default=5)

    args = parser.parse_args()
    settings = get_settings()
    storage_dir = (args.storage_dir or settings.storage_dir).resolve()
    session_factory = create_session_factory(settings.database_url or sqlite_url_for_storage(storage_dir))
    init_database(session_factory)
    repository = ReferenceLibraryRepository(session_factory)
    provider = settings.structured_llm_provider or settings.llm_provider
    llm = _build_llm(provider, settings)

    if args.command == "import":
        path = args.source_path.resolve()
        raw = path.read_bytes()
        digest = hashlib.sha256(raw).hexdigest()
        document = ReferenceDocument(
            id=stable_id("refdoc", digest),
            content_hash=digest,
            source_path=str(path),
            file_name=path.name,
            project_name=args.project_name,
            project_type=args.project_type,
            document_kind=args.document_kind,
        )
        repository.save_document(document)
        result = atomize_reference_markdown(
            document=document,
            markdown=raw.decode("utf-8-sig", errors="replace"),
            llm=llm,
            focus_terms=args.focus,
            max_batches=args.max_batches,
            publish_for_validation=args.publish_for_validation,
        )
        repository.replace_document_content(document.id, chapters=[], atoms=result.atoms)
        print(json.dumps({"document_id": document.id, "atoms": len(result.atoms), "llm_calls": result.llm_call_count}, ensure_ascii=False))
        return 0

    query = AtomRetrievalQuery(
        project_name=args.project_name,
        project_type=args.project_type,
        chapter_title=args.chapter_title,
        evidence_summary=args.evidence_summary,
        writing_topics=args.topic,
        top_k=args.top_k,
    )
    results = retrieve_reference_atoms(atoms=repository.list_atoms(), query=query, llm=llm)
    print(json.dumps([dump_model(item) for item in results], ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
