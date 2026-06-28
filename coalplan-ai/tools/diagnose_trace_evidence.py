from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from coalplan.application.serialization import to_json_text
from coalplan.application.trace_evidence_diagnostics import (
    diagnose_trace_evidence_absorption,
    render_trace_evidence_diagnostics_markdown,
)


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Diagnose whether omitted source facts reached LLM prompts or responses.")
    parser.add_argument("--quality-report", type=Path, required=True)
    parser.add_argument("--trace-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, default=None)
    parser.add_argument("--max-examples", type=int, default=30)
    args = parser.parse_args()

    output_dir = args.output_dir or args.quality_report.parent
    output_dir.mkdir(parents=True, exist_ok=True)

    quality_report = json.loads(args.quality_report.read_text(encoding="utf-8"))
    report = diagnose_trace_evidence_absorption(
        quality_report=quality_report,
        trace_dir=args.trace_dir,
        max_examples=args.max_examples,
    )
    project_key = report.get("project_key") or args.quality_report.stem
    json_path = output_dir / f"{project_key}_trace_evidence_diagnostics.json"
    md_path = output_dir / f"{project_key}_trace_evidence_diagnostics.md"
    json_path.write_text(to_json_text(report), encoding="utf-8")
    md_path.write_text(render_trace_evidence_diagnostics_markdown(report), encoding="utf-8")
    print(json.dumps({"json_path": str(json_path), "markdown_path": str(md_path), **report}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
