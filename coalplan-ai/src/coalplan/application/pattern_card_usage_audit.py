from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from coalplan.application.generation_metadata_audit import audit_version_generation_metadata
from coalplan.application.serialization import to_json_text


def audit_pattern_card_usage(artifact_root: Path) -> dict[str, Any]:
    """Audit whether persisted generated chapters carry and satisfy pattern prompt cards.

    This is intentionally filesystem based so it can inspect historical real-generation
    output folders without requiring the SQLite database to be open.
    """

    root = artifact_root.resolve()
    records = _collect_records(root)
    items: list[dict[str, Any]] = []
    for record in records:
        metadata = record["metadata"]
        markdown = record["markdown_path"].read_text(encoding="utf-8-sig")
        audit = audit_version_generation_metadata(
            {
                "id": record["version_id"] or record["node_id"],
                "markdown": markdown,
                "generation_metadata": metadata,
            }
        )
        metrics = audit.get("metrics") or {}
        issues = list(audit.get("issues") or [])
        generation_policy = metadata.get("generation_policy") if isinstance(metadata, dict) else None
        prompt_cards = []
        if isinstance(generation_policy, dict):
            prompt_cards = [card for card in generation_policy.get("pattern_prompt_cards") or [] if isinstance(card, dict)]
        if generation_policy and not prompt_cards:
            issues.append("Generation policy exists but pattern_prompt_cards were not persisted for this chapter.")
        if not generation_policy:
            issues.append("Generation metadata lacks generation_policy, so pattern-card traceability cannot be verified.")
        items.append(
            {
                "node_id": record["node_id"],
                "version_id": record["version_id"],
                "title": metadata.get("title") or record["node_id"],
                "metadata_path": str(record["metadata_path"]),
                "markdown_path": str(record["markdown_path"]),
                "selected_pattern_keys": metadata.get("selected_pattern_keys") or [],
                "prompt_card_count": metrics.get("prompt_card_count", 0),
                "prompt_card_actionable_count": metrics.get("prompt_card_actionable_count", 0),
                "actionable_count": metrics.get("actionable_count", 0),
                "audit_status": audit.get("status"),
                "issues": issues,
                "next_actions": audit.get("next_actions") or [],
                "prompt_card_audits": audit.get("prompt_card_audits") or [],
                "pattern_audits": audit.get("pattern_audits") or [],
            }
        )

    summary = _summary(root, items)
    return {
        "artifact_root": str(root),
        "summary": summary,
        "items": items,
    }


def write_pattern_card_usage_audit(report: dict[str, Any], output_dir: Path) -> dict[str, str]:
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "pattern_card_usage_audit.json"
    markdown_path = output_dir / "pattern_card_usage_audit.md"
    json_path.write_text(to_json_text(report), encoding="utf-8")
    markdown_path.write_text(render_pattern_card_usage_audit(report), encoding="utf-8")
    return {"json": str(json_path), "markdown": str(markdown_path)}


def load_pattern_card_usage_report(path: Path) -> dict[str, Any]:
    path = path.resolve()
    if path.is_dir():
        audit_path = path / "pattern_card_usage_audit.json"
        if audit_path.exists():
            path = audit_path
        else:
            return audit_pattern_card_usage(path)
    data = _read_json(path)
    if not isinstance(data, dict):
        raise ValueError(f"Pattern card usage report is not valid JSON: {path}")
    return data


