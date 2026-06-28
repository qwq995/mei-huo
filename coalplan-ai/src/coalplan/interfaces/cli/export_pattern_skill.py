from __future__ import annotations

import argparse
from pathlib import Path

from coalplan.application.pattern_skill_export import export_pattern_skill_markdown, export_pattern_skill_package
from coalplan.application.writing_pattern_library import WritingPatternLibrary, load_writing_pattern_library


def main() -> int:
    parser = argparse.ArgumentParser(description="Export local construction organization writing patterns as a reusable skill.")
    parser.add_argument(
        "--generated-path",
        type=Path,
        default=None,
        help="Optional generated writing_patterns JSON to export instead of the active library.",
    )
    parser.add_argument(
        "--output-md",
        type=Path,
        default=None,
        help="Optional single Markdown skill file for review.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path(".coalplan-data/pattern-library/construction-org-writing-patterns"),
        help="Directory for a reusable skill package containing SKILL.md and references.",
    )
    args = parser.parse_args()

    library = _load_library(args.generated_path)
    if args.output_md:
        single = export_pattern_skill_markdown(library=library, output_path=args.output_md)
        print(f"markdown={single['output_path']}")
    package = export_pattern_skill_package(library=library, output_dir=args.output_dir)
    print(f"skill_package={package['output_dir']}")
    print(f"skill={package['package_paths']['skill']}")
    print(f"pattern_cards={package['package_paths']['writing_pattern_cards']}")
    print(f"pattern_cards_json={package['package_paths']['writing_pattern_cards_json']}")
    print(f"pipeline_control={package['package_paths']['pipeline_control']}")
    return 0


def _load_library(path: Path | None) -> WritingPatternLibrary:
    if path is None:
        return load_writing_pattern_library()
    return WritingPatternLibrary.model_validate_json(path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    raise SystemExit(main())
