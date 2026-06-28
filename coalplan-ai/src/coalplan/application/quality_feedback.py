from __future__ import annotations

import re
from typing import Any

from coalplan.domain.documents import stable_id
from coalplan.domain.generation_control import (
    ChapterGenerationPolicy,
    ChapterPolicyAdjustment,
    GenerationControlPlan,
    QualityFeedbackAction,
    QualityFeedbackPlan,
    RevisionTrigger,
)

from .trace_revision_context import (
    build_trace_revision_context,
    build_trace_revision_context_from_labels,
    parse_trace_fact_label,
    render_trace_generation_context,
    render_trace_mapping_context,
    strip_trace_fact_label,
)


def build_quality_feedback_plan(
    report: dict[str, Any],
    *,
    current_plan: GenerationControlPlan | None = None,
    trace_diagnostics: dict[str, Any] | None = None,
) -> QualityFeedbackPlan:
    """Convert a final quality audit report into reusable next-run controls."""

    actions: list[QualityFeedbackAction] = []
    triggers: list[RevisionTrigger] = []
    recommendation_keys = {item.get("action") for item in report.get("recommendations", [])}

    if "increase_detail_budget" in recommendation_keys or _word_ratio(report) is not None and _word_ratio(report) < 0.35:
        action = _detail_budget_action(report, current_plan)
        actions.append(action)
        if action.policy_adjustments:
            triggers.append(
                RevisionTrigger(
                    node_id="all_chapters",
                    title="detail budget",
                    action="regenerate",
                    severity=action.severity,
                    reason=action.reason,
                    evidence=[item.node_id for item in action.policy_adjustments[:12]],
                )
            )

    if "repair_outline_coverage" in recommendation_keys or _heading_ratio(report) is not None and _heading_ratio(report) < 0.35:
        action = _outline_action(report)
        actions.append(action)
        triggers.append(
            RevisionTrigger(
                node_id="outline",
                title="outline coverage",
                action="expand_subsections",
                severity=action.severity,
                reason=action.reason,
                evidence=action.missing_heading_examples[:12],
            )
        )
    if _organization_ratio(report) is not None and _organization_ratio(report) < 0.5:
        action = _organization_action(report)
        actions.append(action)
        triggers.append(
            RevisionTrigger(
                node_id="outline",
                title="organization pattern coverage",
                action="expand_subsections",
                severity=action.severity,
                reason=action.reason,
                evidence=action.missing_heading_examples[:12],
            )
        )

    if "strengthen_evidence_utilization" in recommendation_keys or _fact_ratio(report) is not None and _fact_ratio(report) < 0.25:
        action = _evidence_action(report, current_plan)
        actions.append(action)
        triggers.append(
            RevisionTrigger(
                node_id="evidence",
                title="evidence utilization",
                action="regenerate",
                severity=action.severity,
                reason=action.reason,
                evidence=action.omitted_source_facts[:12],
            )
        )
    if trace_diagnostics:
        trace_action = _trace_evidence_action(trace_diagnostics, current_plan)
        if trace_action is not None:
            actions.append(trace_action)
        triggers.extend(_trace_revision_triggers(trace_diagnostics))

    missing_topics = _missing_common_topics(report)
    if "add_missing_common_topics" in recommendation_keys or len(missing_topics) >= 3:
        action = _missing_topics_action(report, missing_topics)
        actions.append(action)
        triggers.append(
            RevisionTrigger(
                node_id="outline",
                title="common topics",
                action="expand_subsections",
                severity=action.severity,
                reason=action.reason,
                evidence=missing_topics,
            )
        )

    return QualityFeedbackPlan(
        project_key=report.get("project_key"),
        actions=_dedupe_actions(actions),
        revision_triggers=_dedupe_triggers(triggers),
    )


