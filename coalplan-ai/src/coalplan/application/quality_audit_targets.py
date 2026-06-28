from __future__ import annotations

import re
from typing import Any, Literal

from pydantic import BaseModel, Field


AuditTargetType = Literal["outline", "chapter", "content_node", "detail_budget"]
AuditTargetAction = Literal[
    "propose_outline_repair",
    "increase_detail_budget",
    "remap_sources",
    "regenerate",
    "rewrite_subsection",
    "request_human_input",
]


class QualityAuditRevisionTarget(BaseModel):
    target_type: AuditTargetType
    action: AuditTargetAction
    severity: Literal["info", "warning", "error"] = "warning"
    title: str
    reason: str
    node_id: str | None = None
    version_id: str | None = None
    content_node_id: str | None = None
    evidence: list[str] = Field(default_factory=list)
    requires_llm: bool = False
    requires_user_confirmation: bool = False


class QualityAuditRevisionTargets(BaseModel):
    project_id: str
    status: Literal["passed", "warning", "blocked"] = "passed"
    summary: str = ""
    targets: list[QualityAuditRevisionTarget] = Field(default_factory=list)


def build_quality_audit_revision_targets(
    *,
    project_id: str,
    report: dict[str, Any],
    outline_nodes: list[dict[str, Any]],
    workspaces: dict[str, dict[str, Any]] | None = None,
    source_toc_items: list[Any] | None = None,
    limit: int = 40,
) -> QualityAuditRevisionTargets:
    workspaces = workspaces or {}
    source_toc = [_toc_item_dict(item) for item in (source_toc_items or [])]
    node_indexes = [_node_index(node, workspaces.get(str(node.get("node_id") or ""))) for node in outline_nodes]
    targets: list[QualityAuditRevisionTarget] = []

    for heading in _missing_headings(report):
        target = _heading_target(str(heading), node_indexes)
        targets.append(target)
        if len(targets) >= limit:
            break

    if len(targets) < limit and _needs_detail_budget(report):
        targets.append(
            QualityAuditRevisionTarget(
                target_type="detail_budget",
                action="increase_detail_budget",
                title="Review generated document detail budget",
                reason="Quality audit found the generated document is much shorter than the human reference.",
                evidence=[str((report.get("word_counts") or {}).get("generated_vs_human_ratio"))],
                requires_user_confirmation=True,
            )
        )

    for fact in _omitted_facts(report):
        if len(targets) >= limit:
            break
        targets.append(_fact_target(fact, node_indexes, source_toc))

    for topic in _missing_topics(report):
        if len(targets) >= limit:
            break
        targets.append(_topic_target(topic, node_indexes))

    targets = _dedupe_targets(targets)[:limit]
    actionable = [target for target in targets if target.action != "request_human_input" or target.target_type != "outline"]
    status: Literal["passed", "warning", "blocked"] = "warning" if targets else "passed"
    return QualityAuditRevisionTargets(
        project_id=project_id,
        status=status,
        summary=_summary(targets, actionable),
        targets=targets,
    )


def render_quality_audit_revision_targets(plan: QualityAuditRevisionTargets) -> str:
    lines = [
        "# Quality Audit Revision Targets",
        "",
        f"- project_id: `{plan.project_id}`",
        f"- status: `{plan.status}`",
        f"- summary: {plan.summary}",
        "",
        "## Targets",
        "",
    ]
    if not plan.targets:
        lines.append("- No project-level quality-audit revision target.")
        return "\n".join(lines).strip() + "\n"
    for target in plan.targets:
        lines.append(f"- `{target.action}` [{target.severity}] {target.title}")
        lines.append(f"  - type: `{target.target_type}`")
        if target.node_id:
            lines.append(f"  - node_id: `{target.node_id}`")
        if target.version_id:
            lines.append(f"  - version_id: `{target.version_id}`")
        if target.content_node_id:
            lines.append(f"  - content_node_id: `{target.content_node_id}`")
        lines.append(f"  - reason: {target.reason}")
        if target.evidence:
            lines.append("  - evidence:")
            lines.extend(f"    - {item}" for item in target.evidence[:8])
    return "\n".join(lines).strip() + "\n"


def _missing_headings(report: dict[str, Any]) -> list[str]:
    headings = report.get("headings") or {}
    return [str(item) for item in headings.get("missing_human_heading_examples") or [] if str(item).strip()]


def _omitted_facts(report: dict[str, Any]) -> list[dict[str, Any]]:
    facts = (report.get("source_facts") or {}).get("omitted_examples") or []
    output: list[dict[str, Any]] = []
    for item in facts:
        if isinstance(item, dict):
            output.append(item)
        else:
            output.append({"fact": str(item)})
    return output


