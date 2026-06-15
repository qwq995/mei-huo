from __future__ import annotations

import argparse
from pathlib import Path

from coalplan.main import build_pipeline
from coalplan.settings import Settings


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate a coal-fire construction organization markdown from a bid markdown file.")
    parser.add_argument("input_markdown", type=Path)
    parser.add_argument("--project-name", default="宁夏煤火北一火区真实投标演示")
    parser.add_argument("--output-dir", default=".coalplan-real-run")
    parser.add_argument("--llm-provider", default="source_driven", choices=["fake", "source_driven", "source_fake", "minimax", "deepseek"])
    args = parser.parse_args()

    content = args.input_markdown.read_text(encoding="utf-8-sig")
    pipeline = build_pipeline(Settings(storage_dir=Path(args.output_dir), llm_provider=args.llm_provider))
    project = pipeline.create_project(args.project_name, "coal_fire")
    project = pipeline.ingest_bid_markdown(project.id, file_name=args.input_markdown.name, content=content)
    run = pipeline.prepare_run(project.id)
    run = pipeline.generate_all(project.id)
    run = pipeline.merge_latest(project.id)
    print(f"project_id={project.id}")
    print(f"sections={len(project.sections)}")
    print(f"run_id={run.id}")
    print(f"status={run.status.value}")
    print(f"final={run.final_artifact_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
