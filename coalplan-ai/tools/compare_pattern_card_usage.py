from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

from coalplan.application.pattern_card_usage_audit import (
    compare_pattern_card_usage_reports,
    load_pattern_card_usage_report,
    write_pattern_card_usage_comparison,
)


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Compare two pattern-card usage audits or artifact roots.")
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--baseline-label", default="baseline")
    parser.add_argument("--candidate-label", default="candidate")
    parser.add_argument("--output-dir", type=Path, default=None)
    args = parser.parse_args()

    output_dir = args.output_dir or Path.cwd() / f".coalplan-pattern-card-compare-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
    baseline = load_pattern_card_usage_report(args.baseline)
    candidate = load_pattern_card_usage_report(args.candidate)
    comparison = compare_pattern_card_usage_reports(
        baseline,
        candidate,
        baseline_label=args.baseline_label,
        candidate_label=args.candidate_label,
    )
    paths = write_pattern_card_usage_comparison(comparison, output_dir)
    print(
        json.dumps(
            {
                "verdict": comparison["verdict"],
                "summary_delta": comparison["summary_delta"],
                "paths": paths,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
