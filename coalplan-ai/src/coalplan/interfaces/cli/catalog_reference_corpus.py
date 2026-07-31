from __future__ import annotations

import argparse
from pathlib import Path

from coalplan.application.reference_corpus_catalog import (
    build_reference_corpus_catalog,
    write_reference_corpus_catalog,
)


DEFAULT_SOURCE_ROOT = Path(r"D:\Task_md\安能-数据-markdown")
DEFAULT_OUTPUT_DIR = Path(".coalplan-data/reference-library/catalog")


def main() -> int:
    parser = argparse.ArgumentParser(description="Build a read-only catalog for local construction-plan Markdown files.")
    parser.add_argument("--source-root", type=Path, default=DEFAULT_SOURCE_ROOT)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    args = parser.parse_args()

    catalog = build_reference_corpus_catalog(args.source_root)
    paths = write_reference_corpus_catalog(catalog, args.output_dir)
    print(f"documents={catalog.document_count}")
    print(f"unique_documents={catalog.unique_document_count}")
    print(f"exact_duplicates={catalog.exact_duplicate_count}")
    print(f"atom_candidates={catalog.atom_candidate_count}")
    for kind, path in paths.items():
        print(f"{kind}={path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
