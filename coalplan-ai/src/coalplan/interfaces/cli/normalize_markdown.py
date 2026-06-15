from __future__ import annotations

import argparse
from pathlib import Path

from coalplan.infrastructure.markdown.parser import MarkdownDocumentParser


def main() -> int:
    parser = argparse.ArgumentParser(description="Normalize a bid markdown file for CoalPlan ingestion.")
    parser.add_argument("input_markdown", type=Path)
    parser.add_argument("output_markdown", type=Path)
    args = parser.parse_args()

    text = args.input_markdown.read_text(encoding="utf-8-sig")
    normalized = MarkdownDocumentParser().canonicalize(text)
    args.output_markdown.parent.mkdir(parents=True, exist_ok=True)
    args.output_markdown.write_text(normalized, encoding="utf-8")
    sections = MarkdownDocumentParser().split_sections(normalized, source_file=args.output_markdown.name)
    print(f"wrote {args.output_markdown} ({len(normalized)} chars), sections={len(sections)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
