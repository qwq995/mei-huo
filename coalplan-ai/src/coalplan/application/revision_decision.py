from __future__ import annotations

from coalplan.application.word_count_targets import count_words
from coalplan.domain.enums import TaskStatus
from coalplan.domain.generation import ChapterDraft, ChapterTask, GenerationRun
from coalplan.domain.generation_control import ChapterGenerationPolicy, ChapterRevisionDecision
from coalplan.domain.templates import TemplateNode, TemplateTree, iter_template_nodes


FORMAT_ISSUE_CODES = {"json_output", "missing_title", "missing_required_heading", "unexpected_heading"}
SOURCE_ISSUE_CODES = {"missing_source_summary"}
FACT_ISSUE_CODES = {"possible_guessed_fact"}


def build_revision_decisions(
    *,
    run: GenerationRun,
    drafts: list[ChapterDraft],
    template_tree: TemplateTree,
    policies: list[ChapterGenerationPolicy],
) -> list[ChapterRevisionDecision]:
    draft_by_node = {draft.node_id: draft for draft in drafts}
    policy_by_node = {policy.node_id: policy for policy in policies}
    node_by_id = {node.id: node for node in iter_template_nodes(template_tree.nodes)}
    return [
        build_revision_decision(
            task=task,
            draft=draft_by_node.get(task.node_id),
            node=node_by_id.get(task.node_id),
            policy=policy_by_node.get(task.node_id),
        )
        for task in run.chapter_tasks
    ]


