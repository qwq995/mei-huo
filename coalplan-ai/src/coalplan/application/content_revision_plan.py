from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, Field

from coalplan.domain.generated_content import GeneratedContentNode, GeneratedContentTree
from coalplan.domain.generation_control import EvidenceUtilizationAudit, RequiredSourceFact


ContentNodeAction = Literal[
    "accept",
    "review_source_link",
    "remap_sources",
    "rewrite_subsection",
    "request_human_input",
    "split_subsection",
]


class ContentNodeRevisionItem(BaseModel):
    content_node_id: str
    title: str
    title_path: list[str] = Field(default_factory=list)
    source_status: str
    word_count: int = 0
    action: ContentNodeAction
    severity: Literal["info", "warning", "error"] = "info"
    reason: str = ""
    requires_llm: bool = False
    requires_user_confirmation: bool = False
    source_section_ids: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)
    next_steps: list[str] = Field(default_factory=list)


class ContentRevisionPlan(BaseModel):
    node_id: str
    version_id: str | None = None
    title: str
    status: Literal["passed", "warning", "blocked"] = "passed"
    metrics: dict[str, int] = Field(default_factory=dict)
    items: list[ContentNodeRevisionItem] = Field(default_factory=list)
    artifact_path: str | None = None


def build_content_revision_plan(
    tree: GeneratedContentTree | dict,
    *,
    evidence_audit: EvidenceUtilizationAudit | dict | None = None,
    minimum_subsection_words: int = 80,
    dense_subsection_words: int = 650,
) -> ContentRevisionPlan:
    model = _coerce_tree(tree)
    audit = _coerce_audit(evidence_audit)
    items: list[ContentNodeRevisionItem] = []
    candidates = _candidate_nodes(model.nodes)
    for node in candidates:
        items.append(
            _node_revision_item(
                node,
                minimum_subsection_words=minimum_subsection_words,
                dense_subsection_words=dense_subsection_words,
            )
        )
    items = _apply_evidence_audit_items(items, candidates, audit)
    actionable = [item for item in items if item.action != "accept"]
    errors = [item for item in actionable if item.severity == "error"]
    status: Literal["passed", "warning", "blocked"] = "blocked" if errors else ("warning" if actionable else "passed")
    return ContentRevisionPlan(
        node_id=model.node_id,
        version_id=model.version_id,
        title=model.title,
        status=status,
        items=items,
        metrics={
            "candidate_count": len(candidates),
            "actionable_count": len(actionable),
            "missing_source_count": sum(1 for item in items if item.source_status == "missing"),
            "weak_source_count": sum(1 for item in items if item.source_status == "weak"),
            "rewrite_count": sum(1 for item in items if item.action == "rewrite_subsection"),
            "split_count": sum(1 for item in items if item.action == "split_subsection"),
            "human_input_count": sum(1 for item in items if item.action == "request_human_input"),
            "evidence_targeted_rewrite_count": sum(1 for item in items if "omitted_required_source_facts" in item.reason),
        },
    )


def render_content_revision_plan_markdown(plan: ContentRevisionPlan) -> str:
    lines = [
        "# Content Revision Plan",
        "",
        f"- node_id: `{plan.node_id}`",
        f"- version_id: `{plan.version_id or '-'}`",
        f"- status: `{plan.status}`",
        f"- title: {plan.title}",
        "",
        "## Metrics",
        "",
    ]
    lines.extend(f"- {key}: {value}" for key, value in plan.metrics.items())
    lines.extend(["", "## Items", ""])
    if not plan.items:
        lines.append("- No generated content subsection was found for revision planning.")
    for item in plan.items:
        markers = []
        if item.requires_llm:
            markers.append("LLM")
        if item.requires_user_confirmation:
            markers.append("user")
        marker_text = f" ({', '.join(markers)})" if markers else ""
        lines.append(
            f"- `{item.action}` [{item.severity}] {item.title} "
            f"source=`{item.source_status}` words={item.word_count}{marker_text}"
        )
        if item.reason:
            lines.append(f"  - reason: {item.reason}")
        if item.source_section_ids:
            lines.append(f"  - sections: {', '.join(item.source_section_ids[:8])}")
        if item.evidence_ids:
            lines.append(f"  - evidence: {', '.join(item.evidence_ids[:8])}")
        for step in item.next_steps[:4]:
            lines.append(f"  - next: {step}")
    return "\n".join(lines).strip() + "\n"


