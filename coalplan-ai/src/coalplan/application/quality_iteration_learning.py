from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any, Literal

from pydantic import BaseModel, Field

from coalplan.application.writing_pattern_library import match_patterns_for_text


class PatternLearningSuggestion(BaseModel):
    pattern_key: str
    suggestion_type: Literal[
        "strengthen_required_source_facts",
        "add_revision_signal",
        "add_outline_guidance",
        "increase_detail_or_split",
    ]
    severity: Literal["info", "warning", "error"] = "warning"
    reason: str
    evidence: list[str] = Field(default_factory=list)
    suggested_text: list[str] = Field(default_factory=list)


class QualityIterationLearningReport(BaseModel):
    project_id: str
    status: Literal["passed", "warning"] = "passed"
    summary: str = ""
    metrics: dict[str, Any] = Field(default_factory=dict)
    suggestions: list[PatternLearningSuggestion] = Field(default_factory=list)


def build_quality_iteration_learning_report(
    *,
    project_id: str,
    quality_iteration: dict[str, Any],
    limit: int = 30,
) -> QualityIterationLearningReport:
    suggestions: list[PatternLearningSuggestion] = []
    pattern_counters: Counter[str] = Counter()
    omitted_by_pattern: dict[str, list[str]] = defaultdict(list)
    headings_by_pattern: dict[str, list[str]] = defaultdict(list)
    organization_gaps_by_pattern: dict[str, list[str]] = defaultdict(list)
    targets_by_pattern: dict[str, list[str]] = defaultdict(list)

    for audit in _iter_audits(quality_iteration):
        report = audit.get("report") or {}
        for fact in ((report.get("source_facts") or {}).get("omitted_examples") or [])[:40]:
            text = _fact_text(fact)
            if not text:
                continue
            key = _best_pattern_key(text)
            pattern_counters[key] += 1
            omitted_by_pattern[key].append(text)
        for heading in ((report.get("headings") or {}).get("missing_human_heading_examples") or [])[:40]:
            text = str(heading).strip()
            if not text:
                continue
            key = _best_pattern_key(text)
            pattern_counters[key] += 1
            headings_by_pattern[key].append(text)

    for target in _iter_targets(quality_iteration):
        text = " ".join(
            [
                str(target.get("title") or ""),
                str(target.get("reason") or ""),
                " ".join(str(item) for item in target.get("evidence") or []),
                str(target.get("source_status") or ""),
                " ".join(str(item) for item in target.get("source_section_ids") or []),
                " ".join(str(item) for item in target.get("evidence_ids") or []),
                " ".join(str(item) for item in target.get("next_steps") or []),
            ]
        )
        key = _best_pattern_key(text)
        pattern_counters[key] += 1
        evidence_targeted = _is_evidence_targeted_target(target)
        target_label = f"{target.get('target_type')}:{target.get('action')}:{target.get('title')}"
        if evidence_targeted:
            target_label = f"{target_label}:evidence_targeted"
            omitted_by_pattern[key].extend(_target_fact_snippets(target))
        targets_by_pattern[key].append(target_label)

    for target in _iter_generation_metadata_targets(quality_iteration):
        title = str(target.get("title") or "")
        action = str(target.get("action") or "")
        reason = str(target.get("reason") or "")
        next_actions = " ".join(str(item) for item in target.get("next_actions") or [])
        pattern_audits = [item for item in target.get("pattern_audits") or [] if isinstance(item, dict)]
        if not pattern_audits:
            key = _best_pattern_key(" ".join([title, action, reason, next_actions]))
            pattern_counters[key] += 1
            targets_by_pattern[key].append(f"generation_metadata:{action}:{title}")
            continue
        for audit in pattern_audits:
            key = str(audit.get("pattern_key") or "") or _best_pattern_key(" ".join([title, action, reason, next_actions]))
            suggested = str(audit.get("suggested_action") or action)
            missing_points = [str(item).strip() for item in audit.get("missing_points") or [] if str(item).strip()]
            pattern_counters[key] += 1
            targets_by_pattern[key].append(f"generation_metadata:{suggested}:{title}")
            organization_gaps_by_pattern[key].extend(missing_points[:8])

    for key, facts in omitted_by_pattern.items():
        if not facts:
            continue
        suggestions.append(
            PatternLearningSuggestion(
                pattern_key=key,
                suggestion_type="strengthen_required_source_facts",
                severity="warning",
                reason="Quality iterations repeatedly found source facts that were available but not absorbed into generated text.",
                evidence=_dedupe(facts)[:10],
                suggested_text=[
                    "Add these fact types or representative terms to `required_source_facts` or source-mapping requirements.",
                    "Ensure generation prompts require supported facts to be written into `## 生成正文` or explained as manual-fill.",
                ],
            )
        )
    for key, headings in headings_by_pattern.items():
        if not headings:
            continue
        suggestions.append(
            PatternLearningSuggestion(
                pattern_key=key,
                suggestion_type="add_outline_guidance",
                severity="warning",
                reason="Human-reference headings were missing from generated outline/content and should be considered as outline or subsection guidance.",
                evidence=_dedupe(headings)[:10],
                suggested_text=[
                    "Add recurring headings to `corpus_common_headings` after confirming they are reusable across projects.",
                    "Use them as proposal candidates only when the current source TOC or user supplements support them.",
                ],
            )
        )
    for key, gaps in organization_gaps_by_pattern.items():
        if not gaps:
            continue
        suggestions.append(
            PatternLearningSuggestion(
                pattern_key=key,
                suggestion_type="add_outline_guidance",
                severity="warning",
                reason="Generation metadata audits found missing reusable organization points from the local construction-plan writing pattern.",
                evidence=_dedupe(gaps)[:10],
                suggested_text=[
                    "Add recurring missing organization points to outline guidance or preferred structure after confirming they are reusable.",
                    "Use these points as writing-organization checks only; project facts still require mapped source evidence.",
                ],
            )
        )
    for key, target_labels in targets_by_pattern.items():
        if not target_labels:
            continue
        action_counts = Counter(label.split(":", 2)[1] for label in target_labels if ":" in label)
        if (
            action_counts.get("rewrite_subsection", 0)
            or action_counts.get("regenerate", 0)
            or action_counts.get("remap_sources", 0)
            or action_counts.get("review_source_link", 0)
            or action_counts.get("request_human_input", 0)
        ):
            suggestions.append(
                PatternLearningSuggestion(
                    pattern_key=key,
                    suggestion_type="add_revision_signal",
                    severity="warning",
                    reason="Quality and subsection-level revision targets repeatedly required remapping, rewriting, regeneration, or human input for this pattern.",
                    evidence=_dedupe(target_labels)[:10],
                    suggested_text=[
                        "Add revision signals for drafts that omit mapped evidence, have weak or missing subsection sources, remain generic, or require human-only parameters.",
                        "Treat evidence-targeted subsection rewrite as a source-fact absorption failure: the next retry must carry the omitted fact id, evidence id, section id, and fact text.",
                        "When subsection source links are weak or missing, remap before rewriting instead of expanding unsupported factual text.",
                    ],
                )
            )
        if (
            action_counts.get("propose_outline_repair", 0)
            or action_counts.get("repair_outline_coverage", 0)
            or action_counts.get("increase_detail_budget", 0)
            or action_counts.get("split_subsection", 0)
            or action_counts.get("expand_subsections", 0)
        ):
            suggestions.append(
                PatternLearningSuggestion(
                    pattern_key=key,
                    suggestion_type="increase_detail_or_split",
                    severity="info",
                    reason="Quality-audit targets indicated missing outline coverage or insufficient detail budget.",
                    evidence=_dedupe(target_labels)[:10],
                    suggested_text=[
                        "Prefer source-derived subsection proposals or larger target word budgets for this pattern when evidence density is high.",
                    ],
                )
            )

    suggestions = _dedupe_suggestions(suggestions)[:limit]
    metrics = {
        "round_count": quality_iteration.get("round_count"),
        "suggestion_count": len(suggestions),
        "content_revision_target_count": len([target for target in quality_iteration.get("content_revision_targets") or [] if isinstance(target, dict)]),
        "evidence_targeted_content_revision_target_count": len(
            [
                target
                for target in quality_iteration.get("content_revision_targets") or []
                if isinstance(target, dict) and _is_evidence_targeted_target(target)
            ]
        ),
        "generation_metadata_target_count": len([target for target in quality_iteration.get("generation_metadata_targets") or [] if isinstance(target, dict)]),
        "pattern_counts": dict(pattern_counters),
        "status": quality_iteration.get("status"),
    }
    return QualityIterationLearningReport(
        project_id=project_id,
        status="warning" if suggestions else "passed",
        summary=_summary(suggestions, metrics),
        metrics=metrics,
        suggestions=suggestions,
    )


