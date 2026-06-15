from __future__ import annotations

import argparse
from pathlib import Path

from coalplan.main import build_pipeline
from coalplan.settings import Settings


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the coal-fire markdown generation demo with the fake LLM.")
    parser.add_argument("--output-dir", default=".coalplan-demo", help="Local directory for project state and artifacts.")
    args = parser.parse_args()

    root = Path(__file__).resolve().parents[2]
    sample = root / "assets" / "samples" / "coal_fire_bid.normalized.md"
    pipeline = build_pipeline(Settings(storage_dir=Path(args.output_dir), llm_provider="fake"))
    project = pipeline.create_project("宁夏煤火北一火区演示", "coal_fire")
    project = pipeline.ingest_bid_markdown(project.id, file_name=sample.name, content=sample.read_text(encoding="utf-8-sig"))
    run = pipeline.prepare_run(project.id)
    run = pipeline.generate_all(project.id)
    run = pipeline.merge_latest(project.id)
    print(f"project_id={project.id}")
    print(f"run_id={run.id}")
    print(f"status={run.status.value}")
    print(f"final={run.final_artifact_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