def _coerce_tree(tree: GeneratedContentTree | dict) -> GeneratedContentTree:
    if isinstance(tree, GeneratedContentTree):
        return tree
    if hasattr(GeneratedContentTree, "model_validate"):
        return GeneratedContentTree.model_validate(tree)
    return GeneratedContentTree.parse_obj(tree)


def _coerce_audit(audit: EvidenceUtilizationAudit | dict | None) -> EvidenceUtilizationAudit | None:
    if audit is None:
        return None
    if isinstance(audit, EvidenceUtilizationAudit):
        return audit
    if hasattr(EvidenceUtilizationAudit, "model_validate"):
        return EvidenceUtilizationAudit.model_validate(audit)
    return EvidenceUtilizationAudit.parse_obj(audit)


def _candidate_nodes(nodes: list[GeneratedContentNode]) -> list[GeneratedContentNode]:
    all_nodes = list(_walk(nodes))
    body_nodes = [node for node in all_nodes if _under_generated_body(node) and not node.children and _is_revision_candidate(node)]
    if body_nodes:
        return body_nodes
    return [node for node in all_nodes if not node.children and _is_revision_candidate(node)]


def _is_revision_candidate(node: GeneratedContentNode) -> bool:
    if _is_non_body_module(node):
        return False
    text = (node.body or node.markdown or "").strip()
    if not text:
        return False
    if _contains_manual_placeholder(text):
        return True
    if _under_generated_body(node):
        return True
    return node.source_status in {"missing", "weak", "covered"} or _looks_like_content(text)


def _apply_evidence_audit_items(
    items: list[ContentNodeRevisionItem],
    candidates: list[GeneratedContentNode],
    audit: EvidenceUtilizationAudit | None,
) -> list[ContentNodeRevisionItem]:
    if audit is None or not audit.omitted_required_fact_ids:
        return items
    facts_by_id = {fact.fact_id: fact for fact in audit.required_source_facts}
    omitted_facts = [facts_by_id[fact_id] for fact_id in audit.omitted_required_fact_ids if fact_id in facts_by_id]
    if not omitted_facts:
        return items
    item_by_id = {item.content_node_id: item for item in items}
    facts_by_node: dict[str, list[RequiredSourceFact]] = {}
    for fact in omitted_facts:
        node = _best_node_for_fact(fact, candidates)
        if node is None:
            continue
        facts_by_node.setdefault(node.id, []).append(fact)
    if not facts_by_node:
        return items
    revised: list[ContentNodeRevisionItem] = []
    for item in items:
        facts = facts_by_node.get(item.content_node_id)
        if not facts:
            revised.append(item)
            continue
        evidence_ids = _dedupe([*item.evidence_ids, *[fact.evidence_id for fact in facts]])
        source_section_ids = _dedupe([*item.source_section_ids, *[fact.section_id for fact in facts]])
        fact_steps = [
            f"Insert or explicitly route omitted required source fact `{fact.fact_id}` from evidence `{fact.evidence_id}` / section `{fact.section_id}`: {fact.text}"
            for fact in facts[:8]
        ]
        action: ContentNodeAction = "rewrite_subsection" if item.action in {"accept", "review_source_link"} else item.action
        severity: Literal["info", "warning", "error"] = "warning" if item.severity == "info" else item.severity
        revised.append(
            item.model_copy(
                update={
                    "action": action,
                    "severity": severity,
                    "reason": _join_reason(item.reason, "omitted_required_source_facts must be absorbed or explained in this generated subsection."),
                    "requires_llm": True,
                    "source_section_ids": source_section_ids,
                    "evidence_ids": evidence_ids,
                    "next_steps": _dedupe([*fact_steps, *item.next_steps]),
                }
            )
        )
    return revised