def _missing_topics(report: dict[str, Any]) -> list[str]:
    topics = report.get("common_topics") or {}
    output: list[str] = []
    for key, item in topics.items():
        if not isinstance(item, dict) or item.get("covered"):
            continue
        output.append(str(key))
    return output


def _needs_detail_budget(report: dict[str, Any]) -> bool:
    ratio = (report.get("word_counts") or {}).get("generated_vs_human_ratio")
    try:
        return ratio is not None and float(ratio) < 0.35
    except (TypeError, ValueError):
        return False


def _heading_target(heading: str, node_indexes: list[dict[str, Any]]) -> QualityAuditRevisionTarget:
    node = _best_node(heading, node_indexes)
    if node and node["score"] >= 0.25:
        return QualityAuditRevisionTarget(
            target_type="chapter",
            action="regenerate",
            title=node["title"],
            node_id=node["node_id"],
            version_id=node.get("version_id"),
            reason=f"Human-reference heading is missing or weakly covered: {heading}",
            evidence=[heading],
            requires_llm=bool(node.get("version_id")),
            requires_user_confirmation=not bool(node.get("version_id")),
        )
    return QualityAuditRevisionTarget(
        target_type="outline",
        action="propose_outline_repair",
        title=heading,
        reason="Quality audit found this human-reference heading missing from the generated outline.",
        evidence=[heading],
        requires_user_confirmation=True,
    )


def _fact_target(
    fact: dict[str, Any],
    node_indexes: list[dict[str, Any]],
    source_toc: list[dict[str, Any]],
) -> QualityAuditRevisionTarget:
    fact_text = str(fact.get("fact") or "").strip()
    context = str(fact.get("context") or fact_text).strip()
    search_text = " ".join([fact_text, context, _matched_toc_text(context or fact_text, source_toc)])
    node = _best_node(search_text, node_indexes)
    if node:
        content_node = _best_content_node(search_text, node.get("content_nodes") or [])
        if content_node and content_node["score"] >= 0.18:
            return QualityAuditRevisionTarget(
                target_type="content_node",
                action="rewrite_subsection",
                title=content_node["title"],
                node_id=node["node_id"],
                version_id=node.get("version_id"),
                content_node_id=content_node["id"],
                reason=f"Quality audit found an omitted source fact that belongs to this generated subsection: {fact_text}",
                evidence=_fact_evidence(fact),
                requires_llm=True,
            )
        return QualityAuditRevisionTarget(
            target_type="chapter",
            action="regenerate" if node.get("version_id") else "remap_sources",
            title=node["title"],
            node_id=node["node_id"],
            version_id=node.get("version_id"),
            reason=f"Quality audit found an omitted source fact likely related to this chapter: {fact_text}",
            evidence=_fact_evidence(fact),
            requires_llm=True,
        )
    return QualityAuditRevisionTarget(
        target_type="outline",
        action="propose_outline_repair",
        title=fact_text or "Omitted source fact",
        reason="Quality audit found an omitted source fact, but no current outline node could be matched reliably.",
        evidence=_fact_evidence(fact),
        requires_user_confirmation=True,
    )


def _topic_target(topic: str, node_indexes: list[dict[str, Any]]) -> QualityAuditRevisionTarget:
    node = _best_node(topic, node_indexes)
    if node and node["score"] >= 0.2:
        return QualityAuditRevisionTarget(
            target_type="chapter",
            action="regenerate",
            title=node["title"],
            node_id=node["node_id"],
            version_id=node.get("version_id"),
            reason=f"Common construction-organization topic is missing or weakly covered: {topic}",
            evidence=[topic],
            requires_llm=bool(node.get("version_id")),
            requires_user_confirmation=not bool(node.get("version_id")),
        )
    return QualityAuditRevisionTarget(
        target_type="outline",
        action="propose_outline_repair",
        title=topic,
        reason="Quality audit found a missing common construction-organization topic.",
        evidence=[topic],
        requires_user_confirmation=True,
    )


def _node_index(node: dict[str, Any], workspace: dict[str, Any] | None) -> dict[str, Any]:
    workspace = workspace or {}
    selected_id = workspace.get("selected_version_id") or node.get("selected_version_id")
    selected = next((item for item in workspace.get("versions", []) if item.get("id") == selected_id), None)
    content_nodes = []
    if selected:
        content_tree = selected.get("content_tree") or {}
        content_nodes = list(_flatten_content_nodes(content_tree.get("nodes") or []))
    title = str(node.get("title") or node.get("node_id") or "")
    text_parts = [
        title,
        " ".join(str(item) for item in node.get("source_rules") or []),
        " ".join(str(item) for item in node.get("auto_fill") or []),
        " ".join(str(item) for item in node.get("manual_fill") or []),
        selected.get("markdown", "")[:2000] if selected else "",
    ]
    return {
        "node_id": str(node.get("node_id") or ""),
        "title": title,
        "version_id": selected_id,
        "text": " ".join(text_parts),
        "tokens": _tokens(" ".join(text_parts)),
        "content_nodes": content_nodes,
    }


