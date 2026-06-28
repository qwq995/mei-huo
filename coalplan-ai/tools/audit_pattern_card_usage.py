from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

from coalplan.application.pattern_card_usage_audit import audit_pattern_card_usage, write_pattern_card_usage_audit


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Audit persisted generation metadata for pattern prompt card usage.")
    parser.add_argument("--artifact-root", type=Path, required=True, help="Project artifact root or any parent folder containing chapter artifacts.")
    parser.add_argument("--output-dir", type=Path, default=None)
    args = parser.parse_args()

    output_dir = args.output_dir or Path.cwd() / f".coalplan-pattern-card-audit-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
    report = audit_pattern_card_usage(args.artifact_root)
    paths = write_pattern_card_usage_audit(report, output_dir)
    payload = {
        "summary": report["summary"],
        "paths": paths,
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
