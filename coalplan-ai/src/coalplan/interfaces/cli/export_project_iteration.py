from __future__ import annotations

import argparse
from pathlib import Path

from coalplan.application.current_execution_window import (
    build_current_execution_window,
    render_current_execution_window_markdown,
)
from coalplan.application.iteration_plan import render_iteration_plan_markdown
from coalplan.application.serialization import to_json_text
from coalplan.interfaces.cli.audit_generation_goal import (
    _resolve_project_id,
    render_outline_repair_proposal_markdown,
)
from coalplan.main import build_pipeline
from coalplan.settings import Settings


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Export a concrete project convergence plan without mutating generation output."
    )
    parser.add_argument("--storage-dir", type=Path, required=True, help="CoalPlan storage directory.")
    parser.add_argument("--project-id", default=None, help="Project id to inspect.")
    parser.add_argument(
        "--project-key",
        default=None,
        help="Optional id/name/template fragment used when --project-id is not supplied.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("docs/project-iteration"),
        help="Directory for exported gate, action, iteration, and optional proposal files.",
    )
    parser.add_argument(
        "--repair-profile-before-export",
        action="store_true",
        help="Repair ProjectProfile before exporting plans.",
    )
    parser.add_argument(
        "--propose-outline-repair",
        action="store_true",
        help="Create a review-only outline repair proposal and export it as JSON and Markdown.",
    )
    args = parser.parse_args()

    payload = export_project_iteration(
        storage_dir=args.storage_dir,
        project_id=args.project_id,
        project_key=args.project_key,
        output_dir=args.output_dir,
        repair_profile_before_export=args.repair_profile_before_export,
        propose_outline_repair=args.propose_outline_repair,
    )
    print(f"project_id={payload['project_id']}")
    print(f"gate_status={payload['gate_status']}")
    print(f"iteration_status={payload['iteration_status']}")
    print(f"action_count={payload['action_count']}")
    print(f"readiness_status={payload['readiness_status']}")
    print(f"execution_window_status={payload['execution_window_status']}")
    print(f"allowed_now_count={payload['allowed_now_count']}")
    print(f"deferred_action_count={payload['deferred_action_count']}")
    print(
        "readiness_batches="
        f"auto:{payload['readiness_auto_batch_count']},"
        f"user_confirmation:{payload['readiness_user_confirmation_batch_count']},"
        f"manual_review:{payload['readiness_manual_review_batch_count']}"
    )
    print(f"output_dir={args.output_dir}")
    return 0 if payload["gate_status"] != "blocked" else 2