def apply_quality_feedback_to_generation_plan(
    current_plan: GenerationControlPlan,
    feedback_plan: QualityFeedbackPlan,
) -> GenerationControlPlan:
    """Return a next-run control plan with feedback adjustments applied."""

    adjustments = _merge_policy_adjustments(
        adjustment
        for action in feedback_plan.actions
        for adjustment in action.policy_adjustments
    )
    next_policies: list[ChapterGenerationPolicy] = []
    for policy in current_plan.chapter_policies:
        adjustment = adjustments.get(policy.node_id)
        if adjustment is None:
            next_policies.append(policy)
            continue
        next_policies.append(
            _copy_model(
                policy,
                target_word_count=adjustment.next_target_word_count,
                detail_level=adjustment.next_detail_level or policy.detail_level,
                max_source_matches=adjustment.next_max_source_matches or policy.max_source_matches,
                max_evidence_spans=adjustment.next_max_evidence_spans or policy.max_evidence_spans,
                split_required=policy.split_required or bool(adjustment.split_required),
                reason=_append_reason(policy.reason, adjustment.reason),
            )
        )
    return _copy_model(
        current_plan,
        chapter_policies=next_policies,
        revision_triggers=_dedupe_triggers([*current_plan.revision_triggers, *feedback_plan.revision_triggers]),
    )


def render_quality_feedback_plan(plan: QualityFeedbackPlan) -> str:
    lines = [f"# Quality Feedback Plan: {plan.project_key or '-'}", ""]
    if not plan.actions:
        lines.append("- No feedback actions.")
        return "\n".join(lines).strip() + "\n"
    for action in plan.actions:
        lines.extend(
            [
                f"## {action.action}",
                f"- target: {action.target}",
                f"- severity: {action.severity}",
                f"- reason: {action.reason}",
            ]
        )
        if action.source_metrics:
            metrics = ", ".join(f"{key}={value}" for key, value in action.source_metrics.items())
            lines.append(f"- metrics: {metrics}")
        if action.missing_heading_examples:
            lines.append("- missing headings:")
            lines.extend(f"  - {item}" for item in action.missing_heading_examples[:10])
        if action.omitted_source_facts:
            lines.append("- omitted source facts:")
            lines.extend(f"  - {item}" for item in action.omitted_source_facts[:10])
        if action.missing_common_topics:
            lines.append("- missing common topics: " + ", ".join(action.missing_common_topics))
        if action.policy_adjustments:
            lines.append("- policy adjustments:")
            for adjustment in action.policy_adjustments[:20]:
                lines.append(
                    "  - "
                    f"{adjustment.node_id}: target {adjustment.current_target_word_count or '-'}"
                    f" -> {adjustment.next_target_word_count or '-'}, "
                    f"detail {adjustment.current_detail_level or '-'} -> {adjustment.next_detail_level or '-'}"
                )
        if action.next_steps:
            lines.append("- next steps:")
            lines.extend(f"  - {step}" for step in action.next_steps)
        lines.append("")
    if plan.revision_triggers:
        lines.append("## Revision Triggers")
        for trigger in plan.revision_triggers:
            lines.append(f"- [{trigger.severity}] {trigger.title}: {trigger.action}; {trigger.reason}")
    return "\n".join(lines).strip() + "\n"


def render_quality_feedback_prompt_context(
    plan: QualityFeedbackPlan | None,
    *,
    max_items: int = 12,
) -> str:
    """Render audit feedback as bounded prompt context for the next generation call."""

    if plan is None or not plan.actions:
        return ""
    lines = [
        "## Quality Audit Feedback Requirements",
        "- These requirements come from comparing the generated result with source documents and human references.",
        "- Treat headings and facts as audit hints; verify them against mapped source sections before writing factual text.",
        "- If a hinted fact is unsupported or outside the current chapter scope, keep it as a manual-fill placeholder instead of inventing details.",
    ]
    heading_hints = _collect_missing_headings(plan, limit=max_items)
    if heading_hints:
        lines.extend(["", "### Missing Heading Coverage Hints"])
        lines.extend(f"- {item}" for item in heading_hints)
    fact_hints = _collect_omitted_facts(plan, limit=max_items)
    if fact_hints:
        lines.extend(["", "### Omitted Source Fact Hints"])
        lines.extend(f"- {item}" for item in fact_hints)
    trace_hints = _collect_trace_fact_hints(plan, limit=max_items)
    if trace_hints:
        context = build_trace_revision_context_from_labels(trace_hints, project_key=plan.project_key, max_items=max_items)
        rendered = render_trace_generation_context(context, max_items=max_items)
        if rendered:
            lines.extend(["", rendered])
        else:
            lines.extend(["", "### Trace Evidence Diagnostics"])
            lines.extend(f"- {item}" for item in trace_hints)
    topic_hints = _collect_missing_topics(plan, limit=max_items)
    if topic_hints:
        lines.extend(["", "### Missing Common Topic Hints"])
        lines.extend(f"- {item}" for item in topic_hints)
    return "\n".join(lines).strip()