def compare_pattern_card_usage_reports(
    baseline: dict[str, Any],
    candidate: dict[str, Any],
    *,
    baseline_label: str = "baseline",
    candidate_label: str = "candidate",
) -> dict[str, Any]:
    baseline_summary = baseline.get("summary") or {}
    candidate_summary = candidate.get("summary") or {}
    baseline_items = _items_by_key(baseline)
    candidate_items = _items_by_key(candidate)
    keys = sorted(set(baseline_items) | set(candidate_items))
    item_deltas: list[dict[str, Any]] = []
    for key in keys:
        before = baseline_items.get(key)
        after = candidate_items.get(key)
        item_deltas.append(
            {
                "key": key,
                "node_id": (after or before or {}).get("node_id"),
                "title": (after or before or {}).get("title"),
                "baseline_present": before is not None,
                "candidate_present": after is not None,
                "prompt_card_count_delta": _metric(after, "prompt_card_count") - _metric(before, "prompt_card_count"),
                "prompt_card_actionable_delta": _metric(after, "prompt_card_actionable_count")
                - _metric(before, "prompt_card_actionable_count"),
                "actionable_count_delta": _metric(after, "actionable_count") - _metric(before, "actionable_count"),
                "issue_count_delta": len((after or {}).get("issues") or []) - len((before or {}).get("issues") or []),
                "baseline_status": (before or {}).get("audit_status"),
                "candidate_status": (after or {}).get("audit_status"),
            }
        )
    summary_delta = {
        "chapter_count_delta": _summary_metric(candidate_summary, "chapter_count") - _summary_metric(baseline_summary, "chapter_count"),
        "chapters_with_prompt_cards_delta": _summary_metric(candidate_summary, "chapters_with_prompt_cards")
        - _summary_metric(baseline_summary, "chapters_with_prompt_cards"),
        "prompt_card_total_delta": _summary_metric(candidate_summary, "prompt_card_total")
        - _summary_metric(baseline_summary, "prompt_card_total"),
        "prompt_card_actionable_total_delta": _summary_metric(candidate_summary, "prompt_card_actionable_total")
        - _summary_metric(baseline_summary, "prompt_card_actionable_total"),
        "missing_prompt_card_count_delta": _summary_metric(candidate_summary, "missing_prompt_card_count")
        - _summary_metric(baseline_summary, "missing_prompt_card_count"),
        "warning_count_delta": _summary_metric(candidate_summary, "warning_count") - _summary_metric(baseline_summary, "warning_count"),
    }
    return {
        "baseline_label": baseline_label,
        "candidate_label": candidate_label,
        "baseline_artifact_root": baseline.get("artifact_root"),
        "candidate_artifact_root": candidate.get("artifact_root"),
        "baseline_summary": baseline_summary,
        "candidate_summary": candidate_summary,
        "summary_delta": summary_delta,
        "item_deltas": item_deltas,
        "verdict": _comparison_verdict(summary_delta),
    }


def write_pattern_card_usage_comparison(comparison: dict[str, Any], output_dir: Path) -> dict[str, str]:
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "pattern_card_usage_comparison.json"
    markdown_path = output_dir / "pattern_card_usage_comparison.md"
    json_path.write_text(to_json_text(comparison), encoding="utf-8")
    markdown_path.write_text(render_pattern_card_usage_comparison(comparison), encoding="utf-8")
    return {"json": str(json_path), "markdown": str(markdown_path)}