def export_project_iteration(
    *,
    storage_dir: Path,
    project_id: str | None = None,
    project_key: str | None = None,
    output_dir: Path,
    repair_profile_before_export: bool = False,
    propose_outline_repair: bool = False,
) -> dict:
    pipeline = build_pipeline(Settings(storage_dir=storage_dir, llm_provider="fake"))
    resolved_project_id = _resolve_project_id(pipeline, project_id=project_id, project_key=project_key)
    output_dir.mkdir(parents=True, exist_ok=True)

    if repair_profile_before_export:
        pipeline.repair_project_profile(resolved_project_id)

    proposal_paths: dict[str, str] = {}
    if propose_outline_repair:
        proposal = pipeline.propose_control_outline_repair(resolved_project_id)
        proposal_json = output_dir / "outline_repair_proposal.json"
        proposal_md = output_dir / "outline_repair_proposal.md"
        proposal_json.write_text(to_json_text(proposal), encoding="utf-8")
        proposal_md.write_text(render_outline_repair_proposal_markdown(proposal), encoding="utf-8")
        proposal_paths = {"outline_repair_proposal_json": str(proposal_json), "outline_repair_proposal_md": str(proposal_md)}

    gate_report = pipeline.pipeline_gate_report(resolved_project_id)
    action_plan = pipeline.pipeline_action_plan(resolved_project_id)
    iteration_plan = pipeline.iteration_plan(resolved_project_id)
    readiness_report = pipeline.generation_readiness(resolved_project_id)

    gate_json = output_dir / "pipeline_gates.json"
    action_json = output_dir / "pipeline_actions.json"
    iteration_json = output_dir / "iteration_plan.json"
    iteration_md = output_dir / "iteration_plan.md"
    readiness_json = output_dir / "generation_readiness.json"
    readiness_md = output_dir / "generation_readiness.md"
    execution_json = output_dir / "current_execution_window.json"
    execution_md = output_dir / "current_execution_window.md"
    gate_json.write_text(to_json_text(gate_report), encoding="utf-8")
    action_json.write_text(to_json_text(action_plan), encoding="utf-8")
    iteration_json.write_text(to_json_text(iteration_plan), encoding="utf-8")
    iteration_md.write_text(render_iteration_plan_markdown_from_payload(iteration_plan), encoding="utf-8")
    readiness_json.write_text(to_json_text(readiness_report), encoding="utf-8")
    readiness_md.write_text(str(readiness_report.get("artifact_markdown_path") or ""), encoding="utf-8")
    _copy_readiness_markdown(readiness_report, readiness_md)
    execution_window_payload = pipeline.current_execution_window(resolved_project_id)
    execution_window = build_current_execution_window(iteration_plan)
    execution_json.write_text(to_json_text(execution_window_payload), encoding="utf-8")
    source_md = Path(str(execution_window_payload.get("artifact_markdown_path") or ""))
    if source_md.exists():
        execution_md.write_text(source_md.read_text(encoding="utf-8-sig"), encoding="utf-8")
    else:
        execution_md.write_text(render_current_execution_window_markdown(execution_window), encoding="utf-8")

    batch_counts = _readiness_batch_counts(readiness_report)

    return {
        "project_id": resolved_project_id,
        "gate_status": gate_report.get("overall_status"),
        "iteration_status": iteration_plan.get("status"),
        "action_count": len(action_plan.get("actions") or []),
        "readiness_status": readiness_report.get("status"),
        "execution_window_status": execution_window_payload.get("status"),
        "allowed_now_count": len(execution_window_payload.get("allowed_actions") or []),
        "deferred_action_count": len(execution_window_payload.get("deferred_actions") or []),
        "readiness_auto_batch_count": batch_counts["auto"],
        "readiness_user_confirmation_batch_count": batch_counts["user_confirmation"],
        "readiness_manual_review_batch_count": batch_counts["manual_review"],
        "pipeline_gates_json": str(gate_json),
        "pipeline_actions_json": str(action_json),
        "iteration_plan_json": str(iteration_json),
        "iteration_plan_md": str(iteration_md),
        "generation_readiness_json": str(readiness_json),
        "generation_readiness_md": str(readiness_md),
        "current_execution_window_json": str(execution_json),
        "current_execution_window_md": str(execution_md),
        **proposal_paths,
    }


def render_iteration_plan_markdown_from_payload(payload: dict) -> str:
    from coalplan.application.iteration_plan import IterationPlan

    return render_iteration_plan_markdown(IterationPlan.model_validate(payload))


def _copy_readiness_markdown(readiness_report: dict, target: Path) -> None:
    artifact_path = readiness_report.get("artifact_markdown_path")
    if not artifact_path:
        return
    source = Path(str(artifact_path))
    if source.exists():
        target.write_text(source.read_text(encoding="utf-8-sig"), encoding="utf-8")


def _readiness_batch_counts(readiness_report: dict) -> dict[str, int]:
    counts = {"auto": 0, "user_confirmation": 0, "manual_review": 0}
    for batch in readiness_report.get("batches") or []:
        mode = str(batch.get("execution_mode") or "manual_review")
        if mode in counts:
            counts[mode] += 1
    return counts


if __name__ == "__main__":
    raise SystemExit(main())
