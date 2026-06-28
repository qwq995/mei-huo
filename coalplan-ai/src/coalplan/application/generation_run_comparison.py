from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from coalplan.application.serialization import to_json_text


SUMMARY_FILE_NAME = "deepseek_full_generation_summary.json"


def load_generation_run_summary(path: Path) -> dict[str, Any]:
    """Load a DeepSeek generation summary from a JSON file or output directory."""

    path = path.resolve()
    if path.is_dir():
        path = path / SUMMARY_FILE_NAME
    data = _read_json(path)
    if not isinstance(data, dict):
        raise ValueError(f"Generation run summary is not valid JSON: {path}")
    return data


def compare_generation_run_summaries(
    baseline: dict[str, Any],
    candidate: dict[str, Any],
    *,
    baseline_label: str = "baseline",
    candidate_label: str = "candidate",
) -> dict[str, Any]:
    baseline_projects = _projects_by_key(baseline)
    candidate_projects = _projects_by_key(candidate)
    project_keys = sorted(set(baseline_projects) | set(candidate_projects))
    projects = [
        _compare_project(baseline_projects.get(key), candidate_projects.get(key), key=key)
        for key in project_keys
    ]
    summary_delta = _summary_delta(baseline, candidate, projects)
    return {
        "baseline_label": baseline_label,
        "candidate_label": candidate_label,
        "baseline_output_root": baseline.get("output_root"),
        "candidate_output_root": candidate.get("output_root"),
        "baseline_model": baseline.get("model"),
        "candidate_model": candidate.get("model"),
        "baseline_project_count": len(baseline_projects),
        "candidate_project_count": len(candidate_projects),
        "summary_delta": summary_delta,
        "projects": projects,
        "verdict": _comparison_verdict(projects, summary_delta),
        "recommended_next_actions": _recommended_next_actions(projects, summary_delta),
    }


def write_generation_run_comparison(comparison: dict[str, Any], output_dir: Path) -> dict[str, str]:
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "generation_run_comparison.json"
    markdown_path = output_dir / "generation_run_comparison.md"
    json_path.write_text(to_json_text(comparison), encoding="utf-8")
    markdown_path.write_text(render_generation_run_comparison(comparison), encoding="utf-8")
    return {"json": str(json_path), "markdown": str(markdown_path)}