def render_quality_iteration_learning_report(report: QualityIterationLearningReport) -> str:
    lines = [
        "# Quality Iteration Learning Report",
        "",
        f"- project_id: `{report.project_id}`",
        f"- status: `{report.status}`",
        f"- summary: {report.summary}",
        "",
        "## Metrics",
        "",
    ]
    for key, value in report.metrics.items():
        lines.append(f"- {key}: {value}")
    lines.extend(["", "## Suggestions", ""])
    if not report.suggestions:
        lines.append("- No pattern-library learning suggestion.")
        return "\n".join(lines).strip() + "\n"
    for item in report.suggestions:
        lines.extend(
            [
                f"### {item.pattern_key} / {item.suggestion_type}",
                f"- severity: {item.severity}",
                f"- reason: {item.reason}",
            ]
        )
        if item.evidence:
            lines.append("- evidence:")
            lines.extend(f"  - {entry}" for entry in item.evidence[:10])
        if item.suggested_text:
            lines.append("- suggested_text:")
            lines.extend(f"  - {entry}" for entry in item.suggested_text)
        lines.append("")
    return "\n".join(lines).strip() + "\n"


def _iter_audits(payload: dict[str, Any]):
    for round_item in payload.get("rounds") or []:
        audit = round_item.get("audit") or {}
        if audit:
            yield audit
    final = payload.get("final_audit") or {}
    if final:
        yield final


