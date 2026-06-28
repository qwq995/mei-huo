from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any, Iterable

from coalplan.application.generation_run_comparison import SUMMARY_FILE_NAME
from coalplan.application.serialization import to_json_text


REVISION_PLAN_FILE_NAME = "targeted_revision_plan.json"


def load_revision_plan_input(path: Path) -> dict[str, Any]:
    path = path.resolve()
    if path.is_dir():
        path = path / SUMMARY_FILE_NAME
    data = _read_json(path)
    if not isinstance(data, dict):
        raise ValueError(f"Generation summary is not valid JSON: {path}")
    return data


def load_generation_run_comparison(path: Path | None) -> dict[str, Any] | None:
    if path is None:
        return None
    path = path.resolve()
    if path.is_dir():
        path = path / "generation_run_comparison.json"
    data = _read_json(path)
    if not isinstance(data, dict):
        raise ValueError(f"Generation comparison is not valid JSON: {path}")
    return data


def build_targeted_revision_plan(
    summary: dict[str, Any],
    *,
    comparison: dict[str, Any] | None = None,
    project_keys: Iterable[str] | None = None,
) -> dict[str, Any]:
    selected_keys = set(project_keys or [])
    projects = []
    for project in summary.get("projects") or []:
        if not isinstance(project, dict):
            continue
        key = str(project.get("key") or project.get("project_id") or "")
        if selected_keys and key not in selected_keys:
            continue
        projects.append(_project_revision_plan(project, comparison=comparison))
    actions = [action for project in projects for action in project.get("actions") or []]
    action_counts = Counter(action.get("action") for action in actions)
    priority_counts = Counter(action.get("priority") for action in actions)
    return {
        "source_output_root": summary.get("output_root"),
        "source_model": summary.get("model"),
        "comparison_verdict": (comparison or {}).get("verdict"),
        "project_count": len(projects),
        "action_count": len(actions),
        "action_counts": dict(sorted(action_counts.items())),
        "priority_counts": dict(sorted(priority_counts.items())),
        "rerun_policy": _rerun_policy(projects, comparison=comparison),
        "projects": projects,
    }


def write_targeted_revision_plan(plan: dict[str, Any], output_dir: Path) -> dict[str, str]:
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / REVISION_PLAN_FILE_NAME
    markdown_path = output_dir / "targeted_revision_plan.md"
    json_path.write_text(to_json_text(plan), encoding="utf-8")
    markdown_path.write_text(render_targeted_revision_plan(plan), encoding="utf-8")
    return {"json": str(json_path), "markdown": str(markdown_path)}


def render_targeted_revision_plan(plan: dict[str, Any]) -> str:
    lines = [
        "# Targeted Revision Plan",
        "",
        f"- source_output_root: `{plan.get('source_output_root')}`",
        f"- source_model: `{plan.get('source_model')}`",
        f"- comparison_verdict: `{plan.get('comparison_verdict') or '-'}`",
        f"- project_count: {plan.get('project_count', 0)}",
        f"- action_count: {plan.get('action_count', 0)}",
        f"- rerun_policy: {plan.get('rerun_policy')}",
        "",
        "## Action Counts",
        "",
    ]
    counts = plan.get("action_counts") or {}
    if counts:
        lines.extend(f"- {key}: {value}" for key, value in counts.items())
    else:
        lines.append("- No revision action required.")
    for project in plan.get("projects") or []:
        lines.extend(
            [
                "",
                f"## {project.get('key')}",
                "",
                f"- run_status: `{project.get('run_status')}`",
                f"- generation_scope: `{project.get('generation_scope')}`",
                f"- tasks: {project.get('passed_count', 0)}/{project.get('task_count', 0)} passed",
                f"- failed_or_needs_repair: {project.get('failed_count', 0)}",
                f"- recommended_scope: {project.get('recommended_scope')}",
                "",
                "| priority | action | node | reason | endpoint |",
                "| --- | --- | --- | --- | --- |",
            ]
        )
        actions = project.get("actions") or []
        if not actions:
            lines.append("| - | accept | - | No automated revision required. | - |")
        for action in actions:
            lines.append(
                "| {priority} | {action} | {node} | {reason} | {endpoint} |".format(
                    priority=action.get("priority") or "-",
                    action=action.get("action") or "-",
                    node=_cell(action.get("title") or action.get("node_id") or "-"),
                    reason=_cell(action.get("reason") or "-"),
                    endpoint=_cell(action.get("endpoint_hint") or "-"),
                )
            )
        for action in actions:
            requirements = action.get("next_prompt_context") or []
            if not requirements:
                continue
            lines.extend(["", f"### {action.get('title') or action.get('node_id')}", ""])
            lines.append(f"- action: `{action.get('action')}`")
            lines.append("- next_prompt_context:")
            lines.extend(f"  - {item}" for item in requirements)
    lines.extend(
        [
            "",
            "## Control Rule",
            "",
            "- Do not repeat the same prompt after a failed chapter.",
            "- Carry failure reason, source mapping, evidence audit, omitted source facts, unused high-value evidence, supplements, and target word count into the next attempt.",
            "- Prefer chapter-level revision. Rebuild the whole document only when input normalization, template selection, or outline coverage has changed.",
        ]
    )
    return "\n".join(lines).strip() + "\n"