def render_generation_run_comparison(comparison: dict[str, Any]) -> str:
    delta = comparison.get("summary_delta") or {}
    lines = [
        "# Generation Run Comparison",
        "",
        f"- baseline: `{comparison.get('baseline_label')}`",
        f"- candidate: `{comparison.get('candidate_label')}`",
        f"- baseline_model: `{comparison.get('baseline_model')}`",
        f"- candidate_model: `{comparison.get('candidate_model')}`",
        f"- verdict: `{comparison.get('verdict')}`",
        f"- pass_rate_delta: {_fmt_delta(delta.get('pass_rate_delta'))}",
        f"- passed_count_delta: {_fmt_delta(delta.get('passed_count_delta'))}",
        f"- failed_count_delta: {_fmt_delta(delta.get('failed_count_delta'))}",
        f"- actual_word_count_delta: {_fmt_delta(delta.get('actual_word_count_total_delta'))}",
        f"- llm_call_count_delta: {_fmt_delta(delta.get('llm_call_count_delta'))}",
        f"- token_delta: {_fmt_delta(delta.get('total_tokens_delta'))}",
        f"- estimated_token_delta: {_fmt_delta(delta.get('estimated_total_tokens_delta'))}",
        f"- pattern_card_chapter_delta: {_fmt_delta(delta.get('chapters_with_prompt_cards_delta'))}",
        f"- missing_pattern_card_delta: {_fmt_delta(delta.get('missing_prompt_card_count_delta'))}",
        "",
        "## Project Deltas",
        "",
        "| project | scope | pass rate | passed | failed | words | calls | tokens | pattern cards | source absorption | heading coverage |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for item in comparison.get("projects") or []:
        base_scope = (item.get("baseline") or {}).get("generation_scope") or "-"
        cand_scope = (item.get("candidate") or {}).get("generation_scope") or "-"
        item_delta = item.get("delta") or {}
        lines.append(
            "| {project} | {scope} | {pass_rate} | {passed} | {failed} | {words} | {calls} | {tokens} | {cards} | {source} | {heading} |".format(
                project=item.get("key") or "-",
                scope=f"{base_scope}->{cand_scope}",
                pass_rate=_fmt_delta(item_delta.get("pass_rate_delta")),
                passed=_fmt_delta(item_delta.get("passed_count_delta")),
                failed=_fmt_delta(item_delta.get("failed_count_delta")),
                words=_fmt_delta(item_delta.get("actual_word_count_total_delta")),
                calls=_fmt_delta(item_delta.get("llm_call_count_delta")),
                tokens=_fmt_delta(item_delta.get("total_tokens_delta")),
                cards=_fmt_delta(item_delta.get("chapters_with_prompt_cards_delta")),
                source=_fmt_delta(item_delta.get("source_fact_absorption_ratio_delta")),
                heading=_fmt_delta(item_delta.get("human_heading_coverage_ratio_delta")),
            )
        )
    lines.extend(["", "## Next Actions", ""])
    actions = comparison.get("recommended_next_actions") or []
    if actions:
        lines.extend(f"- {item}" for item in actions)
    else:
        lines.append("- No automated action recommendation.")
    lines.extend(["", "## Per-Project Notes", ""])
    for item in comparison.get("projects") or []:
        lines.extend([f"### {item.get('key')}", ""])
        notes = item.get("notes") or []
        if notes:
            lines.extend(f"- {note}" for note in notes)
        else:
            lines.append("- No project-specific note.")
        failures = (item.get("candidate") or {}).get("failed") or []
        if failures:
            lines.append("- candidate_failed_tasks:")
            for failure in failures[:8]:
                lines.append(
                    f"  - {failure.get('title') or failure.get('node_id')}: {failure.get('status')} {failure.get('error_message') or ''}".rstrip()
                )
        lines.append("")
    lines.extend(
        [
            "## How To Read This",
            "",
            "- This comparison is an incrementality gate, not a prose-quality substitute.",
            "- A better run should normally improve pass rate, source absorption, heading coverage, or pattern-card traceability with explainable cost.",
            "- Scope changes matter: partial runs should be used to verify control behavior, while full runs are needed for final document quality.",
        ]
    )
    return "\n".join(lines).strip() + "\n"


def _compare_project(
    baseline: dict[str, Any] | None,
    candidate: dict[str, Any] | None,
    *,
    key: str,
) -> dict[str, Any]:
    baseline_metrics = _project_metrics(baseline)
    candidate_metrics = _project_metrics(candidate)
    delta = _metric_delta(baseline_metrics, candidate_metrics)
    notes = _project_notes(baseline_metrics, candidate_metrics, delta)
    return {
        "key": key,
        "baseline_present": baseline is not None,
        "candidate_present": candidate is not None,
        "baseline": baseline_metrics,
        "candidate": candidate_metrics,
        "delta": delta,
        "notes": notes,
    }


def _project_metrics(project: dict[str, Any] | None) -> dict[str, Any]:
    if not project:
        return {}
    task_count = _number(project.get("task_count"))
    passed_count = _number(project.get("passed_count"))
    failed = project.get("failed") or []
    trace_usage = project.get("trace_usage") or {}
    quality = project.get("quality_audit") or {}
    pattern_cards = project.get("pattern_card_usage") or {}
    return {
        "key": project.get("key"),
        "template_id": project.get("template_id"),
        "generation_scope": project.get("generation_scope") or "full",
        "selected_node_count": len(project.get("selected_node_ids") or []) if project.get("generation_scope") == "partial" else None,
        "run_status": project.get("run_status"),
        "task_count": task_count,
        "passed_count": passed_count,
        "failed_count": len(failed),
        "pass_rate": round(passed_count / task_count, 4) if task_count else None,
        "target_word_count_total": _number(project.get("target_word_count_total")),
        "actual_word_count_total": _number(project.get("actual_word_count_total")),
        "word_target_ratio": _ratio(project.get("actual_word_count_total"), project.get("target_word_count_total")),
        "source_section_count": _number(project.get("source_section_count")),
        "outline_node_count": _number(project.get("outline_node_count")),
        "word_count_estimate_count": _number(project.get("word_count_estimate_count")),
        "quality_issue_count": _number(quality.get("issue_count")),
        "quality_recommendation_count": _number(quality.get("recommendation_count")),
        "generated_vs_human_ratio": _maybe_float(quality.get("generated_vs_human_ratio")),
        "human_heading_coverage_ratio": _maybe_float(quality.get("human_heading_coverage_ratio")),
        "source_fact_absorption_ratio": _maybe_float(quality.get("source_fact_absorption_ratio")),
        "quality_recommended_actions": quality.get("recommended_actions") or [],
        "llm_call_count": _number(trace_usage.get("call_count")),
        "llm_error_count": _number(trace_usage.get("error_count")),
        "llm_elapsed_seconds": _maybe_float(trace_usage.get("elapsed_seconds_total")) or 0.0,
        "prompt_char_total": _number(trace_usage.get("prompt_char_total")),
        "response_char_total": _number(trace_usage.get("response_char_total")),
        "total_tokens": _number(trace_usage.get("total_tokens")),
        "estimated_total_tokens": _number(trace_usage.get("estimated_total_tokens")),
        "has_token_usage": bool(trace_usage.get("has_token_usage")),
        "chapter_count_with_pattern_audit": _number(pattern_cards.get("chapter_count")),
        "chapters_with_prompt_cards": _number(pattern_cards.get("chapters_with_prompt_cards")),
        "prompt_card_total": _number(pattern_cards.get("prompt_card_total")),
        "prompt_card_actionable_total": _number(pattern_cards.get("prompt_card_actionable_total")),
        "missing_prompt_card_count": _number(pattern_cards.get("missing_prompt_card_count")),
        "pattern_card_warning_count": _number(pattern_cards.get("warning_count")),
        "content_revision_target_count": _number(project.get("content_revision_target_count")),
        "generation_metadata_target_count": _number(project.get("generation_metadata_target_count")),
        "failed": failed,
    }


def _summary_delta(
    baseline: dict[str, Any],
    candidate: dict[str, Any],
    projects: list[dict[str, Any]],
) -> dict[str, Any]:
    delta: dict[str, Any] = {
        "project_count_delta": len(candidate.get("projects") or []) - len(baseline.get("projects") or []),
    }
    for key in [
        "task_count",
        "passed_count",
        "failed_count",
        "actual_word_count_total",
        "llm_call_count",
        "llm_error_count",
        "total_tokens",
        "estimated_total_tokens",
        "chapters_with_prompt_cards",
        "prompt_card_total",
        "prompt_card_actionable_total",
        "missing_prompt_card_count",
        "quality_issue_count",
        "quality_recommendation_count",
    ]:
        delta[f"{key}_delta"] = sum((item.get("delta") or {}).get(f"{key}_delta") or 0 for item in projects)
    baseline_tasks = sum(_number((item.get("baseline") or {}).get("task_count")) for item in projects)
    candidate_tasks = sum(_number((item.get("candidate") or {}).get("task_count")) for item in projects)
    baseline_passed = sum(_number((item.get("baseline") or {}).get("passed_count")) for item in projects)
    candidate_passed = sum(_number((item.get("candidate") or {}).get("passed_count")) for item in projects)
    baseline_pass_rate = round(baseline_passed / baseline_tasks, 4) if baseline_tasks else None
    candidate_pass_rate = round(candidate_passed / candidate_tasks, 4) if candidate_tasks else None
    delta["baseline_pass_rate"] = baseline_pass_rate
    delta["candidate_pass_rate"] = candidate_pass_rate
    delta["pass_rate_delta"] = _nullable_delta(baseline_pass_rate, candidate_pass_rate)
    trace_baseline = baseline.get("trace_usage_total") or {}
    trace_candidate = candidate.get("trace_usage_total") or {}
    delta["total_trace_call_count_delta"] = _number(trace_candidate.get("call_count")) - _number(trace_baseline.get("call_count"))
    delta["total_trace_token_delta"] = _number(trace_candidate.get("total_tokens")) - _number(trace_baseline.get("total_tokens"))
    return delta


def _metric_delta(baseline: dict[str, Any], candidate: dict[str, Any]) -> dict[str, Any]:
    delta: dict[str, Any] = {}
    numeric_keys = [
        "task_count",
        "passed_count",
        "failed_count",
        "target_word_count_total",
        "actual_word_count_total",
        "source_section_count",
        "outline_node_count",
        "word_count_estimate_count",
        "quality_issue_count",
        "quality_recommendation_count",
        "llm_call_count",
        "llm_error_count",
        "llm_elapsed_seconds",
        "prompt_char_total",
        "response_char_total",
        "total_tokens",
        "estimated_total_tokens",
        "chapter_count_with_pattern_audit",
        "chapters_with_prompt_cards",
        "prompt_card_total",
        "prompt_card_actionable_total",
        "missing_prompt_card_count",
        "pattern_card_warning_count",
        "content_revision_target_count",
        "generation_metadata_target_count",
    ]
    for key in numeric_keys:
        delta[f"{key}_delta"] = _numeric_delta(baseline.get(key), candidate.get(key))
    for key in [
        "pass_rate",
        "word_target_ratio",
        "generated_vs_human_ratio",
        "human_heading_coverage_ratio",
        "source_fact_absorption_ratio",
    ]:
        delta[f"{key}_delta"] = _nullable_delta(baseline.get(key), candidate.get(key))
    return delta


def _project_notes(
    baseline: dict[str, Any],
    candidate: dict[str, Any],
    delta: dict[str, Any],
) -> list[str]:
    notes: list[str] = []
    if not baseline:
        notes.append("Project exists only in candidate run.")
        return notes
    if not candidate:
        notes.append("Project exists only in baseline run.")
        return notes
    if baseline.get("generation_scope") != candidate.get("generation_scope"):
        notes.append("Generation scope changed; compare control-layer metrics carefully before judging prose quality.")
    if (delta.get("pass_rate_delta") or 0) > 0:
        notes.append("Pass rate improved.")
    elif (delta.get("pass_rate_delta") or 0) < 0:
        notes.append("Pass rate regressed; inspect failed tasks before broader regeneration.")
    if delta.get("missing_prompt_card_count_delta", 0) < 0:
        notes.append("Fewer chapters lack pattern-card traceability.")
    if delta.get("chapters_with_prompt_cards_delta", 0) > 0:
        notes.append("More generated chapters persisted prompt-card controls.")
    if (delta.get("source_fact_absorption_ratio_delta") or 0) > 0:
        notes.append("Source fact absorption improved.")
    elif (delta.get("source_fact_absorption_ratio_delta") or 0) < 0:
        notes.append("Source fact absorption regressed; strengthen source mapping or evidence-targeted revision.")
    if (delta.get("human_heading_coverage_ratio_delta") or 0) > 0:
        notes.append("Human-reference heading coverage improved.")
    elif (delta.get("human_heading_coverage_ratio_delta") or 0) < 0:
        notes.append("Heading coverage regressed; repair outline coverage or subsection expansion.")
    if delta.get("llm_error_count_delta", 0) > 0:
        notes.append("LLM trace errors increased.")
    if delta.get("total_tokens_delta", 0) > 0 and (delta.get("pass_rate_delta") or 0) <= 0:
        notes.append("Token use increased without pass-rate improvement; prefer partial targeted validation.")
    return notes


def _recommended_next_actions(projects: list[dict[str, Any]], delta: dict[str, Any]) -> list[str]:
    actions: list[str] = []
    if (delta.get("pass_rate_delta") or 0) < 0 or delta.get("failed_count_delta", 0) > 0:
        actions.append("Review candidate failed tasks and route each one to remap, evidence-targeted regenerate, or human-input request.")
    elif any(_number((item.get("candidate") or {}).get("failed_count")) > 0 for item in projects):
        actions.append("Candidate still has failed or needs-repair chapters; revise only those chapters instead of rerunning the whole document.")
    if delta.get("missing_prompt_card_count_delta", 0) > 0:
        actions.append("Fix generation metadata persistence so pattern_prompt_cards are written for every generated chapter.")
    if delta.get("chapters_with_prompt_cards_delta", 0) > 0 and delta.get("missing_prompt_card_count_delta", 0) < 0:
        actions.append("Keep the pattern-card control layer; use its missing requirements to drive chapter-level revisions.")
    if delta.get("total_tokens_delta", 0) > 0 and (delta.get("pass_rate_delta") or 0) <= 0:
        actions.append("Use --chapter-limit or --chapter-title-contains for the next validation run before another full regeneration.")
    for item in projects:
        candidate = item.get("candidate") or {}
        if candidate.get("quality_recommended_actions"):
            actions.append(
                f"{item.get('key')}: apply quality feedback actions "
                + ", ".join(candidate["quality_recommended_actions"][:4])
                + "."
            )
    return list(dict.fromkeys(actions))


def _comparison_verdict(projects: list[dict[str, Any]], delta: dict[str, Any]) -> str:
    if any(not item.get("candidate_present") for item in projects):
        return "candidate_missing_projects"
    if (delta.get("pass_rate_delta") or 0) < 0 or delta.get("failed_count_delta", 0) > 0:
        return "regressed"
    if delta.get("missing_prompt_card_count_delta", 0) < 0 and delta.get("chapters_with_prompt_cards_delta", 0) > 0:
        return "control_traceability_improved"
    quality_positive = any(
        ((item.get("delta") or {}).get("source_fact_absorption_ratio_delta") or 0) > 0
        or ((item.get("delta") or {}).get("human_heading_coverage_ratio_delta") or 0) > 0
        for item in projects
    )
    if (delta.get("pass_rate_delta") or 0) > 0 or quality_positive:
        return "improved"
    if any(_scope_changed(item) for item in projects):
        return "scope_changed_inconclusive"
    return "no_clear_change"


def _projects_by_key(summary: dict[str, Any]) -> dict[str, dict[str, Any]]:
    output: dict[str, dict[str, Any]] = {}
    for project in summary.get("projects") or []:
        if not isinstance(project, dict):
            continue
        key = str(project.get("key") or project.get("project_id") or "")
        if key:
            output[key] = project
    return output


def _scope_changed(item: dict[str, Any]) -> bool:
    return (item.get("baseline") or {}).get("generation_scope") != (item.get("candidate") or {}).get("generation_scope")


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


def _maybe_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _numeric_delta(baseline: Any, candidate: Any) -> int | float:
    before = _maybe_float(baseline)
    after = _maybe_float(candidate)
    if before is None:
        before = 0.0
    if after is None:
        after = 0.0
    delta = after - before
    if float(delta).is_integer():
        return int(delta)
    return round(delta, 4)


def _nullable_delta(baseline: Any, candidate: Any) -> float | None:
    before = _maybe_float(baseline)
    after = _maybe_float(candidate)
    if before is None or after is None:
        return None
    return round(after - before, 4)


def _ratio(numerator: Any, denominator: Any) -> float | None:
    value = _maybe_float(numerator)
    total = _maybe_float(denominator)
    if value is None or not total:
        return None
    return round(value / total, 4)


def _fmt_delta(value: Any) -> str:
    if value is None:
        return "-"
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value)
    prefix = "+" if number > 0 else ""
    if number.is_integer():
        return f"{prefix}{int(number)}"
    return f"{prefix}{number:.4f}".rstrip("0").rstrip(".")