def render_pattern_card_usage_audit(report: dict[str, Any]) -> str:
    summary = report.get("summary") or {}
    lines = [
        "# Pattern Card Usage Audit",
        "",
        f"- artifact_root: `{report.get('artifact_root')}`",
        f"- chapter_count: {summary.get('chapter_count', 0)}",
        f"- chapters_with_prompt_cards: {summary.get('chapters_with_prompt_cards', 0)}",
        f"- prompt_card_total: {summary.get('prompt_card_total', 0)}",
        f"- prompt_card_actionable_total: {summary.get('prompt_card_actionable_total', 0)}",
        f"- missing_prompt_card_count: {summary.get('missing_prompt_card_count', 0)}",
        f"- warning_count: {summary.get('warning_count', 0)}",
        "",
        "| node | title | cards | card actions | status | issues |",
        "| --- | --- | ---: | ---: | --- | ---: |",
    ]
    for item in report.get("items") or []:
        lines.append(
            "| {node} | {title} | {cards} | {actions} | {status} | {issues} |".format(
                node=item.get("node_id") or "-",
                title=_cell(str(item.get("title") or "-")),
                cards=item.get("prompt_card_count", 0),
                actions=item.get("prompt_card_actionable_count", 0),
                status=item.get("audit_status") or "-",
                issues=len(item.get("issues") or []),
            )
        )
    lines.append("")
    for item in report.get("items") or []:
        issues = item.get("issues") or []
        actions = item.get("next_actions") or []
        if not issues and not actions:
            continue
        lines.extend([f"## {item.get('title') or item.get('node_id')}", ""])
        lines.append(f"- node_id: `{item.get('node_id')}`")
        if item.get("version_id"):
            lines.append(f"- version_id: `{item.get('version_id')}`")
        lines.append(f"- metadata: `{item.get('metadata_path')}`")
        lines.append(f"- markdown: `{item.get('markdown_path')}`")
        if issues:
            lines.append("- issues:")
            lines.extend(f"  - {issue}" for issue in issues[:12])
        if actions:
            lines.append("- next_actions:")
            lines.extend(f"  - {action}" for action in actions[:8])
        missing_requirements = _missing_card_requirements(item)
        if missing_requirements:
            lines.append("- missing_prompt_card_requirements:")
            lines.extend(f"  - {requirement}" for requirement in missing_requirements[:12])
        lines.append("")
    return "\n".join(lines).strip() + "\n"


def render_pattern_card_usage_comparison(comparison: dict[str, Any]) -> str:
    delta = comparison.get("summary_delta") or {}
    lines = [
        "# Pattern Card Usage Comparison",
        "",
        f"- baseline: `{comparison.get('baseline_label')}`",
        f"- candidate: `{comparison.get('candidate_label')}`",
        f"- verdict: `{comparison.get('verdict')}`",
        f"- chapters_with_prompt_cards_delta: {delta.get('chapters_with_prompt_cards_delta', 0)}",
        f"- prompt_card_total_delta: {delta.get('prompt_card_total_delta', 0)}",
        f"- prompt_card_actionable_total_delta: {delta.get('prompt_card_actionable_total_delta', 0)}",
        f"- missing_prompt_card_count_delta: {delta.get('missing_prompt_card_count_delta', 0)}",
        f"- warning_count_delta: {delta.get('warning_count_delta', 0)}",
        "",
        "| node/title | cards delta | card actions delta | actions delta | issues delta | status |",
        "| --- | ---: | ---: | ---: | ---: | --- |",
    ]
    for item in comparison.get("item_deltas") or []:
        lines.append(
            "| {title} | {cards} | {card_actions} | {actions} | {issues} | {status} |".format(
                title=_cell(str(item.get("title") or item.get("node_id") or item.get("key") or "-")),
                cards=item.get("prompt_card_count_delta", 0),
                card_actions=item.get("prompt_card_actionable_delta", 0),
                actions=item.get("actionable_count_delta", 0),
                issues=item.get("issue_count_delta", 0),
                status=f"{item.get('baseline_status') or '-'} -> {item.get('candidate_status') or '-'}",
            )
        )
    lines.extend(
        [
            "",
            "## Reading The Deltas",
            "",
            "- Positive `cards delta` means the candidate persisted more prompt cards than the baseline.",
            "- Negative `missing_prompt_card_count_delta` means fewer generated chapters lack prompt-card traceability.",
            "- Positive `card actions delta` is not automatically bad: it can mean the new audit is finally seeing card-specific gaps that were invisible before.",
            "- Improvements should be judged together with source evidence utilization and real prose quality after a DeepSeek/flash partial run.",
        ]
    )
    return "\n".join(lines).strip() + "\n"