def _iter_targets(payload: dict[str, Any]):
    for target in payload.get("content_revision_targets") or []:
        if not isinstance(target, dict):
            continue
        enriched = dict(target)
        enriched.setdefault("target_type", "content_node")
        yield enriched
    for audit in _iter_audits(payload):
        targets = (audit.get("revision_targets") or {}).get("targets") or []
        for target in targets:
            yield target
    for round_item in payload.get("rounds") or []:
        execution = round_item.get("execution") or {}
        source_plan = execution.get("source_plan") or {}
        for target in source_plan.get("targets") or []:
            yield target


def _iter_generation_metadata_targets(payload: dict[str, Any]):
    for target in payload.get("generation_metadata_targets") or []:
        if isinstance(target, dict):
            yield target


def _fact_text(fact: Any) -> str:
    if isinstance(fact, dict):
        return " ".join(str(fact.get(key) or "") for key in ("fact", "kind", "context")).strip()
    return str(fact or "").strip()


def _is_evidence_targeted_target(target: dict[str, Any]) -> bool:
    if target.get("evidence_targeted"):
        return True
    text = " ".join(
        [
            str(target.get("reason") or ""),
            " ".join(str(item) for item in target.get("next_steps") or []),
        ]
    )
    return "omitted_required_source_facts" in text or "evidence-targeted" in text


def _target_fact_snippets(target: dict[str, Any]) -> list[str]:
    snippets: list[str] = []
    for item in target.get("next_steps") or []:
        text = str(item).strip()
        if not text:
            continue
        if "omitted required source fact" in text or "omitted_required_source_facts" in text or "fact_id" in text:
            snippets.append(text)
    reason = str(target.get("reason") or "").strip()
    if reason:
        snippets.append(reason)
    for item in target.get("evidence") or []:
        if str(item).strip():
            snippets.append(str(item).strip())
    return _dedupe(snippets)


def _best_pattern_key(text: str) -> str:
    matches = match_patterns_for_text(text, limit=1)
    if matches:
        return matches[0].pattern_key
    return "general"


def _dedupe(items: list[str]) -> list[str]:
    output: list[str] = []
    seen: set[str] = set()
    for item in items:
        value = str(item).strip()
        if not value or value in seen:
            continue
        seen.add(value)
        output.append(value)
    return output


def _dedupe_suggestions(items: list[PatternLearningSuggestion]) -> list[PatternLearningSuggestion]:
    seen: set[tuple[str, str]] = set()
    output: list[PatternLearningSuggestion] = []
    for item in items:
        key = (item.pattern_key, item.suggestion_type)
        if key in seen:
            continue
        seen.add(key)
        output.append(item)
    return output


def _summary(suggestions: list[PatternLearningSuggestion], metrics: dict[str, Any]) -> str:
    if not suggestions:
        return "No reusable writing-pattern learning suggestion was found from this quality iteration."
    return f"{len(suggestions)} suggestion(s) from {metrics.get('round_count') or 0} quality iteration round(s)."
