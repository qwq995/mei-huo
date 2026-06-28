from __future__ import annotations

import argparse
from pathlib import Path

from coalplan.application.local_corpus_patterns import (
    analyze_local_corpus,
    build_pattern_library_from_analysis,
    render_corpus_analysis_markdown,
)
from coalplan.application.serialization import dump_model, to_json_text


DEFAULT_CORPUS_DIR = Path(r"C:\Users\Lenovo\Documents\煤火\施组目录结构_纯文本")


def main() -> int:
    parser = argparse.ArgumentParser(description="Analyze local construction organization TOC corpus.")
    parser.add_argument("--corpus-dir", type=Path, default=DEFAULT_CORPUS_DIR)
    parser.add_argument("--output-json", type=Path, default=Path("docs/local-corpus-analysis.json"))
    parser.add_argument("--output-md", type=Path, default=Path("docs/local-corpus-analysis.md"))
    parser.add_argument(
        "--output-patterns",
        type=Path,
        default=Path("src/coalplan/assets/generation/writing_patterns.generated.json"),
        help="Write a generated pattern library JSON. Use this for review before replacing writing_patterns.json.",
    )
    parser.add_argument(
        "--include-source-excerpts",
        action="store_true",
        help="Best-effort read original PDF/DOCX files referenced by the TOC corpus and extract generic body-writing cues.",
    )
    parser.add_argument(
        "--max-source-chars",
        type=int,
        default=250_000,
        help="Maximum characters to read from each original source file when --include-source-excerpts is enabled.",
    )
    args = parser.parse_args()

    analysis = analyze_local_corpus(
        args.corpus_dir,
        include_source_excerpts=args.include_source_excerpts,
        max_source_chars=args.max_source_chars,
    )
    pattern_library = build_pattern_library_from_analysis(analysis)

    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_md.parent.mkdir(parents=True, exist_ok=True)
    args.output_patterns.parent.mkdir(parents=True, exist_ok=True)

    args.output_json.write_text(to_json_text(dump_model(analysis)), encoding="utf-8")
    args.output_md.write_text(render_corpus_analysis_markdown(analysis), encoding="utf-8")
    args.output_patterns.write_text(to_json_text(dump_model(pattern_library)), encoding="utf-8")

    print(f"sample_count={analysis.sample_count}")
    print(f"analysis_json={args.output_json}")
    print(f"analysis_md={args.output_md}")
    print(f"generated_patterns={args.output_patterns}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