def _collect_records(root: Path) -> list[dict[str, Any]]:
    by_node: dict[str, dict[str, Any]] = {}
    for metadata_path in sorted(root.rglob("*.generation_metadata.json")):
        metadata = _read_json(metadata_path)
        if not isinstance(metadata, dict):
            continue
        node_id = str(metadata.get("node_id") or _node_id_from_path(metadata_path))
        if not node_id:
            continue
        markdown_path = _find_markdown_for_metadata(metadata_path, node_id)
        if markdown_path is None:
            continue
        record = {
            "node_id": node_id,
            "version_id": _version_id_from_path(metadata_path),
            "metadata_path": metadata_path,
            "markdown_path": markdown_path,
            "metadata": metadata,
        }
        previous = by_node.get(node_id)
        if previous is None or _record_score(record) > _record_score(previous):
            by_node[node_id] = record
    return list(by_node.values())


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return None


def _find_markdown_for_metadata(metadata_path: Path, node_id: str) -> Path | None:
    same_base = metadata_path.with_name(metadata_path.name.replace(".generation_metadata.json", ".md"))
    if same_base.exists():
        return same_base
    for parent in [metadata_path.parent, *metadata_path.parents]:
        candidate = parent / f"{node_id}.md"
        if candidate.exists():
            return candidate
        chapters = parent / "chapters"
        candidate = chapters / f"{node_id}.md"
        if candidate.exists():
            return candidate
    return None


def _node_id_from_path(path: Path) -> str:
    name = path.name.replace(".generation_metadata.json", "")
    if name.startswith("tplnode_"):
        return name
    for part in reversed(path.parts):
        if part.startswith("tplnode_"):
            return part
    return ""


def _version_id_from_path(path: Path) -> str | None:
    name = path.name.replace(".generation_metadata.json", "")
    return name if name.startswith("ver_") else None


def _record_score(record: dict[str, Any]) -> int:
    metadata = record.get("metadata") or {}
    policy = metadata.get("generation_policy") if isinstance(metadata, dict) else None
    cards = policy.get("pattern_prompt_cards") if isinstance(policy, dict) else []
    score = 0
    if cards:
        score += 10
    if record.get("version_id"):
        score += 2
    return score


def _summary(root: Path, items: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "artifact_root_exists": root.exists(),
        "chapter_count": len(items),
        "chapters_with_prompt_cards": sum(1 for item in items if item.get("prompt_card_count", 0) > 0),
        "prompt_card_total": sum(int(item.get("prompt_card_count") or 0) for item in items),
        "prompt_card_actionable_total": sum(int(item.get("prompt_card_actionable_count") or 0) for item in items),
        "missing_prompt_card_count": sum(1 for item in items if item.get("prompt_card_count", 0) == 0),
        "warning_count": sum(1 for item in items if item.get("audit_status") != "passed" or item.get("issues")),
    }


def _missing_card_requirements(item: dict[str, Any]) -> list[str]:
    output: list[str] = []
    for audit in item.get("prompt_card_audits") or []:
        output.extend(str(value) for value in audit.get("missing_requirements") or [])
    return list(dict.fromkeys(output))


def _cell(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ")


def _items_by_key(report: dict[str, Any]) -> dict[str, dict[str, Any]]:
    output: dict[str, dict[str, Any]] = {}
    for item in report.get("items") or []:
        key = str(item.get("node_id") or item.get("title") or "")
        if key:
            output[key] = item
    return output


def _metric(item: dict[str, Any] | None, key: str) -> int:
    if not item:
        return 0
    try:
        return int(item.get(key) or 0)
    except (TypeError, ValueError):
        return 0


def _summary_metric(summary: dict[str, Any], key: str) -> int:
    try:
        return int(summary.get(key) or 0)
    except (TypeError, ValueError):
        return 0


def _comparison_verdict(delta: dict[str, int]) -> str:
    if delta.get("chapters_with_prompt_cards_delta", 0) > 0 and delta.get("missing_prompt_card_count_delta", 0) < 0:
        return "traceability_improved"
    if delta.get("prompt_card_total_delta", 0) > 0:
        return "prompt_cards_increased"
    if delta.get("missing_prompt_card_count_delta", 0) > 0:
        return "traceability_regressed"
    return "no_traceability_change"