def render_quality_feedback_mapping_context(
    plan: QualityFeedbackPlan | None,
    *,
    max_items: int = 12,
) -> str:
    """Render audit feedback as source-mapping requirements for the next run."""

    if plan is None or not plan.actions:
        return ""
    not_prompted = _collect_trace_facts_by_status(plan, status="not_prompted", limit=max_items)
    prompted_but_omitted = _collect_trace_facts_by_status(plan, status="prompted_but_omitted", limit=max_items)
    omitted_facts = _collect_omitted_facts(plan, limit=max_items)
    if not not_prompted and not prompted_but_omitted and not omitted_facts:
        return ""
    lines = [
        "## Quality Feedback Mapping Requirements",
        "- These requirements come from post-generation quality audit and LLM trace diagnostics.",
        "- Use these facts only to select or expand source sections; do not write factual text during mapping.",
        "- For facts that cannot be supported by any source section, return them in missing_evidence.",
    ]
    if not_prompted:
        context = build_trace_revision_context_from_labels(
            not_prompted,
            project_key=plan.project_key,
            max_items=max_items,
        )
        rendered = render_trace_mapping_context(context, max_items=max_items)
        if rendered:
            lines.extend(["", rendered])
        else:
            lines.extend(["", "### Facts Not Reaching Previous Prompts"])
            lines.extend(f"- {item}" for item in not_prompted)
    if prompted_but_omitted:
        lines.extend(["", "### Facts Previously Prompted But Omitted"])
        lines.extend(f"- {item}" for item in prompted_but_omitted)
    if omitted_facts:
        lines.extend(["", "### Omitted Source Fact Search Hints"])
        lines.extend(f"- {item}" for item in omitted_facts)
    return "\n".join(lines).strip()


def quality_feedback_required_fact_hints(
    plan: QualityFeedbackPlan | None,
    *,
    source_text: str = "",
    max_items: int = 12,
) -> list[str]:
    """Return source-fact hints that the next chapter generation should carry over."""

    if plan is None or not plan.actions:
        return []
    hints: list[str] = []
    for action in plan.actions:
        if action.action != "strengthen_evidence_utilization":
            continue
        trace_labels = [str(item) for item in action.omitted_source_facts if _is_trace_label(str(item))]
        if trace_labels:
            trace_context = build_trace_revision_context_from_labels(
                trace_labels,
                project_key=plan.project_key,
                source_text=source_text,
                max_items=max_items,
            )
            for fact in trace_context.required_generation_facts:
                if fact.fact not in hints:
                    hints.append(fact.fact)
                if len(hints) >= max_items:
                    return hints
        for fact in action.omitted_source_facts:
            if _is_trace_label(str(fact)):
                continue
            cleaned = strip_trace_fact_label(str(fact))
            if not cleaned:
                continue
            if source_text and not _fact_hint_supported_by_source(cleaned, source_text):
                continue
            if cleaned not in hints:
                hints.append(cleaned)
            if len(hints) >= max_items:
                return hints
    return hints


def render_quality_feedback_required_facts_context(facts: list[str]) -> str:
    if not facts:
        return "无。"
    return "\n".join(f"- {fact}" for fact in facts)


