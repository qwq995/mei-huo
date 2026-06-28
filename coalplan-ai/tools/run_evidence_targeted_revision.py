from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from coalplan.application.serialization import to_json_text
from coalplan.domain.enums import TaskStatus
from coalplan.main import build_pipeline
from coalplan.settings import Settings


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    parser = argparse.ArgumentParser(
        description="Run chapter-level evidence-targeted revisions against an existing persisted generation run."
    )
    parser.add_argument("--run-root", type=Path, required=True, help="Existing output root, for example .coalplan-deepseek-project3-flash-...")
    parser.add_argument("--project-id", default=None)
    parser.add_argument("--project-key", default="project_3", help="Used to infer project_id from deepseek_full_generation_summary.json.")
    parser.add_argument("--node-id", action="append", default=[], help="Specific outline node id to revise. Can be repeated.")
    parser.add_argument("--title-contains", action="append", default=[], help="Revise matching failed/needs-repair task titles. Can be repeated.")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--action", default="regenerate", choices=["regenerate", "remap_sources", "repair_format"])
    parser.add_argument("--provider", default=os.getenv("COALPLAN_LLM_PROVIDER", "deepseek"))
    parser.add_argument("--structured-provider", default=os.getenv("COALPLAN_STRUCTURED_LLM_PROVIDER"))
    parser.add_argument("--model", default=os.getenv("COALPLAN_DEEPSEEK_MODEL", "deepseek-v4-flash"))
    parser.add_argument("--output-dir", type=Path, default=None)
    parser.add_argument("--in-place", action="store_true", help="Modify --run-root directly. By default a working copy is created under --output-dir.")
    args = parser.parse_args()

    source_run_root = args.run_root.resolve()
    output_dir = args.output_dir or Path.cwd() / f".coalplan-evidence-targeted-revision-{datetime.now():%Y%m%d-%H%M%S}"
    output_dir.mkdir(parents=True, exist_ok=True)
    run_root = source_run_root if args.in_place else _copy_run_root_for_revision(source_run_root, output_dir)

    project_id = args.project_id or _project_id_from_summary(run_root, args.project_key)
    settings = Settings(
        storage_dir=run_root / "storage",
        llm_provider=args.provider,
        structured_llm_provider=args.structured_provider or args.provider,
        llm_trace_dir=output_dir / "traces",
        deepseek_api_key=os.getenv("COALPLAN_DEEPSEEK_API_KEY", ""),
        deepseek_base_url=os.getenv("COALPLAN_DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
        deepseek_model=args.model,
        minimax_api_key=os.getenv("COALPLAN_MINIMAX_API_KEY", ""),
        minimax_base_url=os.getenv("COALPLAN_MINIMAX_BASE_URL", "https://api.minimaxi.com/v1"),
        minimax_model=os.getenv("COALPLAN_MINIMAX_MODEL", "MiniMax-M2.7"),
    )
    if settings.llm_provider == "deepseek" and not settings.deepseek_api_key:
        raise RuntimeError("COALPLAN_DEEPSEEK_API_KEY is required for --provider deepseek.")

    pipeline = build_pipeline(settings)
    project = pipeline.projects.get(project_id)
    node_ids = _select_node_ids(
        project,
        explicit_node_ids=args.node_id,
        title_contains=args.title_contains,
        limit=args.limit,
    )
    if not node_ids:
        raise RuntimeError("No matching failed/needs-repair node was found. Pass --node-id or adjust --title-contains.")

    results: list[dict[str, Any]] = []
    for node_id in node_ids:
        before = _task_snapshot(project, node_id)
        before_audit = _node_validation_audit(run_root, project_id, project, node_id)
        try:
            result = pipeline.execute_revision_action(project_id, node_id, action=args.action)
            project = pipeline.projects.get(project_id)
            after = _task_snapshot(project, node_id)
            draft = result.get("draft") if isinstance(result, dict) else None
            after_audit = (draft or {}).get("evidence_audit") if isinstance(draft, dict) else None
            results.append(
                {
                    "node_id": node_id,
                    "title": before.get("title") or after.get("title"),
                    "action": args.action,
                    "status": "ok",
                    "before": before,
                    "after": after,
                    "before_evidence_audit": _audit_summary(before_audit),
                    "after_evidence_audit": _audit_summary(after_audit),
                    "evidence_delta": _audit_delta(before_audit, after_audit),
                    "result_kind": result.get("kind") if isinstance(result, dict) else None,
                    "draft_status": ((draft or {}).get("validation_status") if isinstance(draft, dict) else None),
                }
            )
        except Exception as exc:
            results.append(
                {
                    "node_id": node_id,
                    "title": before.get("title"),
                    "action": args.action,
                    "status": "failed",
                    "before": before,
                    "before_evidence_audit": _audit_summary(before_audit),
                    "error": str(exc),
                }
            )

    summary = {
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "source_run_root": str(source_run_root),
        "run_root": str(run_root),
        "in_place": bool(args.in_place),
        "storage_dir": str((run_root / "storage").resolve()),
        "project_id": project_id,
        "project_key": args.project_key,
        "provider": settings.llm_provider,
        "structured_provider": settings.structured_llm_provider,
        "model": args.model,
        "node_count": len(node_ids),
        "results": results,
    }
    json_path = output_dir / "evidence_targeted_revision_summary.json"
    md_path = output_dir / "evidence_targeted_revision_report.md"
    json_path.write_text(to_json_text(summary), encoding="utf-8")
    md_path.write_text(_render_report(summary), encoding="utf-8")
    print(json.dumps({**summary, "summary_path": str(json_path), "report_path": str(md_path)}, ensure_ascii=False, indent=2))


def _project_id_from_summary(run_root: Path, project_key: str) -> str:
    summary_path = run_root / "deepseek_full_generation_summary.json"
    if not summary_path.exists():
        raise RuntimeError("--project-id is required when deepseek_full_generation_summary.json is not available.")
    summary = json.loads(summary_path.read_text(encoding="utf-8-sig"))
    for project in summary.get("projects") or []:
        if project.get("key") == project_key:
            return str(project["project_id"])
    raise RuntimeError(f"Project key not found in summary: {project_key}")


def _copy_run_root_for_revision(source_run_root: Path, output_dir: Path) -> Path:
    if not source_run_root.exists():
        raise FileNotFoundError(f"Run root not found: {source_run_root}")
    working_root = output_dir / "working_run_root"
    if working_root.exists():
        shutil.rmtree(working_root)
    ignore = shutil.ignore_patterns("traces", "pattern_skill_active", "pattern_learning", "quality_audit", "targeted_revision_plan")
    shutil.copytree(source_run_root, working_root, ignore=ignore)
    return working_root


def _select_node_ids(project, *, explicit_node_ids: list[str], title_contains: list[str], limit: int | None) -> list[str]:
    if explicit_node_ids:
        return explicit_node_ids[:limit] if limit is not None else explicit_node_ids
    if not project.runs:
        return []
    keywords = [item for item in title_contains if item]
    output: list[str] = []
    for task in project.runs[-1].chapter_tasks:
        if task.status == TaskStatus.passed:
            continue
        if keywords and not any(keyword in task.title or keyword in task.node_id for keyword in keywords):
            continue
        output.append(task.node_id)
        if limit is not None and len(output) >= limit:
            break
    return output


def _task_snapshot(project, node_id: str) -> dict[str, Any]:
    run = project.runs[-1] if project.runs else None
    task = next((item for item in (run.chapter_tasks if run else []) if item.node_id == node_id), None)
    if task is None:
        return {"node_id": node_id}
    return {
        "node_id": task.node_id,
        "title": task.title,
        "status": task.status.value,
        "error_message": task.error_message,
        "source_section_ids": [match.section_id for match in task.source_matches],
        "evidence_count": len(task.source_mapping.evidence) if task.source_mapping else 0,
    }


def _node_validation_audit(run_root: Path, project_id: str, project, node_id: str) -> dict[str, Any] | None:
    run = project.runs[-1] if project.runs else None
    if run is None:
        return None
    validation_path = run_root / "storage" / "artifacts" / project_id / "runs" / run.id / "validation.json"
    if not validation_path.exists():
        return None
    try:
        payload = json.loads(validation_path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return None
    for item in payload.get("tasks") or []:
        if isinstance(item, dict) and item.get("node_id") == node_id:
            audit = item.get("evidence_audit")
            return audit if isinstance(audit, dict) else None
    return None


def _audit_summary(audit: dict[str, Any] | None) -> dict[str, Any] | None:
    if not audit:
        return None
    omitted_ids = {str(item) for item in audit.get("omitted_required_fact_ids") or []}
    facts = [
        item
        for item in audit.get("required_source_facts") or []
        if isinstance(item, dict) and str(item.get("fact_id")) in omitted_ids
    ]
    issues = [item for item in audit.get("issues") or [] if isinstance(item, dict)]
    return {
        "coverage_ratio": audit.get("coverage_ratio"),
        "issue_codes": [str(item.get("code")) for item in issues if item.get("code")],
        "omitted_required_fact_count": len(omitted_ids),
        "omitted_required_facts": [
            {
                "fact_id": item.get("fact_id"),
                "evidence_id": item.get("evidence_id"),
                "section_id": item.get("section_id"),
                "fact_type": item.get("fact_type"),
                "text": item.get("text"),
            }
            for item in facts[:12]
        ],
        "omitted_feedback_fact_hints": list(audit.get("omitted_feedback_fact_hints") or [])[:12],
        "unused_high_value_evidence_ids": list(audit.get("unused_high_value_evidence_ids") or [])[:12],
        "manual_items_with_source_support": list(audit.get("manual_items_with_source_support") or [])[:12],
    }


def _audit_delta(before: dict[str, Any] | None, after: dict[str, Any] | None) -> dict[str, Any]:
    before_summary = _audit_summary(before) or {}
    after_summary = _audit_summary(after) or {}
    before_omitted = {
        str(item.get("fact_id"))
        for item in before_summary.get("omitted_required_facts") or []
        if isinstance(item, dict) and item.get("fact_id")
    }
    after_omitted = {
        str(item.get("fact_id"))
        for item in after_summary.get("omitted_required_facts") or []
        if isinstance(item, dict) and item.get("fact_id")
    }
    before_unused = set(str(item) for item in before_summary.get("unused_high_value_evidence_ids") or [])
    after_unused = set(str(item) for item in after_summary.get("unused_high_value_evidence_ids") or [])
    return {
        "coverage_ratio_before": before_summary.get("coverage_ratio"),
        "coverage_ratio_after": after_summary.get("coverage_ratio"),
        "omitted_required_fact_count_before": before_summary.get("omitted_required_fact_count"),
        "omitted_required_fact_count_after": after_summary.get("omitted_required_fact_count"),
        "resolved_required_fact_ids": sorted(before_omitted - after_omitted),
        "new_required_fact_ids": sorted(after_omitted - before_omitted),
        "resolved_unused_evidence_ids": sorted(before_unused - after_unused),
        "new_unused_evidence_ids": sorted(after_unused - before_unused),
    }


def _render_report(summary: dict[str, Any]) -> str:
    lines = [
        "# Evidence Targeted Revision Report",
        "",
        f"- source_run_root: `{summary.get('source_run_root') or summary['run_root']}`",
        f"- run_root: `{summary['run_root']}`",
        f"- in_place: `{summary.get('in_place')}`",
        f"- project_id: `{summary['project_id']}`",
        f"- provider: `{summary['provider']}`",
        f"- model: `{summary['model']}`",
        f"- node_count: {summary['node_count']}",
        "",
        "| node | action | before | after | result |",
        "| --- | --- | --- | --- | --- |",
    ]
    for item in summary["results"]:
        before = (item.get("before") or {}).get("status") or "-"
        after = (item.get("after") or {}).get("status") or "-"
        result = item.get("draft_status") or item.get("status")
        lines.append(f"| {item.get('title') or item.get('node_id')} | {item.get('action')} | {before} | {after} | {result} |")
        delta = item.get("evidence_delta") or {}
        if delta:
            lines.extend(
                [
                    "",
                    f"### {item.get('title') or item.get('node_id')}",
                    "",
                    f"- coverage_ratio: {delta.get('coverage_ratio_before')} -> {delta.get('coverage_ratio_after')}",
                    f"- omitted_required_fact_count: {delta.get('omitted_required_fact_count_before')} -> {delta.get('omitted_required_fact_count_after')}",
                    f"- resolved_required_fact_ids: {', '.join(delta.get('resolved_required_fact_ids') or []) or '-'}",
                    f"- new_required_fact_ids: {', '.join(delta.get('new_required_fact_ids') or []) or '-'}",
                    f"- resolved_unused_evidence_ids: {', '.join(delta.get('resolved_unused_evidence_ids') or []) or '-'}",
                    f"- new_unused_evidence_ids: {', '.join(delta.get('new_unused_evidence_ids') or []) or '-'}",
                ]
            )
        before_audit = item.get("before_evidence_audit") or {}
        after_audit = item.get("after_evidence_audit") or {}
        if before_audit.get("omitted_required_facts"):
            lines.extend(["", "Before omitted facts:"])
            lines.extend(
                f"- `{fact.get('fact_id')}` {fact.get('text')}"
                for fact in before_audit.get("omitted_required_facts", [])[:6]
                if isinstance(fact, dict)
            )
        if after_audit.get("omitted_required_facts"):
            lines.extend(["", "After omitted facts:"])
            lines.extend(
                f"- `{fact.get('fact_id')}` {fact.get('text')}"
                for fact in after_audit.get("omitted_required_facts", [])[:6]
                if isinstance(fact, dict)
            )
        if item.get("error"):
            lines.append(f"\n- `{item.get('node_id')}` error: {item['error']}")
    return "\n".join(lines).strip() + "\n"


if __name__ == "__main__":
    main()