def build_revision_decision(
    *,
    task: ChapterTask,
    draft: ChapterDraft | None,
    node: TemplateNode | None,
    policy: ChapterGenerationPolicy | None,
) -> ChapterRevisionDecision:
    issue_codes = [issue.code for issue in (draft.validation_issues if draft else [])]
    evidence_audit = draft.evidence_audit if draft else None
    actual_word_count = count_words(draft.markdown) if draft else None
    target_word_count = task.target_word_count or (policy.target_word_count if policy else None)
    source_section_ids = [match.section_id for match in task.source_matches]
    missing_evidence = []
    if task.source_mapping:
        missing_evidence = task.source_mapping.missing_evidence
    if not source_section_ids and task.source_mapping and not task.source_mapping.matches:
        missing_evidence = missing_evidence or ["未匹配到可靠来源章节。"]

    if not source_section_ids and task.source_mapping and not task.source_mapping.matches:
        return ChapterRevisionDecision(
            node_id=task.node_id,
            title=task.title,
            decision="request_human_input",
            severity="warning",
            reasons=["当前章节没有可靠来源映射，不应生成确定性正文。"],
            required_changes=["补充来源资料，禁用该目录节点，或将其改为仅保留人工补充占位的章节。"],
            missing_evidence=missing_evidence,
            source_section_ids=source_section_ids,
            target_word_count=target_word_count,
            actual_word_count=actual_word_count,
            evidence_audit=evidence_audit,
        )

    if task.error_message and draft is None:
        return ChapterRevisionDecision(
            node_id=task.node_id,
            title=task.title,
            decision="regenerate",
            severity="error",
            reasons=[f"章节生成过程异常：{task.error_message}"],
            required_changes=["检查来源映射、prompt 和 LLM 响应后重新生成。"],
            missing_evidence=missing_evidence,
            source_section_ids=source_section_ids,
            target_word_count=target_word_count,
            actual_word_count=actual_word_count,
            evidence_audit=evidence_audit,
        )

    if draft is not None and draft.validation_status == TaskStatus.failed:
        if any(code in FORMAT_ISSUE_CODES for code in issue_codes):
            return ChapterRevisionDecision(
                node_id=task.node_id,
                title=task.title,
                decision="repair_format",
                severity="error",
                reasons=["Markdown 输出不符合固定章节合同。"],
                required_changes=["调用格式修复 prompt，保留事实内容并恢复固定标题模块。"],
                validation_issue_codes=issue_codes,
                source_section_ids=source_section_ids,
                target_word_count=target_word_count,
                actual_word_count=actual_word_count,
                evidence_audit=evidence_audit,
            )
        if any(code in SOURCE_ISSUE_CODES for code in issue_codes):
            return ChapterRevisionDecision(
                node_id=task.node_id,
                title=task.title,
                decision="remap_sources",
                severity="error",
                reasons=["生成正文未列出可追溯来源摘要。"],
                required_changes=["重新执行来源映射并要求正文引用 section_id/evidence_id。"],
                missing_evidence=missing_evidence,
                validation_issue_codes=issue_codes,
                source_section_ids=source_section_ids,
                target_word_count=target_word_count,
                actual_word_count=actual_word_count,
                evidence_audit=evidence_audit,
            )
        if any(code in FACT_ISSUE_CODES for code in issue_codes):
            return ChapterRevisionDecision(
                node_id=task.node_id,
                title=task.title,
                decision="regenerate",
                severity="error",
                reasons=["正文疑似将未确认参数写成确定事实。"],
                required_changes=["重生成时强制缺失参数使用人工补充占位。"],
                validation_issue_codes=issue_codes,
                source_section_ids=source_section_ids,
                target_word_count=target_word_count,
                actual_word_count=actual_word_count,
                evidence_audit=evidence_audit,
            )
        return ChapterRevisionDecision(
            node_id=task.node_id,
            title=task.title,
            decision="regenerate",
            severity="error",
            reasons=["章节校验失败。"],
            required_changes=["根据校验问题重新生成或人工修订。"],
            validation_issue_codes=issue_codes,
            source_section_ids=source_section_ids,
            target_word_count=target_word_count,
            actual_word_count=actual_word_count,
            evidence_audit=evidence_audit,
        )

    if not source_section_ids:
        return ChapterRevisionDecision(
            node_id=task.node_id,
            title=task.title,
            decision="request_human_input",
            severity="warning",
            reasons=["当前章节没有可追溯来源，不应生成确定性正文。"],
            required_changes=["补充来源资料，或禁用该目录节点。"],
            missing_evidence=missing_evidence,
            source_section_ids=source_section_ids,
            target_word_count=target_word_count,
            actual_word_count=actual_word_count,
            evidence_audit=evidence_audit,
        )

    has_children = bool(node and node.children)
    if policy and policy.split_required and not has_children:
        return ChapterRevisionDecision(
            node_id=task.node_id,
            title=task.title,
            decision="expand_subsections",
            severity="warning",
            reasons=["该章属于高信息密度工艺章节，直接整章生成容易变成概述。"],
            required_changes=["先生成小节拆分 proposal，再逐小节映射来源和生成正文。"],
            source_section_ids=source_section_ids,
            target_word_count=target_word_count,
            actual_word_count=actual_word_count,
            evidence_audit=evidence_audit,
        )

    if evidence_audit and evidence_audit.manual_items_with_source_support:
        return ChapterRevisionDecision(
            node_id=task.node_id,
            title=task.title,
            decision="regenerate",
            severity="warning",
            reasons=["章节仍保留人工补充占位，但映射原文证据中已有可使用的信息。"],
            required_changes=[
                "重新生成时优先吸收 evidence_id 对应的原文事实，将可确定内容写入正文；只把原文确实缺失的信息保留为人工补充。"
            ],
            source_section_ids=source_section_ids,
            target_word_count=target_word_count,
            actual_word_count=actual_word_count,
            evidence_audit=evidence_audit,
        )

    if evidence_audit and evidence_audit.omitted_required_fact_ids:
        omitted_text = [
            fact.text for fact in evidence_audit.required_source_facts if fact.fact_id in evidence_audit.omitted_required_fact_ids
        ]
        return ChapterRevisionDecision(
            node_id=task.node_id,
            title=task.title,
            decision="regenerate",
            severity="warning",
            reasons=["生成正文遗漏了已映射原文中的关键工程量、参数、日期、规范或工艺控制点。"],
            required_changes=[
                "重新生成时必须优先吸收 required_source_facts；确不适用于本节时，应在人工补充需补充中说明不采用原因。",
                *[f"补入或说明：{item}" for item in omitted_text[:8]],
            ],
            source_section_ids=source_section_ids,
            target_word_count=target_word_count,
            actual_word_count=actual_word_count,
            evidence_audit=evidence_audit,
        )

    if (
        evidence_audit
        and evidence_audit.evidence_count >= 3
        and evidence_audit.coverage_ratio is not None
        and evidence_audit.coverage_ratio < 0.35
        and evidence_audit.unused_high_value_evidence_ids
    ):
        return ChapterRevisionDecision(
            node_id=task.node_id,
            title=task.title,
            decision="regenerate",
            severity="warning",
            reasons=["章节通过了基础格式校验，但高价值原文证据利用率偏低。"],
            required_changes=[
                "扩大生成正文对工程量、工期、施工方法、质量安全环保目标等 evidence_id 的吸收，避免只写流程性泛化表述。"
            ],
            source_section_ids=source_section_ids,
            target_word_count=target_word_count,
            actual_word_count=actual_word_count,
            evidence_audit=evidence_audit,
        )

    pattern_gap = _pattern_fact_gap(policy, evidence_audit)
    if pattern_gap:
        return ChapterRevisionDecision(
            node_id=task.node_id,
            title=task.title,
            decision="remap_sources",
            severity="warning",
            reasons=[
                f"Matched local writing pattern `{policy.writing_pattern_key}` expects source-backed facts, but the mapped evidence did not provide usable required_source_facts."
            ],
            required_changes=[
                "Re-run source mapping and evidence extraction with the local writing pattern requirements as search hints.",
                "If the bid document truly lacks these facts, keep them as human-fill placeholders instead of generating unsupported prose.",
                *[f"Pattern expects source support for: {item}" for item in pattern_gap[:8]],
            ],
            source_section_ids=source_section_ids,
            target_word_count=target_word_count,
            actual_word_count=actual_word_count,
            evidence_audit=evidence_audit,
        )

    if target_word_count and actual_word_count is not None and actual_word_count < max(250, int(target_word_count * 0.45)):
        return ChapterRevisionDecision(
            node_id=task.node_id,
            title=task.title,
            decision="regenerate",
            severity="warning",
            reasons=["生成正文显著低于目标详略预算。"],
            required_changes=["扩大证据片段或按小节重生成；来源不足时写明人工补充项。"],
            source_section_ids=source_section_ids,
            target_word_count=target_word_count,
            actual_word_count=actual_word_count,
            evidence_audit=evidence_audit,
        )

    return ChapterRevisionDecision(
        node_id=task.node_id,
        title=task.title,
        decision="accept",
        severity="info",
        reasons=["章节通过格式与来源基础检查。"],
        source_section_ids=source_section_ids,
        target_word_count=target_word_count,
        actual_word_count=actual_word_count,
        evidence_audit=evidence_audit,
    )