def build_quality_outline_repair_proposal_nodes(
    *,
    feedback_plan: QualityFeedbackPlan,
    existing_node_ids: set[str] | None = None,
    existing_titles: set[str] | None = None,
    start_sort_order: int = 1000,
    limit: int = 12,
) -> list[dict]:
    """Create editable outline proposal nodes from human-reference heading gaps."""

    existing_node_ids = existing_node_ids or set()
    existing_title_keys = {_title_key(title) for title in (existing_titles or set())}
    nodes: list[dict] = []
    order = start_sort_order
    for heading in _collect_missing_headings(feedback_plan, limit=limit * 2):
        title = _clean_heading_candidate(heading)
        if not title:
            continue
        title_key = _title_key(title)
        if title_key in existing_title_keys:
            continue
        node_id = stable_id("qfbnode", title)
        if node_id in existing_node_ids:
            continue
        nodes.append(
            {
                "__action": "create",
                "node_id": node_id,
                "parent_id": None,
                "title": title,
                "level": 1,
                "sort_order": order,
                "enabled": True,
                "source_rules": [
                    "Quality audit found this heading in a human-written reference but not in the generated outline.",
                    "Before factual generation, run source mapping and use only source-supported content.",
                ],
                "auto_fill": [
                    "Summarize source-supported scope, methods, controls, and management requirements for this heading.",
                    "Use the project profile and mapped bid-document sections to organize prose.",
                ],
                "manual_fill": [
                    "【需人工补充：确认该参考标题是否适用于当前项目，并补充图纸、审批、现场或合同中未在投标文档明确的信息。】",
                ],
                "special_notes": [
                    "Created from quality audit feedback; apply only after user confirmation.",
                ],
                "target_word_count": _quality_heading_target(title),
            }
        )
        existing_title_keys.add(title_key)
        order += 10
        if len(nodes) >= limit:
            break
    return nodes


def _detail_budget_action(
    report: dict[str, Any],
    current_plan: GenerationControlPlan | None,
) -> QualityFeedbackAction:
    ratio = _word_ratio(report)
    multiplier = _detail_multiplier(ratio)
    adjustments = [
        _detail_adjustment(policy, multiplier, ratio)
        for policy in (current_plan.chapter_policies if current_plan else [])
    ]
    return QualityFeedbackAction(
        action="increase_detail_budget",
        target="detail_budget",
        severity="warning",
        reason=f"Generated document is too short for the reference; increase detail budgets by about {multiplier:.2f}x.",
        source_metrics={"generated_vs_human_ratio": ratio},
        next_steps=[
            "Recompute target_word_count before regeneration.",
            "Prefer splitting dense craft chapters instead of asking one prompt for a long answer.",
            "Keep missing parameters as manual-fill placeholders.",
        ],
        policy_adjustments=adjustments,
    )


def _outline_action(report: dict[str, Any]) -> QualityFeedbackAction:
    headings = report.get("headings") or {}
    examples = [str(item) for item in headings.get("missing_human_heading_examples") or []]
    return QualityFeedbackAction(
        action="repair_outline_coverage",
        target="outline",
        severity="warning",
        reason="Generated heading tree covers too few human-reference headings; run outline repair before regeneration.",
        source_metrics={
            "human_heading_coverage_ratio": headings.get("human_heading_coverage_ratio"),
            "generated_count": headings.get("generated_count"),
            "human_count": headings.get("human_count"),
        },
        missing_heading_examples=examples[:30],
        next_steps=[
            "Create editable outline proposals for missing high-value headings.",
            "Use source-derived subsection proposals for dense craft chapters.",
            "Disable unsupported template-only nodes or route them to human input.",
        ],
    )


def _organization_action(report: dict[str, Any]) -> QualityFeedbackAction:
    organization = report.get("organization_patterns") or {}
    audits = [item for item in organization.get("audits", []) if item.get("applicable")]
    missing_points: list[str] = []
    for item in audits:
        pattern = item.get("pattern_key") or "-"
        for point in item.get("missing_points") or []:
            missing_points.append(f"{pattern}: {point}")
    return QualityFeedbackAction(
        action="repair_outline_coverage",
        target="outline",
        severity="warning",
        reason=(
            "Generated text does not yet follow the reusable construction-plan organization patterns "
            f"learned from the local corpus; average coverage={organization.get('average_coverage_ratio')}."
        ),
        source_metrics={
            "organization_average_coverage_ratio": organization.get("average_coverage_ratio"),
            "applicable_pattern_count": organization.get("applicable_pattern_count"),
        },
        missing_heading_examples=missing_points[:30],
        next_steps=[
            "Use pattern cards to add missing expected points to editable outline nodes or subchapters.",
            "For craft chapters, split source-backed subtopics before regeneration.",
            "Regenerate chapters whose evidence exists but whose expected organization points are missing.",
            "Do not copy human reference wording; only reuse the organization shape and point coverage.",
        ],
    )