def _project_revision_plan(project: dict[str, Any], *, comparison: dict[str, Any] | None) -> dict[str, Any]:
    actions = [_failure_action(project, failure) for failure in project.get("failed") or []]
    actions.extend(_quality_actions(project))
    actions.extend(_pattern_card_actions(project))
    actions = _dedupe_actions(sorted(actions, key=_action_sort_key))
    task_count = _number(project.get("task_count"))
    passed_count = _number(project.get("passed_count"))
    return {
        "key": project.get("key"),
        "project_id": project.get("project_id"),
        "template_id": project.get("template_id"),
        "run_status": project.get("run_status"),
        "generation_scope": project.get("generation_scope") or "full",
        "task_count": task_count,
        "passed_count": passed_count,
        "failed_count": len(project.get("failed") or []),
        "pass_rate": round(passed_count / task_count, 4) if task_count else None,
        "recommended_scope": _recommended_project_scope(project, actions, comparison=comparison),
        "actions": actions,
    }


def _failure_action(project: dict[str, Any], failure: dict[str, Any]) -> dict[str, Any]:
    message = str(failure.get("error_message") or "")
    title = str(failure.get("title") or failure.get("node_id") or "")
    node_id = str(failure.get("node_id") or "")
    action, stage, priority = _classify_failure(message, title)
    return {
        "action_id": f"{project.get('key')}.{node_id}.{action}",
        "project_key": project.get("key"),
        "node_id": node_id,
        "title": title,
        "status": failure.get("status"),
        "action": action,
        "stage": stage,
        "priority": priority,
        "requires_llm": action
        in {"repair_format", "remap_sources", "regenerate_evidence_targeted", "regenerate_with_manual_placeholders", "expand_subsections"},
        "requires_user_confirmation": action in {"request_human_input", "disable_node", "expand_subsections"},
        "reason": _failure_reason(message, action),
        "error_message": message,
        "endpoint_hint": _endpoint_hint(project, node_id, action),
        "next_prompt_context": _next_prompt_context(message, action),
    }


def _quality_actions(project: dict[str, Any]) -> list[dict[str, Any]]:
    quality = project.get("quality_audit") or {}
    actions: list[dict[str, Any]] = []
    for action in quality.get("recommended_actions") or []:
        action = str(action)
        if action == "increase_detail_budget":
            actions.append(_project_level_action(project, action, "detail", "normal", "Increase target word counts or split sparse chapters."))
        elif action in {"repair_outline_coverage", "add_missing_common_topics"}:
            actions.append(_project_level_action(project, action, "outline", "high", "Create outline proposals before more chapter generation."))
        elif action == "strengthen_evidence_utilization":
            actions.append(_project_level_action(project, action, "mapping", "high", "Improve source mapping and required source facts before regenerating affected chapters."))
        else:
            actions.append(_project_level_action(project, action, "quality_feedback", "normal", "Apply quality audit feedback."))
    return actions