def _best_node_for_fact(fact: RequiredSourceFact, candidates: list[GeneratedContentNode]) -> GeneratedContentNode | None:
    linked = [
        node
        for node in candidates
        if any(link.evidence_id == fact.evidence_id for link in node.source_links)
        or any(link.section_id == fact.section_id for link in node.source_links)
    ]
    if linked:
        return max(linked, key=lambda node: _fact_overlap_score(fact, node))
    scored = [(node, _fact_overlap_score(fact, node)) for node in candidates]
    scored = [(node, score) for node, score in scored if score > 0]
    if not scored:
        body_nodes = [node for node in candidates if _under_generated_body(node)]
        return body_nodes[0] if body_nodes else (candidates[0] if candidates else None)
    return max(scored, key=lambda item: item[1])[0]


def _fact_overlap_score(fact: RequiredSourceFact, node: GeneratedContentNode) -> float:
    text = _compact(f"{node.title} {' '.join(node.title_path)} {node.body} {node.markdown}")
    terms = _dedupe([*fact.tokens, *_terms(fact.text), *_terms(fact.reason)])
    score = 0.0
    for term in terms:
        if not term:
            continue
        if term in text:
            score += 2.0 if term in fact.tokens else 1.0
    for link in node.source_links:
        if link.evidence_id == fact.evidence_id:
            score += 6.0
        if link.section_id == fact.section_id:
            score += 3.0
    return score


def _node_revision_item(
    node: GeneratedContentNode,
    *,
    minimum_subsection_words: int,
    dense_subsection_words: int,
) -> ContentNodeRevisionItem:
    word_count = _word_count(node.body or node.markdown)
    source_section_ids = _dedupe([link.section_id for link in node.source_links if link.section_id])
    evidence_ids = _dedupe([link.evidence_id for link in node.source_links if link.evidence_id])
    if _contains_manual_placeholder(node.body):
        return _item(
            node,
            word_count,
            "request_human_input",
            "warning",
            "The subsection contains manual placeholders and should be completed from user supplements before final merge.",
            source_section_ids,
            evidence_ids,
            requires_user_confirmation=True,
            next_steps=[
                "Ask the user to persist supplement text, tables, attachment notes, or approved parameters in this chapter workspace.",
                "Regenerate or manually edit this subsection after the supplement is available.",
            ],
        )
    if node.source_status == "missing":
        return _item(
            node,
            word_count,
            "remap_sources",
            "error",
            "The subsection appears factual but has no source section or evidence link.",
            source_section_ids,
            evidence_ids,
            requires_llm=True,
            next_steps=[
                "Re-run source mapping with this subsection title and body as search hints.",
                "If no reliable source exists, route the subsection to human input instead of factual generation.",
            ],
        )
    if node.source_status == "weak":
        return _item(
            node,
            word_count,
            "review_source_link",
            "warning",
            "The subsection only has weak keyword-overlap evidence and should be checked before merge.",
            source_section_ids,
            evidence_ids,
            requires_llm=True,
            next_steps=[
                "Re-rank evidence spans or ask the model to remap sources for this subsection.",
                "Keep unsupported values as manual-fill placeholders.",
            ],
        )
    if word_count >= dense_subsection_words and _has_multiple_control_topics(node.body):
        return _item(
            node,
            word_count,
            "split_subsection",
            "warning",
            "The subsection is dense and mixes multiple control topics; split it into smaller generated content nodes.",
            source_section_ids,
            evidence_ids,
            requires_user_confirmation=True,
            next_steps=[
                "Create child outline or content nodes from process, resources, quality, safety, environment, and acceptance topics.",
                "Map and regenerate the split nodes one by one.",
            ],
        )
    if 0 < word_count < minimum_subsection_words and node.source_status in {"covered", "weak"}:
        return _item(
            node,
            word_count,
            "rewrite_subsection",
            "warning",
            "The subsection is source-linked but too brief for construction-organization detail.",
            source_section_ids,
            evidence_ids,
            requires_llm=True,
            next_steps=[
                "Regenerate this subsection using mapped evidence, target word count, and local writing pattern structure.",
                "Do not add unsupported parameters only to increase length.",
            ],
        )
    return _item(
        node,
        word_count,
        "accept",
        "info",
        "The subsection has acceptable source status and no immediate revision trigger.",
        source_section_ids,
        evidence_ids,
    )