def _evidence_action(
    report: dict[str, Any],
    current_plan: GenerationControlPlan | None,
) -> QualityFeedbackAction:
    source_facts = report.get("source_facts") or {}
    omitted_examples = [
        str(item.get("fact") or item)
        for item in (source_facts.get("omitted_examples") or [])
    ]
    adjustments = [
        _evidence_adjustment(policy)
        for policy in (current_plan.chapter_policies if current_plan else [])
    ]
    return QualityFeedbackAction(
        action="strengthen_evidence_utilization",
        target="evidence",
        severity="warning",
        reason="Mapped source evidence is not sufficiently absorbed by generated text; require fact-level carryover.",
        source_metrics={
            "candidate_count": source_facts.get("candidate_count"),
            "absorbed_count": source_facts.get("absorbed_count"),
            "omitted_count": source_facts.get("omitted_count"),
            "absorption_ratio": source_facts.get("absorption_ratio"),
        },
        omitted_source_facts=omitted_examples[:30],
        next_steps=[
            "Extract high-value quantities, parameters, standards, and dates into required_source_facts.",
            "Add omitted required facts to revision context for regeneration.",
            "Fail or regenerate chapters that omit required facts without a missing-source reason.",
        ],
        policy_adjustments=adjustments,
    )


def _missing_topics_action(report: dict[str, Any], missing_topics: list[str]) -> QualityFeedbackAction:
    return QualityFeedbackAction(
        action="add_missing_common_topics",
        target="common_topics",
        severity="warning",
        reason="Several common construction-organization topic groups are missing from generated text.",
        source_metrics={"missing_topic_count": len(missing_topics)},
        missing_common_topics=missing_topics,
        next_steps=[
            "Create outline proposals for missing common-topic groups.",
            "Generate only when source mapping or human supplements support the topic.",
        ],
    )


def _trace_evidence_action(
    trace_diagnostics: dict[str, Any],
    current_plan: GenerationControlPlan | None,
) -> QualityFeedbackAction | None:
    context = build_trace_revision_context(trace_diagnostics, max_items=30)
    buckets = trace_diagnostics.get("buckets") or {}
    not_prompted = int(buckets.get("not_prompted") or len(context.remap_facts))
    prompted_but_omitted = int(buckets.get("prompted_but_omitted") or len(context.required_generation_facts))
    if not_prompted == 0 and prompted_but_omitted == 0:
        return None
    adjustments = [_evidence_adjustment(policy) for policy in (current_plan.chapter_policies if current_plan else [])]
    omitted = [fact.label for fact in [*context.remap_facts, *context.required_generation_facts]][:30]
    return QualityFeedbackAction(
        action="strengthen_evidence_utilization",
        target="traceability",
        severity="warning",
        reason=(
            "Trace diagnostics found omitted facts that were either never prompted "
            f"({not_prompted}) or prompted but not written ({prompted_but_omitted})."
        ),
        source_metrics={
            "trace_count": trace_diagnostics.get("trace_count"),
            "not_prompted": not_prompted,
            "prompted_but_omitted": prompted_but_omitted,
        },
        omitted_source_facts=omitted,
        next_steps=[
            "For not_prompted facts, remap sources using the fact text as mapping hints.",
            "For prompted_but_omitted facts, regenerate with these facts in required_source_facts.",
            "Do not accept a retry that silently drops the same fact again.",
        ],
        policy_adjustments=adjustments,
    )


def _trace_revision_triggers(trace_diagnostics: dict[str, Any]) -> list[RevisionTrigger]:
    triggers: list[RevisionTrigger] = []
    context = build_trace_revision_context(trace_diagnostics, max_items=12)
    not_prompted = [fact.label for fact in context.remap_facts]
    if not_prompted:
        triggers.append(
            RevisionTrigger(
                node_id="evidence",
                title="trace evidence mapping",
                action="remap_sources",
                severity="warning",
                reason="Trace diagnostics found omitted source facts that never reached LLM prompts.",
                evidence=not_prompted,
            )
        )
    prompted_but_omitted = [fact.label for fact in context.required_generation_facts if fact.status == "prompted_but_omitted"]
    if prompted_but_omitted:
        triggers.append(
            RevisionTrigger(
                node_id="evidence",
                title="trace evidence regeneration",
                action="regenerate",
                severity="warning",
                reason="Trace diagnostics found source facts that reached prompts but were omitted from responses.",
                evidence=prompted_but_omitted,
            )
        )
    return triggers