def _pattern_card_actions(project: dict[str, Any]) -> list[dict[str, Any]]:
    usage = project.get("pattern_card_usage") or {}
    missing = _number(usage.get("missing_prompt_card_count"))
    if missing <= 0:
        return []
    return [
        _project_level_action(
            project,
            "persist_pattern_prompt_cards",
            "generation_metadata",
            "high",
            f"{missing} generated chapters lack pattern-card traceability.",
            requires_llm=False,
        )
    ]


def _project_level_action(
    project: dict[str, Any],
    action: str,
    stage: str,
    priority: str,
    reason: str,
    *,
    requires_llm: bool = True,
) -> dict[str, Any]:
    return {
        "action_id": f"{project.get('key')}.{stage}.{action}",
        "project_key": project.get("key"),
        "node_id": None,
        "title": action,
        "action": action,
        "stage": stage,
        "priority": priority,
        "requires_llm": requires_llm,
        "requires_user_confirmation": stage in {"outline", "detail"},
        "reason": reason,
        "endpoint_hint": f"/projects/{project.get('project_id')}/{stage}",
        "next_prompt_context": _project_prompt_context(action),
    }


def _classify_failure(message: str, title: str) -> tuple[str, str, str]:
    text = f"{message}\n{title}".lower()
    if any(token in text for token in ["missing section", "missing_required_heading", "json output", "markdown", "format"]):
        return "repair_format", "revision", "high"
    if any(token in text for token in ["no mapping", "missing source summary", "invalid section", "source ids do not exist"]):
        return "remap_sources", "mapping", "high"
    if any(token in text for token in ["omitted_required_source_facts", "low_evidence_utilization", "evidence was not sufficiently absorbed"]):
        return "regenerate_evidence_targeted", "generation", "high"
    if any(token in text for token in ["possible_guessed_fact", "unsupported", "manual-fill"]):
        return "regenerate_with_manual_placeholders", "generation", "high"
    if any(token in text for token in ["too short", "split", "dense", "subsection"]):
        return "expand_subsections", "detail", "normal"
    if any(token in text for token in ["drawing", "approval", "site measurement", "personnel", "equipment", "contract"]):
        return "request_human_input", "supplement", "normal"
    return "regenerate_evidence_targeted", "generation", "normal"


def _failure_reason(message: str, action: str) -> str:
    if action == "repair_format":
        return "Chapter failed the fixed Markdown contract; repair structure without changing facts."
    if action == "remap_sources":
        return "Source mapping or cited section ids are insufficient; remap before factual writing."
    if action == "regenerate_evidence_targeted":
        return "Generated text did not absorb mapped evidence; regenerate only this chapter with omitted facts and evidence audit context."
    if action == "regenerate_with_manual_placeholders":
        return "Generated text likely treated unconfirmed facts as certain; regenerate with manual placeholders for missing parameters."
    if action == "expand_subsections":
        return "Chapter is too dense or too short; split into source-derived subsections before generation."
    if action == "request_human_input":
        return "Required facts depend on user, site, drawing, contract, approval, or measurement input."
    return message or "Chapter did not pass revision gate."


def _next_prompt_context(message: str, action: str) -> list[str]:
    base = [
        "current chapter title and node_id",
        "previous failure reason and validation status",
        "current target_word_count and detail policy",
        "mapped source sections and evidence spans",
        "chapter supplements and selected historical version if present",
    ]
    if action == "repair_format":
        return base + ["bad markdown output", "required headings only; do not add new facts"]
    if action == "remap_sources":
        return base + ["full source toc", "previous main source requirements", "invalid or missing source ids"]
    if action == "regenerate_evidence_targeted":
        return base + [
            "omitted_required_source_facts from evidence audit",
            "unused_high_value_evidence_ids",
            "manual items already supported by source evidence",
            f"raw failure message: {message}",
        ]
    if action == "regenerate_with_manual_placeholders":
        return base + ["facts that must remain as `【需人工补充：...】` when unsupported"]
    if action == "expand_subsections":
        return base + ["source-derived subsection proposals", "dense craft pattern card"]
    if action == "request_human_input":
        return ["manual supplement form fields", "missing drawings/site/contract/approval/measurement list"]
    return base + [f"raw failure message: {message}"]