def _item(
    node: GeneratedContentNode,
    word_count: int,
    action: ContentNodeAction,
    severity: Literal["info", "warning", "error"],
    reason: str,
    source_section_ids: list[str],
    evidence_ids: list[str],
    *,
    requires_llm: bool = False,
    requires_user_confirmation: bool = False,
    next_steps: list[str] | None = None,
) -> ContentNodeRevisionItem:
    return ContentNodeRevisionItem(
        content_node_id=node.id,
        title=node.title,
        title_path=node.title_path,
        source_status=node.source_status,
        word_count=word_count,
        action=action,
        severity=severity,
        reason=reason,
        requires_llm=requires_llm,
        requires_user_confirmation=requires_user_confirmation,
        source_section_ids=source_section_ids,
        evidence_ids=evidence_ids,
        next_steps=next_steps or [],
    )


def _join_reason(*parts: str) -> str:
    return " ".join(part.strip() for part in parts if part and part.strip())


def _under_generated_body(node: GeneratedContentNode) -> bool:
    return any(title in {"生成正文", "鐢熸垚姝ｆ枃"} for title in node.title_path)


def _is_non_body_module(node: GeneratedContentNode) -> bool:
    return node.title in {
        "主要来源摘要",
        "涓昏鏉ユ簮鎽樿",
        "人工补充需补充",
        "浜哄伐琛ュ厖闇€琛ュ厖",
        "特殊备注",
        "鐗规畩澶囨敞",
    }


def _contains_manual_placeholder(text: str) -> bool:
    return "需人工补充" in text or "闇€浜哄伐琛ュ厖" in text


def _looks_like_content(text: str) -> bool:
    compact = re.sub(r"\s+", "", text or "")
    if len(compact) >= 80:
        return True
    terms = ("施工", "工程", "工艺", "质量", "安全", "环保", "进度", "验收", "控制", "鏂藉伐", "宸ョ▼", "宸ヨ壓", "璐ㄩ噺", "瀹夊叏", "楠屾敹", "鎺у埗")
    return sum(1 for term in terms if term in compact) >= 2


def _has_multiple_control_topics(text: str) -> bool:
    groups = [
        ("流程", "工艺", "施工方法", "娴佺▼", "宸ヨ壓"),
        ("人员", "设备", "材料", "机械", "浜哄憳", "璁惧"),
        ("质量", "检验", "验收", "璐ㄩ噺", "楠屾敹"),
        ("安全", "风险", "应急", "瀹夊叏", "搴旀€"),
        ("环保", "文明施工", "水保", "鐜繚"),
    ]
    compact = text or ""
    return sum(1 for group in groups if any(term in compact for term in group)) >= 3


def _word_count(text: str) -> int:
    chinese = re.findall(r"[\u4e00-\u9fff]", text or "")
    latin = re.findall(r"[A-Za-z0-9]+", text or "")
    return len(chinese) + len(latin)


def _terms(text: str) -> list[str]:
    return re.findall(r"[\u4e00-\u9fff]{2,12}|[A-Za-z][A-Za-z0-9_-]{1,30}|\d+(?:\.\d+)?\s*(?:MPa|kPa|m3/h|m³/h|m3/min|m³/min|mm|cm|m|km|%|h|d)?", text or "")


def _compact(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def _dedupe(items: list[str | None]) -> list[str]:
    seen: set[str] = set()
    output: list[str] = []
    for item in items:
        if not item or item in seen:
            continue
        seen.add(item)
        output.append(item)
    return output


def _walk(nodes: list[GeneratedContentNode]):
    for node in nodes:
        yield node
        yield from _walk(node.children)
