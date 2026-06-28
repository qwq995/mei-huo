from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

from coalplan.application.generation_run_comparison import (
    compare_generation_run_summaries,
    load_generation_run_summary,
    write_generation_run_comparison,
)


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(
        description="Compare two DeepSeek generation output roots or deepseek_full_generation_summary.json files."
    )
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--baseline-label", default="baseline")
    parser.add_argument("--candidate-label", default="candidate")
    parser.add_argument("--output-dir", type=Path, default=None)
    args = parser.parse_args()

    baseline = load_generation_run_summary(args.baseline)
    candidate = load_generation_run_summary(args.candidate)
    comparison = compare_generation_run_summaries(
        baseline,
        candidate,
        baseline_label=args.baseline_label,
        candidate_label=args.candidate_label,
    )
    output_dir = args.output_dir or Path.cwd() / f".coalplan-generation-run-compare-{datetime.now():%Y%m%d-%H%M%S}"
    paths = write_generation_run_comparison(comparison, output_dir)
    print(json.dumps({"paths": paths, "comparison": comparison}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
