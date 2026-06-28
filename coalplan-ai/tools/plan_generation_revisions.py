from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

from coalplan.application.targeted_revision_plan import (
    build_targeted_revision_plan,
    load_generation_run_comparison,
    load_revision_plan_input,
    write_targeted_revision_plan,
)


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(
        description="Build a targeted, chapter-level revision plan from a generation summary and optional run comparison."
    )
    parser.add_argument("--summary", type=Path, required=True, help="Output root or deepseek_full_generation_summary.json.")
    parser.add_argument("--comparison", type=Path, default=None, help="Optional generation_run_comparison.json or its folder.")
    parser.add_argument("--projects", nargs="*", default=[], help="Optional project keys to include.")
    parser.add_argument("--output-dir", type=Path, default=None)
    args = parser.parse_args()

    summary = load_revision_plan_input(args.summary)
    comparison = load_generation_run_comparison(args.comparison)
    plan = build_targeted_revision_plan(
        summary,
        comparison=comparison,
        project_keys=args.projects or None,
    )
    output_dir = args.output_dir or Path.cwd() / f".coalplan-targeted-revision-plan-{datetime.now():%Y%m%d-%H%M%S}"
    paths = write_targeted_revision_plan(plan, output_dir)
    print(json.dumps({"paths": paths, "plan": plan}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