def _detail_adjustment(
    policy: ChapterGenerationPolicy,
    multiplier: float,
    ratio: float | None,
) -> ChapterPolicyAdjustment:
    current = policy.target_word_count or _default_target(policy)
    next_target = _round_target(current * multiplier)
    next_detail = policy.detail_level
    split_required = policy.split_required
    if policy.detail_level == "brief":
        next_detail = "normal"
    elif policy.detail_level == "normal" and (ratio is None or ratio < 0.25):
        next_detail = "deep"
    if policy.split_required or policy.source_subtopics or policy.detail_level == "subsection_required":
        next_detail = "subsection_required"
        split_required = True
    return ChapterPolicyAdjustment(
        node_id=policy.node_id,
        title=policy.title,
        current_target_word_count=policy.target_word_count,
        next_target_word_count=next_target,
        current_detail_level=policy.detail_level,
        next_detail_level=next_detail,
        next_max_source_matches=max(policy.max_source_matches, 10),
        next_max_evidence_spans=max(policy.max_evidence_spans, 18),
        split_required=split_required,
        reason="Post-generation audit reported low generated/reference word ratio.",
    )


def _evidence_adjustment(policy: ChapterGenerationPolicy) -> ChapterPolicyAdjustment:
    return ChapterPolicyAdjustment(
        node_id=policy.node_id,
        title=policy.title,
        current_target_word_count=policy.target_word_count,
        next_target_word_count=policy.target_word_count,
        current_detail_level=policy.detail_level,
        next_detail_level=policy.detail_level,
        next_max_source_matches=max(policy.max_source_matches, 12),
        next_max_evidence_spans=max(policy.max_evidence_spans, 24),
        split_required=policy.split_required,
        reason="Post-generation audit reported low high-value source fact absorption.",
    )


def _word_ratio(report: dict[str, Any]) -> float | None:
    return _float_or_none((report.get("word_counts") or {}).get("generated_vs_human_ratio"))


def _heading_ratio(report: dict[str, Any]) -> float | None:
    return _float_or_none((report.get("headings") or {}).get("human_heading_coverage_ratio"))


def _fact_ratio(report: dict[str, Any]) -> float | None:
    return _float_or_none((report.get("source_facts") or {}).get("absorption_ratio"))


def _organization_ratio(report: dict[str, Any]) -> float | None:
    return _float_or_none((report.get("organization_patterns") or {}).get("average_coverage_ratio"))