def _flatten_content_nodes(nodes: list[dict[str, Any]]):
    for node in nodes:
        text = " ".join(
            [
                str(node.get("title") or ""),
                " ".join(str(item) for item in node.get("title_path") or []),
                str(node.get("body") or ""),
                str(node.get("markdown") or "")[:1000],
                " ".join(
                    " ".join(str(term) for term in link.get("matched_terms") or [])
                    for link in node.get("source_links") or []
                    if isinstance(link, dict)
                ),
            ]
        )
        yield {
            "id": str(node.get("id") or ""),
            "title": str(node.get("title") or node.get("id") or ""),
            "text": text,
            "tokens": _tokens(text),
        }
        yield from _flatten_content_nodes(node.get("children") or [])


def _best_node(search_text: str, node_indexes: list[dict[str, Any]]) -> dict[str, Any] | None:
    query = _tokens(search_text)
    if not query:
        return None
    scored = []
    for node in node_indexes:
        if not node.get("node_id"):
            continue
        score = _jaccard(query, node["tokens"])
        if score > 0:
            scored.append({**node, "score": score})
    if not scored:
        return None
    return max(scored, key=lambda item: item["score"])


def _best_content_node(search_text: str, content_nodes: list[dict[str, Any]]) -> dict[str, Any] | None:
    query = _tokens(search_text)
    if not query:
        return None
    scored = []
    for node in content_nodes:
        score = _jaccard(query, node["tokens"])
        if score > 0:
            scored.append({**node, "score": score})
    if not scored:
        return None
    return max(scored, key=lambda item: item["score"])


def _matched_toc_text(search_text: str, source_toc: list[dict[str, Any]]) -> str:
    query = _tokens(search_text)
    if not query:
        return ""
    scored = []
    for item in source_toc:
        text = " ".join([" ".join(item.get("title_path") or []), str(item.get("snippet") or "")])
        score = _jaccard(query, _tokens(text))
        if score > 0:
            scored.append((score, text))
    scored.sort(reverse=True, key=lambda item: item[0])
    return " ".join(text for _, text in scored[:3])


def _fact_evidence(fact: dict[str, Any]) -> list[str]:
    items = []
    for key in ("fact", "kind", "line", "context"):
        value = str(fact.get(key) or "").strip()
        if value:
            items.append(f"{key}: {value}")
    return items


def _toc_item_dict(item: Any) -> dict[str, Any]:
    if isinstance(item, dict):
        return item
    if hasattr(item, "model_dump"):
        return item.model_dump()
    if hasattr(item, "dict"):
        return item.dict()
    return {}


def _tokens(text: str) -> set[str]:
    normalized = str(text or "").lower()
    tokens = set(re.findall(r"[a-z0-9]+", normalized))
    tokens.update(re.findall(r"[\u4e00-\u9fff]{2,8}", normalized))
    for number in re.findall(r"\d+(?:\.\d+)?", normalized):
        tokens.add(number)
    return {token for token in tokens if len(token) >= 2}


def _jaccard(left: set[str], right: set[str]) -> float:
    if not left or not right:
        return 0.0
    overlap = len(left & right)
    if overlap == 0:
        return 0.0
    return overlap / max(1, min(len(left), len(right)))


def _dedupe_targets(targets: list[QualityAuditRevisionTarget]) -> list[QualityAuditRevisionTarget]:
    output: list[QualityAuditRevisionTarget] = []
    seen: set[tuple[str, str, str | None, str | None]] = set()
    for target in targets:
        key = (target.target_type, target.action, target.node_id or target.title, target.content_node_id)
        if key in seen:
            continue
        seen.add(key)
        output.append(target)
    return output


def _summary(targets: list[QualityAuditRevisionTarget], actionable: list[QualityAuditRevisionTarget]) -> str:
    if not targets:
        return "No project-level quality-audit revision target was found."
    llm_count = sum(1 for target in targets if target.requires_llm)
    user_count = sum(1 for target in targets if target.requires_user_confirmation)
    return f"{len(targets)} target(s), {len(actionable)} actionable, {llm_count} require LLM, {user_count} require user confirmation."
