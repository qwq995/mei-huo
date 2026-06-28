from __future__ import annotations

import argparse
import json
from pathlib import Path

from coalplan.application.goal_completion_audit import (
    GenerationGoalAuditReport,
    audit_generation_goal,
    render_generation_goal_audit_markdown,
)
from coalplan.application.pipeline_stage_gates import PipelineGateReport
from coalplan.application.serialization import to_json_text
from coalplan.main import build_pipeline
from coalplan.settings import Settings


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Audit reusable construction-organization generation controls against the thread goal."
    )
    parser.add_argument(
        "--project-gate-report",
        type=Path,
        default=None,
        help="Optional JSON pipeline gate report from a concrete project run.",
    )
    parser.add_argument(
        "--storage-dir",
        type=Path,
        default=None,
        help="Optional CoalPlan storage directory. When supplied with --project-id, the CLI builds the project gate report directly.",
    )
    parser.add_argument(
        "--project-id",
        default=None,
        help="Project id to audit from --storage-dir. Use --project-key for summaries that use friendly keys elsewhere.",
    )
    parser.add_argument(
        "--project-key",
        default=None,
        help="Optional project key/name fragment used to locate a project from --storage-dir when --project-id is not supplied.",
    )
    parser.add_argument(
        "--output-gate-json",
        type=Path,
        default=Path("docs/generation-goal-project-gates.json"),
        help="Where to persist the project gate report when --storage-dir is used.",
    )
    parser.add_argument(
        "--repair-profile-before-audit",
        action="store_true",
        help="When auditing from --storage-dir, rebuild ProjectProfile before computing project gates.",
    )
    parser.add_argument(
        "--propose-outline-repair",
        action="store_true",
        help="When auditing from --storage-dir, create a user-reviewable control-plan outline repair proposal.",
    )
    parser.add_argument(
        "--output-outline-proposal-json",
        type=Path,
        default=Path("docs/generation-goal-outline-repair-proposal.json"),
        help="Where to persist the outline repair proposal when --propose-outline-repair is used.",
    )
    parser.add_argument(
        "--output-outline-proposal-md",
        type=Path,
        default=Path("docs/generation-goal-outline-repair-proposal.md"),
        help="Where to persist a human-readable outline repair proposal when --propose-outline-repair is used.",
    )
    parser.add_argument(
        "--output-json",
        type=Path,
        default=Path("docs/generation-goal-audit.json"),
    )
    parser.add_argument(
        "--output-md",
        type=Path,
        default=Path("docs/generation-goal-audit.md"),
    )
    args = parser.parse_args()

    project_gate_report = _resolve_project_gate_report(
        project_gate_report_path=args.project_gate_report,
        storage_dir=args.storage_dir,
        project_id=args.project_id,
        project_key=args.project_key,
        output_gate_json=args.output_gate_json,
        repair_profile_before_audit=args.repair_profile_before_audit,
        propose_outline_repair=args.propose_outline_repair,
        output_outline_proposal_json=args.output_outline_proposal_json,
        output_outline_proposal_md=args.output_outline_proposal_md,
    )
    report = audit_generation_goal(project_gate_report=project_gate_report)
    _write_report(report, args.output_json, args.output_md)
    print(f"status={report.status}")
    print(f"summary={report.summary}")
    print(f"json={args.output_json}")
    print(f"markdown={args.output_md}")
    if project_gate_report is not None:
        print(f"project_gate_status={project_gate_report.overall_status}")
        print(f"project_id={project_gate_report.project_id}")
        if args.storage_dir is not None:
            print(f"project_gate_json={args.output_gate_json}")
        if args.propose_outline_repair:
            print(f"outline_repair_proposal_json={args.output_outline_proposal_json}")
            print(f"outline_repair_proposal_md={args.output_outline_proposal_md}")
    return 0 if report.status != "blocked" else 2


def _resolve_project_gate_report(
    *,
    project_gate_report_path: Path | None,
    storage_dir: Path | None,
    project_id: str | None,
    project_key: str | None,
    output_gate_json: Path,
    repair_profile_before_audit: bool = False,
    propose_outline_repair: bool = False,
    output_outline_proposal_json: Path | None = None,
    output_outline_proposal_md: Path | None = None,
) -> PipelineGateReport | None:
    if project_gate_report_path is not None and storage_dir is not None:
        raise ValueError("Use either --project-gate-report or --storage-dir, not both.")
    if project_gate_report_path is not None:
        return _load_project_gate_report(project_gate_report_path)
    if storage_dir is None:
        return None
    pipeline = build_pipeline(Settings(storage_dir=storage_dir, llm_provider="fake"))
    resolved_project_id = _resolve_project_id(pipeline, project_id=project_id, project_key=project_key)
    if repair_profile_before_audit:
        pipeline.repair_project_profile(resolved_project_id)
    if propose_outline_repair:
        proposal = pipeline.propose_control_outline_repair(resolved_project_id)
        if output_outline_proposal_json is not None:
            output_outline_proposal_json.parent.mkdir(parents=True, exist_ok=True)
            output_outline_proposal_json.write_text(to_json_text(proposal), encoding="utf-8")
        if output_outline_proposal_md is not None:
            output_outline_proposal_md.parent.mkdir(parents=True, exist_ok=True)
            output_outline_proposal_md.write_text(render_outline_repair_proposal_markdown(proposal), encoding="utf-8")
    payload = pipeline.pipeline_gate_report(resolved_project_id)
    output_gate_json.parent.mkdir(parents=True, exist_ok=True)
    output_gate_json.write_text(to_json_text(payload), encoding="utf-8")
    return PipelineGateReport.model_validate(payload)