def _project_prompt_context(action: str) -> list[str]:
    if action == "increase_detail_budget":
        return ["human reference word count by heading", "current target_word_count", "source evidence density"]
    if action in {"repair_outline_coverage", "add_missing_common_topics"}:
        return ["project profile", "source toc", "template tree", "missing heading/topic examples"]
    if action == "strengthen_evidence_utilization":
        return ["omitted source fact examples", "trace diagnostics", "source mapping requirements"]
    if action == "persist_pattern_prompt_cards":
        return ["generation policy", "selected writing pattern keys", "pattern prompt cards"]
    return ["quality audit report", "quality feedback plan"]


def _endpoint_hint(project: dict[str, Any], node_id: str, action: str) -> str:
    project_id = project.get("project_id") or "{project_id}"
    if action == "repair_format":
        return f"/projects/{project_id}/chapters/{node_id}/revision-action"
    if action in {"remap_sources", "regenerate_evidence_targeted", "regenerate_with_manual_placeholders"}:
        return f"/projects/{project_id}/chapters/{node_id}/generate"
    if action == "expand_subsections":
        return f"/projects/{project_id}/outline/subsection-proposals"
    if action == "request_human_input":
        return f"/projects/{project_id}/chapters/{node_id}/supplements"
    return f"/projects/{project_id}/chapters/{node_id}"


def _recommended_project_scope(
    project: dict[str, Any],
    actions: list[dict[str, Any]],
    *,
    comparison: dict[str, Any] | None,
) -> str:
    if not actions:
        return "accept_or_merge_selected_versions"
    if any(action.get("stage") == "outline" for action in actions):
        return "repair_outline_then_regenerate_affected_chapters"
    if any(action.get("stage") == "detail" for action in actions):
        return "split_or_resize_then_generate_affected_chapters"
    if all(action.get("node_id") for action in actions):
        return "chapter_level_only"
    verdict = (comparison or {}).get("verdict")
    if verdict == "regressed":
        return "partial_validation_before_full_run"
    return "project_level_control_then_chapter_level_revision"


def _rerun_policy(projects: list[dict[str, Any]], *, comparison: dict[str, Any] | None) -> str:
    if not projects:
        return "no_project"
    scopes = {project.get("recommended_scope") for project in projects}
    if scopes == {"accept_or_merge_selected_versions"}:
        return "no_regeneration_required"
    if "repair_outline_then_regenerate_affected_chapters" in scopes:
        return "outline_repair_before_chapter_generation"
    if "partial_validation_before_full_run" in scopes or (comparison or {}).get("verdict") == "regressed":
        return "partial_validation_before_full_run"
    if all(scope in {"chapter_level_only", "accept_or_merge_selected_versions"} for scope in scopes):
        return "chapter_level_revision_only"
    return "targeted_project_controls_then_chapter_revision"


def _dedupe_actions(actions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    seen: set[str] = set()
    for action in actions:
        key = str(action.get("action_id") or "")
        if key in seen:
            continue
        seen.add(key)
        output.append(action)
    return output


def _action_sort_key(action: dict[str, Any]) -> tuple[int, str, str]:
    priority_order = {"critical": 0, "high": 1, "normal": 2, "low": 3}
    stage_order = {"outline": "01", "detail": "02", "mapping": "03", "generation": "04", "revision": "05", "supplement": "06"}
    return (
        priority_order.get(str(action.get("priority") or "normal"), 2),
        stage_order.get(str(action.get("stage") or ""), "99"),
        str(action.get("action_id") or ""),
    )


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return None


def _number(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _cell(value: Any) -> str:
    return str(value or "").replace("|", "\\|").replace("\n", " ")