def _float_or_none(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _detail_multiplier(ratio: float | None) -> float:
    if ratio is None:
        return 1.35
    if ratio < 0.15:
        return 2.0
    if ratio < 0.25:
        return 1.6
    return 1.35


def _default_target(policy: ChapterGenerationPolicy) -> int:
    if policy.detail_level == "subsection_required" or policy.split_required:
        return 1800
    if policy.detail_level == "deep":
        return 1500
    if policy.detail_level == "brief":
        return 600
    return 1000


def _round_target(value: float) -> int:
    return int(round(value / 50) * 50)


def _missing_common_topics(report: dict[str, Any]) -> list[str]:
    topics = report.get("common_topics") or {}
    return [key for key, item in topics.items() if not (item or {}).get("covered")]


def _collect_missing_headings(plan: QualityFeedbackPlan, *, limit: int) -> list[str]:
    output: list[str] = []
    for action in plan.actions:
        if action.action != "repair_outline_coverage":
            continue
        for heading in action.missing_heading_examples:
            cleaned = _clean_heading_candidate(heading)
            if cleaned and cleaned not in output:
                output.append(cleaned)
            if len(output) >= limit:
                return output
    return output


def _collect_omitted_facts(plan: QualityFeedbackPlan, *, limit: int) -> list[str]:
    output: list[str] = []
    for action in plan.actions:
        if action.action != "strengthen_evidence_utilization":
            continue
        if action.target == "traceability":
            continue
        for fact in action.omitted_source_facts:
            cleaned = str(fact).strip()
            if cleaned and cleaned not in output:
                output.append(cleaned)
            if len(output) >= limit:
                return output
    return output


def _collect_missing_topics(plan: QualityFeedbackPlan, *, limit: int) -> list[str]:
    output: list[str] = []
    for action in plan.actions:
        if action.action != "add_missing_common_topics":
            continue
        for topic in action.missing_common_topics:
            cleaned = str(topic).strip()
            if cleaned and cleaned not in output:
                output.append(cleaned)
            if len(output) >= limit:
                return output
    return output


def _collect_trace_fact_hints(plan: QualityFeedbackPlan, *, limit: int) -> list[str]:
    output: list[str] = []
    for action in plan.actions:
        if action.target != "traceability":
            continue
        for fact in action.omitted_source_facts:
            cleaned = str(fact).strip()
            if cleaned and cleaned not in output:
                output.append(cleaned)
            if len(output) >= limit:
                return output
    return output


def _collect_trace_facts_by_status(plan: QualityFeedbackPlan, *, status: str, limit: int) -> list[str]:
    output: list[str] = []
    marker = f"[{status} ->"
    for action in plan.actions:
        if action.target != "traceability":
            continue
        for fact in action.omitted_source_facts:
            cleaned = str(fact).strip()
            if marker not in cleaned:
                continue
            if cleaned and cleaned not in output:
                output.append(cleaned)
            if len(output) >= limit:
                return output
    return output


def _is_trace_label(value: str) -> bool:
    return parse_trace_fact_label(value) is not None


def _strip_trace_label(value: str) -> str:
    return re.sub(r"\s*\[(?:not_prompted|prompted_but_omitted|absorbed_in_response)\s*->\s*[^]]+\]\s*$", "", value).strip()


def _fact_hint_supported_by_source(fact: str, source_text: str) -> bool:
    normalized_source = _normalize_fact_match_text(source_text)
    tokens = _fact_hint_tokens(fact)
    if not tokens:
        return _normalize_fact_match_text(fact) in normalized_source
    numeric_tokens = [token for token in tokens if any(char.isdigit() for char in token)]
    if numeric_tokens:
        return any(_normalize_fact_match_text(token) in normalized_source for token in numeric_tokens)
    return sum(1 for token in tokens if _normalize_fact_match_text(token) in normalized_source) >= min(2, len(tokens))


def _fact_hint_tokens(text: str) -> list[str]:
    tokens: list[str] = []
    for token in re.findall(r"(?:GB|GB/T|DL/T|JGJ|SL|DZ/T|HJ|NB/T|TB|JTJ|JTG)\s*[-A-Z0-9./]+", text, flags=re.I):
        if token not in tokens:
            tokens.append(token)
    for token in re.findall(
        r"\d+(?:\.\d+)?(?:\s*(?:-|~|～|—|至)\s*\d+(?:\.\d+)?)?\s*(?:万)?\s*"
        r"(?:m³/min|m3/min|m3|m³|m2|m²|mm|cm|km|m|t|kg|MPa|kPa|kN|kW|MW|%|℃|°|"
        r"天|日|月|年|根|孔|台|套|人|班|次|处|座|条|项|分钟|小时|"
        r"米|毫米|厘米|千米|吨|立方米|平方米|公顷)",
        text,
        flags=re.I,
    ):
        if token not in tokens:
            tokens.append(token)
    if tokens:
        return tokens[:8]
    for token in re.findall(r"[\u4e00-\u9fff]{2,12}", text):
        if token not in tokens:
            tokens.append(token)
    return tokens[:8]


def _normalize_fact_match_text(text: str) -> str:
    return re.sub(r"\s+", "", text or "").lower()


def _trace_fact_labels(trace_diagnostics: dict[str, Any], *, statuses: set[str], limit: int) -> list[str]:
    labels: list[str] = []
    for item in trace_diagnostics.get("facts") or []:
        if item.get("status") not in statuses:
            continue
        fact = str(item.get("fact") or "").strip()
        if not fact:
            continue
        status = item.get("status")
        action = item.get("suggested_action")
        label = f"{fact} [{status} -> {action}]"
        if label not in labels:
            labels.append(label)
        if len(labels) >= limit:
            break
    return labels


def _clean_heading_candidate(value: str) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    text = re.sub(r"^\s*[-*+\d.、\)\(]+\s*", "", text)
    text = re.sub(r"\s*\.{2,}\s*\d*\s*$", "", text)
    text = re.sub(r"\s*[-_—]{2,}\s*\d*\s*$", "", text)
    text = re.sub(r"\s+\d+\s*$", "", text)
    text = re.sub(r"\s+", " ", text).strip(" -._\t")
    if len(text) < 2 or len(text) > 80:
        return ""
    if not re.search(r"[\w\u4e00-\u9fff]", text):
        return ""
    return text


def _quality_heading_target(title: str) -> int:
    if any(term in title for term in ("施工", "质量", "安全", "环保", "进度", "资源", "布置", "灌浆", "注水", "覆盖", "钻孔")):
        return 1000
    return 700


def _title_key(title: str) -> str:
    return re.sub(r"[\s\W_]+", "", title).lower()


def _dedupe_actions(actions: list[QualityFeedbackAction]) -> list[QualityFeedbackAction]:
    output_by_key: dict[tuple[str, str], QualityFeedbackAction] = {}
    for action in actions:
        key = (action.action, action.target)
        existing = output_by_key.get(key)
        if existing is None:
            output_by_key[key] = action
            continue
        output_by_key[key] = QualityFeedbackAction(
            action=existing.action,
            target=existing.target,
            severity=_stronger_severity(existing.severity, action.severity),
            reason=_append_reason(existing.reason, action.reason),
            source_metrics={**existing.source_metrics, **action.source_metrics},
            next_steps=_dedupe_strings([*existing.next_steps, *action.next_steps]),
            missing_heading_examples=_dedupe_strings(
                [*existing.missing_heading_examples, *action.missing_heading_examples]
            ),
            omitted_source_facts=_dedupe_strings([*existing.omitted_source_facts, *action.omitted_source_facts]),
            missing_common_topics=_dedupe_strings([*existing.missing_common_topics, *action.missing_common_topics]),
            policy_adjustments=[*existing.policy_adjustments, *action.policy_adjustments],
        )
    return list(output_by_key.values())


def _stronger_severity(left: str, right: str) -> str:
    order = {"info": 0, "warning": 1, "error": 2}
    return left if order.get(left, 0) >= order.get(right, 0) else right


def _dedupe_strings(items: list[str]) -> list[str]:
    output: list[str] = []
    seen: set[str] = set()
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        output.append(item)
    return output


def _dedupe_triggers(triggers: list[RevisionTrigger]) -> list[RevisionTrigger]:
    seen: set[tuple[str, str, str]] = set()
    output: list[RevisionTrigger] = []
    for trigger in triggers:
        key = (trigger.node_id, trigger.title, trigger.action)
        if key in seen:
            continue
        seen.add(key)
        output.append(trigger)
    return output


def _merge_policy_adjustments(adjustments) -> dict[str, ChapterPolicyAdjustment]:
    merged: dict[str, ChapterPolicyAdjustment] = {}
    for adjustment in adjustments:
        existing = merged.get(adjustment.node_id)
        if existing is None:
            merged[adjustment.node_id] = adjustment
            continue
        merged[adjustment.node_id] = ChapterPolicyAdjustment(
            node_id=adjustment.node_id,
            title=adjustment.title or existing.title,
            current_target_word_count=existing.current_target_word_count,
            next_target_word_count=_max_optional_int(existing.next_target_word_count, adjustment.next_target_word_count),
            current_detail_level=existing.current_detail_level,
            next_detail_level=_stronger_detail_level(existing.next_detail_level, adjustment.next_detail_level),
            next_max_source_matches=_max_optional_int(existing.next_max_source_matches, adjustment.next_max_source_matches),
            next_max_evidence_spans=_max_optional_int(existing.next_max_evidence_spans, adjustment.next_max_evidence_spans),
            split_required=bool(existing.split_required or adjustment.split_required),
            reason=_append_reason(existing.reason, adjustment.reason),
        )
    return merged


def _max_optional_int(left: int | None, right: int | None) -> int | None:
    if left is None:
        return right
    if right is None:
        return left
    return max(left, right)


def _stronger_detail_level(left, right):
    order = {"brief": 0, "normal": 1, "deep": 2, "subsection_required": 3}
    if left is None:
        return right
    if right is None:
        return left
    return left if order.get(left, 0) >= order.get(right, 0) else right


def _append_reason(old: str, new: str) -> str:
    if not old:
        return new
    if not new or new in old:
        return old
    return f"{old} {new}"


def _copy_model(model: Any, **update: Any) -> Any:
    if hasattr(model, "model_copy"):
        return model.model_copy(update=update)
    return model.copy(update=update)