def _pattern_fact_gap(
    policy: ChapterGenerationPolicy | None,
    evidence_audit,
) -> list[str]:
    if policy is None or evidence_audit is None:
        return []
    if not policy.writing_pattern_key or not policy.pattern_required_source_facts:
        return []
    if evidence_audit.evidence_count <= 0:
        return []
    if evidence_audit.required_source_facts:
        return []
    if policy.writing_pattern_key not in {"overview", "deployment", "craft", "quality", "safety", "environment", "schedule_resource"}:
        return []
    return policy.pattern_required_source_facts


def render_revision_decisions(decisions: list[ChapterRevisionDecision]) -> str:
    lines = ["# Chapter Revision Decisions", ""]
    for item in decisions:
        lines.extend(
            [
                f"## {item.title}",
                f"- node_id: `{item.node_id}`",
                f"- decision: {item.decision}",
                f"- severity: {item.severity}",
                f"- words: {item.actual_word_count or '-'} / {item.target_word_count or '-'}",
                f"- sources: {', '.join(item.source_section_ids) if item.source_section_ids else '-'}",
                "- reasons:",
                *[f"  - {reason}" for reason in item.reasons],
            ]
        )
        if item.required_changes:
            lines.extend(["- required_changes:", *[f"  - {change}" for change in item.required_changes]])
        if item.missing_evidence:
            lines.extend(["- missing_evidence:", *[f"  - {evidence}" for evidence in item.missing_evidence]])
        if item.evidence_audit:
            lines.extend(
                [
                    f"- evidence_coverage: {item.evidence_audit.coverage_ratio if item.evidence_audit.coverage_ratio is not None else '-'}",
                    f"- unused_high_value_evidence: {', '.join(item.evidence_audit.unused_high_value_evidence_ids) if item.evidence_audit.unused_high_value_evidence_ids else '-'}",
                    f"- omitted_required_facts: {', '.join(item.evidence_audit.omitted_required_fact_ids) if item.evidence_audit.omitted_required_fact_ids else '-'}",
                ]
            )
            if item.evidence_audit.manual_items_with_source_support:
                lines.extend(
                    [
                        "- manual_items_with_source_support:",
                        *[f"  - {item}" for item in item.evidence_audit.manual_items_with_source_support],
                    ]
                )
        lines.append("")
    return "\n".join(lines).strip() + "\n"
