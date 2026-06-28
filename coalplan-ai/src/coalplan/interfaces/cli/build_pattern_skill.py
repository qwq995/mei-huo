from __future__ import annotations

import argparse
from pathlib import Path

from coalplan.application.pattern_library_admin import (
    DEFAULT_LOCAL_CORPUS_DIR,
    build_reviewable_pattern_skill_from_corpus,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build a reviewable construction-organization writing skill package from the local corpus."
    )
    parser.add_argument("--corpus-dir", type=Path, default=DEFAULT_LOCAL_CORPUS_DIR)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path(".coalplan-data/pattern-library/reviewable-skill-build"),
        help="Directory that will receive analysis, generated patterns, coverage audit, and the skill package.",
    )
    parser.add_argument("--skill-name", default="construction-org-writing-patterns")
    parser.add_argument(
        "--include-source-excerpts",
        action="store_true",
        help="Best-effort read original PDF/DOCX references from the corpus to enrich generic writing moves.",
    )
    parser.add_argument("--max-source-chars", type=int, default=250_000)
    args = parser.parse_args()

    result = build_reviewable_pattern_skill_from_corpus(
        corpus_dir=args.corpus_dir,
        output_dir=args.output_dir,
        skill_name=args.skill_name,
        include_source_excerpts=args.include_source_excerpts,
        max_source_chars=args.max_source_chars,
    )
    print(f"corpus_dir={result['corpus_dir']}")
    print(f"sample_count={result['analysis']['sample_count']}")
    print(f"coverage_status={result['coverage_report']['status']}")
    print(f"generated_patterns={result['generated_path']}")
    print(f"coverage_report={result['coverage_markdown_path']}")
    print(f"skill_package={result['skill_package_dir']}")
    print(f"skill_manifest={result['skill_manifest_path']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