def _load_project_gate_report(path: Path | None) -> PipelineGateReport | None:
    if path is None:
        return None
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    return PipelineGateReport.model_validate(data)


def _resolve_project_id(pipeline, *, project_id: str | None, project_key: str | None) -> str:
    if project_id:
        return project_id
    projects = pipeline.projects.list()
    if not projects:
        raise ValueError("No project exists in the supplied storage directory.")
    if not project_key:
        if len(projects) == 1:
            return projects[0].id
        choices = ", ".join(f"{project.id}:{project.name}" for project in projects[:10])
        raise ValueError(f"Multiple projects found. Pass --project-id or --project-key. Candidates: {choices}")
    matches = [
        project
        for project in projects
        if project_key in project.id
        or project_key in project.name
        or project_key == getattr(project, "template_id", "")
    ]
    if not matches:
        choices = ", ".join(f"{project.id}:{project.name}" for project in projects[:10])
        raise ValueError(f"No project matched --project-key={project_key!r}. Candidates: {choices}")
    if len(matches) > 1:
        choices = ", ".join(f"{project.id}:{project.name}" for project in matches[:10])
        raise ValueError(f"Multiple projects matched --project-key={project_key!r}. Pass --project-id. Matches: {choices}")
    return matches[0].id


def _write_report(report: GenerationGoalAuditReport, output_json: Path, output_md: Path) -> None:
    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_md.parent.mkdir(parents=True, exist_ok=True)
    output_json.write_text(to_json_text(report.model_dump(mode="json")), encoding="utf-8")
    output_md.write_text(render_generation_goal_audit_markdown(report), encoding="utf-8")


def render_outline_repair_proposal_markdown(proposal: dict) -> str:
    preview = proposal.get("preview") or {}
    nodes = preview.get("nodes") or []
    lines = [
        "# Outline Repair Proposal",
        "",
        f"- proposal_id: `{proposal.get('id') or '-'}`",
        f"- status: `{proposal.get('status') or '-'}`",
        f"- target_type: `{proposal.get('target_type') or '-'}`",
        f"- target_id: `{proposal.get('target_id') or '-'}`",
        f"- node_count: {len(nodes)}",
        f"- applied: `{str(bool(proposal.get('applied_at'))).lower()}`",
        "",
        "## Suggestion",
        proposal.get("suggestion") or "-",
        "",
        "## Review Boundary",
        "- This proposal has not been applied automatically.",
        "- Apply it only after user review; then sync generation tasks and run source mapping before generation.",
        "- The proposal only changes the editable outline; it does not rewrite existing chapter versions.",
        "",
        "## Proposed Nodes",
    ]
    if not nodes:
        lines.append("- No proposed nodes.")
        return "\n".join(lines).rstrip() + "\n"

    for index, node in enumerate(nodes, start=1):
        lines.extend(
            [
                "",
                f"### {index}. {node.get('title') or '-'}",
                "",
                f"- action: `{node.get('__action') or 'create'}`",
                f"- node_id: `{node.get('node_id') or '-'}`",
                f"- parent_id: `{node.get('parent_id') or '-'}`",
                f"- level: {node.get('level') or '-'}",
                f"- sort_order: {node.get('sort_order') or '-'}",
                f"- enabled: `{str(bool(node.get('enabled', True))).lower()}`",
                f"- target_word_count: {node.get('target_word_count') or '-'}",
                "",
                "#### [主要来源]",
            ]
        )
        lines.extend(_proposal_list(node.get("source_rules")))
        lines.extend(["", "#### [自动补充]"])
        lines.extend(_proposal_list(node.get("auto_fill")))
        lines.extend(["", "#### [人工补充需补充]"])
        lines.extend(_proposal_list(node.get("manual_fill")))
        special_notes = node.get("special_notes") or []
        if special_notes:
            lines.extend(["", "#### [特殊备注]"])
            lines.extend(_proposal_list(special_notes))

    lines.extend(
        [
            "",
            "## Next Step After Review",
            "- Apply the proposal through the outline proposal API or frontend confirmation.",
            "- Regenerate affected chapter tasks only after the editable outline is updated.",
            "- Keep prompt/response traces and selected chapter versions for the final merge.",
        ]
    )
    return "\n".join(lines).rstrip() + "\n"


def _proposal_list(value: object) -> list[str]:
    if not value:
        return ["- -"]
    if isinstance(value, list):
        return [f"- {item}" for item in value]
    return [f"- {value}"]


if __name__ == "__main__":
    raise SystemExit(main())
