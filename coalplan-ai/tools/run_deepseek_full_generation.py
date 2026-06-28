from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from coalplan.application.quality_audit import (
    QualityAuditInput,
    audit_generation_quality,
    render_quality_audit_markdown,
)
from coalplan.application.quality_feedback import build_quality_feedback_plan, render_quality_feedback_plan
from coalplan.application.quality_iteration_learning import (
    build_quality_iteration_learning_report,
    render_quality_iteration_learning_report,
)
from coalplan.application.pattern_library_admin import build_pattern_library_candidate_from_learning_report
from coalplan.application.pattern_skill_export import export_pattern_skill_package
from coalplan.application.pattern_card_usage_audit import audit_pattern_card_usage, write_pattern_card_usage_audit
from coalplan.application.serialization import dump_model, to_json_text
from coalplan.application.targeted_revision_plan import build_targeted_revision_plan, write_targeted_revision_plan
from coalplan.application.word_count_targets import count_words
from coalplan.domain.enums import RunStatus, TaskStatus
from coalplan.main import build_pipeline
from coalplan.settings import Settings


PROJECT_CONFIGS: dict[str, dict[str, str]] = {
    "project_3": {
        "name": "宁夏煤火全量字数控制生成",
        "template_id": "coal_fire",
    },
    "project_4": {
        "name": "拉哇水电全量字数控制生成",
        "template_id": "hydro_diversion_slope",
    },
}


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    parser = argparse.ArgumentParser(description="Run full DeepSeek generation and quality audit for desktop demo projects.")
    parser.add_argument("--input-root", type=Path, default=Path.home() / "Desktop" / "示例输入输出")
    parser.add_argument("--output-root", type=Path, default=None)
    parser.add_argument("--projects", nargs="*", default=["project_3", "project_4"], choices=sorted(PROJECT_CONFIGS))
    parser.add_argument("--max-retries", type=int, default=1)
    parser.add_argument("--chapter-limit", type=int, default=None, help="Generate only the first N outline nodes per project for low-cost validation.")
    parser.add_argument(
        "--chapter-title-contains",
        nargs="*",
        default=[],
        help="Optional title keywords. When provided, only matching outline nodes are considered before chapter-limit is applied.",
    )
    args = parser.parse_args()

    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    output_root = args.output_root or Path.cwd() / f".coalplan-deepseek-full-wordcount-{timestamp}"
    output_root.mkdir(parents=True, exist_ok=True)

    settings = Settings(
        storage_dir=output_root / "storage",
        llm_provider="deepseek",
        structured_llm_provider="deepseek",
        llm_trace_dir=output_root / "traces",
        deepseek_api_key=os.getenv("COALPLAN_DEEPSEEK_API_KEY", ""),
        deepseek_base_url=os.getenv("COALPLAN_DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
        deepseek_model=os.getenv("COALPLAN_DEEPSEEK_MODEL", "deepseek-v4-pro"),
    )
    if not settings.deepseek_api_key:
        raise RuntimeError("COALPLAN_DEEPSEEK_API_KEY is required.")
    pipeline = build_pipeline(settings)

    quality_dir = output_root / "quality_audit"
    quality_dir.mkdir(parents=True, exist_ok=True)
    pattern_skill_snapshot = export_pattern_skill_package(output_dir=output_root / "pattern_skill_active")

    results = []
    for project_key in args.projects:
        demo = {"key": project_key, **PROJECT_CONFIGS[project_key]}
        results.append(
            _run_one(
                pipeline,
                input_root=args.input_root,
                output_root=output_root,
                quality_dir=quality_dir,
                demo=demo,
                max_retries=args.max_retries,
                chapter_limit=args.chapter_limit,
                chapter_title_contains=args.chapter_title_contains,
            )
        )

    summary = {
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "input_root": str(args.input_root.resolve()),
        "output_root": str(output_root.resolve()),
        "model": settings.deepseek_model,
        "pattern_skill_snapshot": _skill_snapshot_summary(pattern_skill_snapshot),
        "projects": results,
    }
    learning = _build_batch_pattern_learning(summary, quality_dir=quality_dir, output_root=output_root)
    summary["pattern_learning"] = learning
    summary["trace_usage_total"] = _trace_usage_summary(output_root / "traces")
    summary["targeted_revision_plan"] = _build_targeted_revision_artifacts(summary, output_root=output_root)
    (output_root / "deepseek_full_generation_summary.json").write_text(to_json_text(summary), encoding="utf-8")
    (output_root / "deepseek_full_generation_report.md").write_text(_render_report(summary), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


def _run_one(
    pipeline,
    *,
    input_root: Path,
    output_root: Path,
    quality_dir: Path,
    demo: dict[str, str],
    max_retries: int,
    chapter_limit: int | None = None,
    chapter_title_contains: list[str] | None = None,
) -> dict[str, Any]:
    project_dir = input_root / demo["key"]
    input_path = _find_input_markdown(project_dir)
    reference_path = _find_reference_markdown(project_dir)
    human_path = project_dir / "human_org.txt"
    if input_path is None:
        raise FileNotFoundError(f"Input markdown not found under: {project_dir}")
    if reference_path is None:
        raise FileNotFoundError(f"Reference generated markdown not found under: {project_dir}")

    trace_start = _trace_usage_summary(output_root / "traces")
    project = pipeline.create_project(demo["name"], template_id=demo["template_id"])
    project = pipeline.ingest_bid_markdown(project.id, file_name=input_path.name, content=input_path.read_text(encoding="utf-8-sig"))
    pipeline.prepare_directory(project.id)
    word_count_plan = pipeline.estimate_outline_word_counts(project.id, reference_path.read_text(encoding="utf-8-sig"))
    workspace_store = pipeline.workspace_store

    selected_node_ids = _selected_generation_node_ids(
        workspace_store.list_outline_nodes(project.id),
        limit=chapter_limit,
        title_contains=chapter_title_contains or [],
    )
    if selected_node_ids is None:
        run = pipeline.generate_all(project.id)
    else:
        run = _generate_selected_chapters(pipeline, project.id, selected_node_ids)
    retries = 0
    while retries < max_retries:
        project_state = pipeline.projects.get(project.id)
        failed_tasks = [
            task
            for task in project_state.runs[-1].chapter_tasks
            if task.status != TaskStatus.passed and (selected_node_ids is None or task.node_id in selected_node_ids)
        ]
        if not failed_tasks:
            break
        retries += 1
        for task in failed_tasks:
            try:
                pipeline.execute_revision_action(project.id, task.node_id)
            except Exception:
                try:
                    pipeline.generate_one(project.id, task.node_id)
                except Exception:
                    pass
        run = pipeline.projects.get(project.id).runs[-1]

    merge_run = pipeline.merge_latest(project.id)
    selected_versions = []
    for node in workspace_store.list_outline_nodes(project.id):
        if not node.get("selected_version_id"):
            continue
        version = workspace_store.get_version(project.id, node["node_id"], node["selected_version_id"])
        selected_versions.append(
            {
                "node_id": node["node_id"],
                "title": node["title"],
                "target_word_count": node.get("target_word_count"),
                "actual_word_count": count_words(version.get("markdown", "")),
                "version_id": version["id"],
                "source_type": version["source_type"],
                "content_tree_nodes": _count_content_nodes(version.get("content_tree", {}).get("nodes", [])),
                "source_links": _count_source_links(version.get("content_tree", {}).get("nodes", [])),
            }
        )

    final_text = ""
    local_final_copy = None
    if merge_run.final_artifact_path:
        final_text = Path(merge_run.final_artifact_path).read_text(encoding="utf-8-sig")
        local_final_copy = output_root / f"{demo['key']}_final.md"
        local_final_copy.write_text(final_text, encoding="utf-8")

    quality_report = None
    feedback_plan = None
    if final_text:
        quality_report = audit_generation_quality(
            QualityAuditInput(
                project_key=demo["key"],
                generated_markdown=final_text,
                source_markdown=input_path.read_text(encoding="utf-8-sig"),
                human_markdown=human_path.read_text(encoding="utf-8-sig") if human_path.exists() else "",
            )
        )
        quality_report["paths"] = {
            "project_dir": str(project_dir),
            "generated": str(local_final_copy) if local_final_copy else None,
            "source": str(input_path),
            "human": str(human_path) if human_path.exists() else None,
        }
        (quality_dir / f"{demo['key']}_quality_audit.json").write_text(to_json_text(quality_report), encoding="utf-8")
        (quality_dir / f"{demo['key']}_quality_audit.md").write_text(render_quality_audit_markdown(quality_report), encoding="utf-8")
        feedback_plan = build_quality_feedback_plan(quality_report)
        (quality_dir / f"{demo['key']}_quality_feedback_plan.json").write_text(to_json_text(dump_model(feedback_plan)), encoding="utf-8")
        (quality_dir / f"{demo['key']}_quality_feedback_plan.md").write_text(render_quality_feedback_plan(feedback_plan), encoding="utf-8")

    project_state = pipeline.projects.get(project.id)
    tasks = project_state.runs[-1].chapter_tasks if project_state.runs else []
    quality_iteration_payload = {
        "project_id": project.id,
        "project_key": demo["key"],
        "status": "warning" if any(task.status != TaskStatus.passed for task in tasks) or (quality_report or {}).get("issues") else "passed",
        "round_count": 0,
        "rounds": [{"project_key": demo["key"], "audit": {"report": quality_report}}] if quality_report else [],
        "final_audit": {"report": quality_report} if quality_report else {},
        "content_revision_targets": pipeline._version_content_revision_targets(project.id),
        "generation_metadata_targets": pipeline._version_generation_metadata_targets(project.id),
    }
    quality_iteration_path = quality_dir / f"{demo['key']}_quality_iteration.json"
    quality_iteration_path.write_text(to_json_text(quality_iteration_payload), encoding="utf-8")
    quality_iteration_learning = pipeline.quality_iteration_learning_report(
        project.id,
        quality_iteration=quality_iteration_payload,
    )
    quality_iteration_learning_path = quality_dir / f"{demo['key']}_quality_iteration_learning.json"
    quality_iteration_learning_path.write_text(to_json_text(quality_iteration_learning), encoding="utf-8")
    artifact_root = (pipeline.artifacts.root / project.id).resolve()
    pattern_card_usage = audit_pattern_card_usage(artifact_root)
    pattern_card_usage_paths = write_pattern_card_usage_audit(pattern_card_usage, quality_dir / f"{demo['key']}_pattern_card_usage")
    trace_end = _trace_usage_summary(output_root / "traces")
    trace_usage = _trace_usage_delta(trace_start, trace_end)
    return {
        "key": demo["key"],
        "project_id": project.id,
        "template_id": demo["template_id"],
        "input_path": str(input_path),
        "reference_path": str(reference_path),
        "human_path": str(human_path) if human_path.exists() else None,
        "source_section_count": len(project_state.sections),
        "outline_node_count": len(workspace_store.list_outline_nodes(project.id)),
        "word_count_estimate_count": len(word_count_plan["estimates"]),
        "generation_scope": "full" if selected_node_ids is None else "partial",
        "selected_node_ids": selected_node_ids,
        "target_word_count_total": sum(item["target_word_count"] or 0 for item in selected_versions),
        "actual_word_count_total": count_words(final_text) if final_text else sum(item["actual_word_count"] for item in selected_versions),
        "task_count": len(tasks),
        "passed_count": sum(1 for task in tasks if task.status == TaskStatus.passed),
        "failed": [
            {"node_id": task.node_id, "title": task.title, "status": task.status.value, "error_message": task.error_message}
            for task in tasks
            if task.status != TaskStatus.passed
        ],
        "run_status": merge_run.status.value,
        "final_artifact_path": merge_run.final_artifact_path,
        "local_final_copy": str(local_final_copy) if local_final_copy else None,
        "selected_versions": selected_versions,
        "trace_count_total": trace_end["call_count"],
        "trace_usage": trace_usage,
        "artifacts_root": str(artifact_root),
        "quality_audit": _quality_summary(quality_report),
        "quality_feedback": _feedback_summary(feedback_plan),
        "pattern_card_usage": _pattern_card_usage_summary(pattern_card_usage),
        "pattern_card_usage_path": pattern_card_usage_paths["json"],
        "pattern_card_usage_markdown_path": pattern_card_usage_paths["markdown"],
        "quality_audit_path": str(quality_dir / f"{demo['key']}_quality_audit.json") if quality_report else None,
        "quality_audit_markdown_path": str(quality_dir / f"{demo['key']}_quality_audit.md") if quality_report else None,
        "quality_feedback_plan_path": str(quality_dir / f"{demo['key']}_quality_feedback_plan.json") if feedback_plan else None,
        "quality_feedback_markdown_path": str(quality_dir / f"{demo['key']}_quality_feedback_plan.md") if feedback_plan else None,
        "quality_iteration_path": str(quality_iteration_path),
        "quality_iteration_learning_path": str(quality_iteration_learning_path),
        "content_revision_target_count": len(quality_iteration_payload["content_revision_targets"]),
        "generation_metadata_target_count": len(quality_iteration_payload["generation_metadata_targets"]),
        "quality_iteration_learning": {
            "status": quality_iteration_learning.get("status"),
            "suggestion_count": len(quality_iteration_learning.get("suggestions") or []),
            "artifact_json_path": quality_iteration_learning.get("artifact_json_path"),
            "artifact_markdown_path": quality_iteration_learning.get("artifact_markdown_path"),
        },
    }


def _selected_generation_node_ids(
    outline_nodes: list[dict[str, Any]],
    *,
    limit: int | None,
    title_contains: list[str],
) -> list[str] | None:
    if limit is None and not title_contains:
        return None
    keywords = [item for item in title_contains if item]
    nodes = [
        node
        for node in sorted(outline_nodes, key=lambda item: (int(item.get("sort_order") or 0), str(item.get("node_id") or "")))
        if node.get("enabled", True) is not False and node.get("node_id")
    ]
    if keywords:
        nodes = [
            node
            for node in nodes
            if any(keyword in str(node.get("title") or "") or keyword in str(node.get("node_id") or "") for keyword in keywords)
        ]
    if limit is not None:
        nodes = nodes[: max(limit, 0)]
    return [str(node["node_id"]) for node in nodes]


def _generate_selected_chapters(pipeline, project_id: str, node_ids: list[str]):
    project = pipeline.projects.get(project_id)
    run = project.runs[-1] if project.runs else pipeline.prepare_run(project_id)
    run.status = RunStatus.running
    for node_id in node_ids:
        try:
            pipeline.generate_one(project_id, node_id)
        except Exception as exc:
            project = pipeline.projects.get(project_id)
            run = project.runs[-1]
            task = next((item for item in run.chapter_tasks if item.node_id == node_id), None)
            if task is not None:
                task.status = TaskStatus.failed
                task.error_message = str(exc)
    project = pipeline.projects.get(project_id)
    run = project.runs[-1]
    selected_tasks = [task for task in run.chapter_tasks if task.node_id in set(node_ids)]
    if not selected_tasks:
        run.status = RunStatus.failed
    elif all(task.status == TaskStatus.passed for task in selected_tasks):
        run.status = RunStatus.completed
    elif any(task.status in {TaskStatus.passed, TaskStatus.needs_repair, TaskStatus.failed} for task in selected_tasks):
        run.status = RunStatus.partial_failed
    else:
        run.status = RunStatus.failed
    pipeline.projects.save(project)
    return run


def _skill_snapshot_summary(snapshot: dict[str, Any]) -> dict[str, Any]:
    manifest = snapshot.get("manifest") or {}
    return {
        "output_dir": snapshot.get("output_dir"),
        "output_path": snapshot.get("output_path"),
        "package_paths": snapshot.get("package_paths") or {},
        "coverage_status": manifest.get("coverage_status"),
        "coverage_issue_count": manifest.get("coverage_issue_count"),
        "pattern_count": manifest.get("pattern_count"),
        "validation_issue_count": len(snapshot.get("validation_issues") or []),
    }


def _build_batch_pattern_learning(
    summary: dict[str, Any],
    *,
    quality_dir: Path,
    output_root: Path,
) -> dict[str, Any]:
    rounds = []
    content_revision_targets = []
    generation_metadata_targets = []
    for project in summary.get("projects") or []:
        path_value = project.get("quality_audit_path")
        if not path_value:
            path = None
        else:
            path = Path(path_value)
        if path and path.exists():
            report = json.loads(path.read_text(encoding="utf-8-sig"))
            rounds.append({"project_key": project.get("key"), "audit": {"report": report}})
        iteration_path_value = project.get("quality_iteration_path")
        if iteration_path_value:
            iteration_path = Path(iteration_path_value)
            if iteration_path.exists():
                iteration = json.loads(iteration_path.read_text(encoding="utf-8-sig"))
                content_revision_targets.extend(
                    target for target in iteration.get("content_revision_targets") or [] if isinstance(target, dict)
                )
                generation_metadata_targets.extend(
                    target for target in iteration.get("generation_metadata_targets") or [] if isinstance(target, dict)
                )

    payload = {
        "status": "warning"
        if any((project.get("quality_audit") or {}).get("issue_count", 0) for project in summary.get("projects") or [])
        or content_revision_targets
        or generation_metadata_targets
        else "passed",
        "round_count": len(rounds),
        "rounds": rounds,
        "final_audit": rounds[-1]["audit"] if rounds else {},
        "content_revision_targets": content_revision_targets,
        "generation_metadata_targets": generation_metadata_targets,
    }
    learning_report = build_quality_iteration_learning_report(
        project_id="deepseek_full_generation_batch",
        quality_iteration=payload,
    )
    learning_dir = output_root / "pattern_learning"
    learning_dir.mkdir(parents=True, exist_ok=True)
    learning_json_path = learning_dir / "deepseek_batch_quality_iteration_learning.json"
    learning_md_path = learning_dir / "deepseek_batch_quality_iteration_learning.md"
    learning_json_path.write_text(to_json_text(dump_model(learning_report)), encoding="utf-8")
    learning_md_path.write_text(render_quality_iteration_learning_report(learning_report), encoding="utf-8")
    candidate = build_pattern_library_candidate_from_learning_report(
        learning_report=dump_model(learning_report),
        output_dir=learning_dir,
    )
    return {
        "status": learning_report.status,
        "suggestion_count": len(learning_report.suggestions),
        "learning_report_path": str(learning_json_path),
        "learning_report_markdown_path": str(learning_md_path),
        "candidate_generated_path": candidate["generated_path"],
        "candidate_markdown_path": candidate["learning_candidate_markdown_path"],
        "candidate_change_count": len(candidate["changes"]),
        "selected_suggestion_indexes": candidate.get("selected_suggestion_indexes"),
    }


def _build_targeted_revision_artifacts(summary: dict[str, Any], *, output_root: Path) -> dict[str, Any]:
    plan = build_targeted_revision_plan(summary)
    paths = write_targeted_revision_plan(plan, output_root / "targeted_revision_plan")
    return {
        "rerun_policy": plan.get("rerun_policy"),
        "action_count": plan.get("action_count", 0),
        "action_counts": plan.get("action_counts") or {},
        "priority_counts": plan.get("priority_counts") or {},
        "project_count": plan.get("project_count", 0),
        "json_path": paths["json"],
        "markdown_path": paths["markdown"],
    }


def _find_input_markdown(project_dir: Path) -> Path | None:
    preferred = project_dir / "投标文档（md版本）.md"
    if preferred.exists():
        return preferred
    candidates = [path for path in sorted(project_dir.glob("*.md")) if "投标" in path.name and "md" in path.name.lower()]
    return candidates[0] if candidates else None


def _find_reference_markdown(project_dir: Path) -> Path | None:
    preferred = project_dir / "生成文档（包含信息来源）.md"
    if preferred.exists():
        return preferred
    candidates = sorted(project_dir.glob("*.md"))
    with_source = [path for path in candidates if "生成" in path.name and "包含" in path.name and "不包含" not in path.name]
    if with_source:
        return with_source[0]
    generated = [path for path in candidates if "生成" in path.name]
    return generated[0] if generated else None


def _quality_summary(report: dict[str, Any] | None) -> dict[str, Any] | None:
    if not report:
        return None
    recommendations = report.get("recommendations", [])
    return {
        "generated_vs_human_ratio": report["word_counts"]["generated_vs_human_ratio"],
        "human_heading_coverage_ratio": report["headings"]["human_heading_coverage_ratio"],
        "source_fact_absorption_ratio": report["source_facts"]["absorption_ratio"],
        "issue_count": len(report["issues"]),
        "issues": report["issues"],
        "recommendation_count": len(recommendations),
        "recommended_actions": [item["action"] for item in recommendations],
    }


def _feedback_summary(plan: Any | None) -> dict[str, Any] | None:
    if not plan:
        return None
    return {
        "action_count": len(plan.actions),
        "actions": [item.action for item in plan.actions],
        "revision_trigger_count": len(plan.revision_triggers),
    }


def _pattern_card_usage_summary(report: dict[str, Any] | None) -> dict[str, Any] | None:
    if not report:
        return None
    summary = report.get("summary") or {}
    return {
        "chapter_count": summary.get("chapter_count", 0),
        "chapters_with_prompt_cards": summary.get("chapters_with_prompt_cards", 0),
        "prompt_card_total": summary.get("prompt_card_total", 0),
        "prompt_card_actionable_total": summary.get("prompt_card_actionable_total", 0),
        "missing_prompt_card_count": summary.get("missing_prompt_card_count", 0),
        "warning_count": summary.get("warning_count", 0),
    }


def _trace_usage_summary(trace_dir: Path) -> dict[str, Any]:
    summary = {
        "call_count": 0,
        "json_call_count": 0,
        "markdown_call_count": 0,
        "error_count": 0,
        "elapsed_seconds_total": 0.0,
        "prompt_char_total": 0,
        "response_char_total": 0,
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "total_tokens": 0,
        "has_token_usage": False,
        "estimated_total_tokens": 0,
    }
    if not trace_dir.exists():
        return summary
    for path in sorted(trace_dir.glob("*.json")):
        try:
            trace = json.loads(path.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError):
            continue
        summary["call_count"] += 1
        kind = trace.get("kind")
        if kind == "json":
            summary["json_call_count"] += 1
        elif kind == "markdown":
            summary["markdown_call_count"] += 1
        if trace.get("error"):
            summary["error_count"] += 1
        summary["elapsed_seconds_total"] += float(trace.get("elapsed_seconds") or 0)
        prompt = trace.get("prompt") or ""
        response = trace.get("response") or ""
        summary["prompt_char_total"] += len(prompt)
        summary["response_char_total"] += len(response)
        usage = trace.get("usage") or {}
        if isinstance(usage, dict):
            prompt_tokens = _safe_int(usage.get("prompt_tokens"))
            completion_tokens = _safe_int(usage.get("completion_tokens"))
            total_tokens = _safe_int(usage.get("total_tokens"))
            if prompt_tokens or completion_tokens or total_tokens:
                summary["has_token_usage"] = True
            summary["prompt_tokens"] += prompt_tokens
            summary["completion_tokens"] += completion_tokens
            summary["total_tokens"] += total_tokens or (prompt_tokens + completion_tokens)
    summary["elapsed_seconds_total"] = round(summary["elapsed_seconds_total"], 3)
    summary["estimated_total_tokens"] = round((summary["prompt_char_total"] + summary["response_char_total"]) / 4)
    return summary


def _trace_usage_delta(start: dict[str, Any], end: dict[str, Any]) -> dict[str, Any]:
    delta = {}
    numeric_keys = [
        "call_count",
        "json_call_count",
        "markdown_call_count",
        "error_count",
        "elapsed_seconds_total",
        "prompt_char_total",
        "response_char_total",
        "prompt_tokens",
        "completion_tokens",
        "total_tokens",
        "estimated_total_tokens",
    ]
    for key in numeric_keys:
        value = (end.get(key) or 0) - (start.get(key) or 0)
        delta[key] = round(value, 3) if key == "elapsed_seconds_total" else value
    delta["has_token_usage"] = bool(delta["prompt_tokens"] or delta["completion_tokens"] or delta["total_tokens"])
    return delta


def _safe_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _count_content_nodes(nodes: list[dict]) -> int:
    return sum(1 + _count_content_nodes(node.get("children", [])) for node in nodes)


def _count_source_links(nodes: list[dict]) -> int:
    return sum(len(node.get("source_links", [])) + _count_source_links(node.get("children", [])) for node in nodes)


def _render_report(summary: dict[str, Any]) -> str:
    lines = [
        "# DeepSeek Full Generation Report",
        "",
        f"- input_root: `{summary['input_root']}`",
        f"- output_root: `{summary['output_root']}`",
        f"- model: `{summary['model']}`",
        f"- active pattern skill coverage: `{(summary.get('pattern_skill_snapshot') or {}).get('coverage_status')}` / issues={(summary.get('pattern_skill_snapshot') or {}).get('coverage_issue_count')}",
        f"- active pattern skill package: `{(summary.get('pattern_skill_snapshot') or {}).get('output_dir')}`",
        f"- batch pattern learning: `{(summary.get('pattern_learning') or {}).get('status')}` / suggestions={(summary.get('pattern_learning') or {}).get('suggestion_count')}",
        f"- batch learning candidate: `{(summary.get('pattern_learning') or {}).get('candidate_generated_path')}`",
        f"- targeted revision rerun policy: `{(summary.get('targeted_revision_plan') or {}).get('rerun_policy')}`",
        f"- targeted revision actions: {(summary.get('targeted_revision_plan') or {}).get('action_count', 0)}",
        f"- targeted revision plan: `{(summary.get('targeted_revision_plan') or {}).get('markdown_path')}`",
        f"- total LLM calls: {(summary.get('trace_usage_total') or {}).get('call_count', 0)}",
        f"- total elapsed LLM seconds: {(summary.get('trace_usage_total') or {}).get('elapsed_seconds_total', 0)}",
        f"- total tokens: {_format_token_usage(summary.get('trace_usage_total') or {})}",
        "",
    ]
    for project in summary["projects"]:
        quality = project.get("quality_audit") or {}
        trace_usage = project.get("trace_usage") or {}
        pattern_cards = project.get("pattern_card_usage") or {}
        lines.extend(
            [
                f"## {project['key']}",
                "",
                f"- project_id: `{project['project_id']}`",
                f"- template_id: `{project['template_id']}`",
                f"- source sections: {project['source_section_count']}",
                f"- outline nodes: {project['outline_node_count']}",
                f"- word count estimates: {project['word_count_estimate_count']}",
                f"- generation scope: `{project.get('generation_scope', 'full')}`; selected nodes={len(project.get('selected_node_ids') or []) if project.get('generation_scope') == 'partial' else 'all'}",
                f"- tasks: {project['passed_count']}/{project['task_count']} passed",
                f"- run status: `{project['run_status']}`",
                f"- target words total: {project['target_word_count_total']}",
                f"- actual words total: {project['actual_word_count_total']}",
                f"- final artifact: `{project['final_artifact_path']}`",
                f"- local final copy: `{project['local_final_copy']}`",
                f"- traces total so far: {project['trace_count_total']}",
                f"- project LLM calls: {trace_usage.get('call_count', 0)} (json={trace_usage.get('json_call_count', 0)}, markdown={trace_usage.get('markdown_call_count', 0)}, errors={trace_usage.get('error_count', 0)})",
                f"- project LLM elapsed seconds: {trace_usage.get('elapsed_seconds_total', 0)}",
                f"- project LLM chars: prompt={trace_usage.get('prompt_char_total', 0)}, response={trace_usage.get('response_char_total', 0)}",
                f"- project tokens: {_format_token_usage(trace_usage)}",
                f"- quality word ratio: {quality.get('generated_vs_human_ratio')}",
                f"- quality heading coverage: {quality.get('human_heading_coverage_ratio')}",
                f"- quality source fact absorption: {quality.get('source_fact_absorption_ratio')}",
                f"- quality recommended actions: {', '.join(quality.get('recommended_actions', [])) or '-'}",
                f"- quality feedback actions: {', '.join((project.get('quality_feedback') or {}).get('actions', [])) or '-'}",
                f"- pattern card chapters: {pattern_cards.get('chapters_with_prompt_cards', 0)}/{pattern_cards.get('chapter_count', 0)}",
                f"- pattern card actions: {pattern_cards.get('prompt_card_actionable_total', 0)}; missing cards: {pattern_cards.get('missing_prompt_card_count', 0)}",
                f"- pattern card usage audit: `{project.get('pattern_card_usage_markdown_path')}`",
                f"- quality audit report: `{project.get('quality_audit_markdown_path')}`",
                f"- quality feedback plan: `{project.get('quality_feedback_markdown_path')}`",
                "",
                "| 章节 | 目标字数 | 实际字数 | 小节数 | 来源链接 |",
                "| --- | ---: | ---: | ---: | ---: |",
            ]
        )
        for version in project["selected_versions"]:
            lines.append(
                f"| {version['title']} | {version['target_word_count'] or ''} | {version['actual_word_count']} | {version['content_tree_nodes']} | {version['source_links']} |"
            )
        if project["failed"]:
            lines.extend(["", "Failed tasks:"])
            lines.extend(f"- {item['title']}: {item['status']} {item['error_message'] or ''}" for item in project["failed"])
        if quality.get("issues"):
            lines.extend(["", "Quality issues:"])
            lines.extend(f"- {item}" for item in quality["issues"])
        lines.append("")
    return "\n".join(lines).strip() + "\n"


def _format_token_usage(trace_usage: dict[str, Any]) -> str:
    if trace_usage.get("has_token_usage"):
        return (
            f"prompt={trace_usage.get('prompt_tokens', 0)}, "
            f"completion={trace_usage.get('completion_tokens', 0)}, "
            f"total={trace_usage.get('total_tokens', 0)}"
        )
    return f"estimated_total={trace_usage.get('estimated_total_tokens', 0)} (from chars/4; provider usage unavailable)"


if __name__ == "__main__":
    main()
