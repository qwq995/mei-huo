from __future__ import annotations

import json
import re

from coalplan.application.organization_pattern_audit import audit_pattern_organization
from coalplan.application.serialization import dump_model


def audit_version_generation_metadata(version: dict | None) -> dict:
    """Audit whether selected local writing patterns are traceable and sufficiently represented."""

    if not version:
        return _missing_result()
    metadata = version.get("generation_metadata")
    if not metadata:
        return _missing_result()

    pattern_keys = list(dict.fromkeys(metadata.get("selected_pattern_keys") or []))
    markdown = str(version.get("markdown") or "")
    applicability = "\n".join(
        [
            markdown,
            json.dumps(metadata, ensure_ascii=False, sort_keys=True),
        ]
    )
    audits = [
        audit_pattern_organization(markdown, pattern_key=key, applicability_text=applicability)
        for key in pattern_keys[:5]
    ]
    prompt_card_audits = _audit_prompt_cards(markdown, _metadata_prompt_cards(metadata))
    actionable = [audit for audit in audits if audit.suggested_action != "accept"]
    actionable_cards = [audit for audit in prompt_card_audits if audit.get("suggested_action") != "accept"]
    requires_llm = [audit for audit in actionable if audit.suggested_action in {"regenerate"}]
    requires_llm.extend(
        audit
        for audit in actionable_cards
        if audit.get("suggested_action") in {"regenerate", "expand_subsections"}
    )
    requires_user = [
        audit
        for audit in actionable
        if audit.suggested_action in {"repair_outline_coverage", "expand_subsections", "request_human_input"}
    ]
    requires_user.extend(
        audit
        for audit in actionable_cards
        if audit.get("suggested_action") in {"expand_subsections", "request_human_input"}
    )
    status = "passed" if not actionable and not actionable_cards else "warning"
    return {
        "status": status,
        "issues": [_audit_issue(audit) for audit in actionable] + [_prompt_card_issue(audit) for audit in actionable_cards],
        "next_actions": _next_actions(actionable) + _prompt_card_next_actions(actionable_cards),
        "metrics": {
            "selected_pattern_count": len(pattern_keys),
            "audited_pattern_count": len(audits),
            "prompt_card_count": len(prompt_card_audits),
            "prompt_card_actionable_count": len(actionable_cards),
            "actionable_count": len(actionable) + len(actionable_cards),
            "requires_llm_count": len(requires_llm),
            "requires_user_confirmation_count": len(requires_user),
        },
        "pattern_audits": [dump_model(audit) for audit in audits],
        "prompt_card_audits": prompt_card_audits,
    }


def _missing_result() -> dict:
    return {
        "status": "warning",
        "issues": ["Selected version lacks generation metadata; local writing-pattern use is not traceable."],
        "next_actions": ["Regenerate this chapter or save a version with generation metadata before final merge."],
        "metrics": {
            "selected_pattern_count": 0,
            "audited_pattern_count": 0,
            "actionable_count": 0,
            "requires_llm_count": 0,
            "requires_user_confirmation_count": 1,
            "missing_metadata": 1,
        },
        "pattern_audits": [],
    }


def _audit_issue(audit) -> str:
    missing = "；".join(audit.missing_points[:4]) if audit.missing_points else "-"
    return (
        f"Pattern `{audit.pattern_key}` suggests `{audit.suggested_action}`; "
        f"coverage={audit.coverage_ratio if audit.coverage_ratio is not None else '-'}; missing={missing}."
    )


def _next_actions(audits) -> list[str]:
    actions: list[str] = []
    for audit in audits:
        if audit.suggested_action == "repair_outline_coverage":
            actions.append("Create or apply an outline proposal before regenerating this chapter.")
        elif audit.suggested_action == "expand_subsections":
            actions.append("Split this dense chapter into source-derived subsections before regenerating.")
        elif audit.suggested_action == "regenerate":
            actions.append("Regenerate this chapter with the selected writing pattern and mapped evidence.")
        elif audit.suggested_action == "request_human_input":
            actions.append("Collect human supplements for missing drawings, parameters, approvals, or site data.")
    return list(dict.fromkeys(actions))


def _metadata_prompt_cards(metadata: dict) -> list[dict]:
    policy = metadata.get("generation_policy") if isinstance(metadata, dict) else None
    if not isinstance(policy, dict):
        return []
    cards = policy.get("pattern_prompt_cards") or []
    return [card for card in cards if isinstance(card, dict)]


def _audit_prompt_cards(markdown: str, cards: list[dict]) -> list[dict]:
    body = _generated_body(markdown)
    normalized = _normalize_text(body)
    output: list[dict] = []
    for card in cards[:5]:
        requirements = _card_audit_requirements(card)
        covered: list[str] = []
        missing: list[str] = []
        for item in requirements:
            tokens = _requirement_tokens(item)
            if not tokens:
                continue
            if any(token in normalized for token in tokens):
                covered.append(item)
            else:
                missing.append(item)
        total = len(covered) + len(missing)
        coverage = round(len(covered) / total, 4) if total else None
        suggested = _prompt_card_suggested_action(card, missing, coverage)
        output.append(
            {
                "pattern_key": card.get("pattern_key"),
                "coverage_ratio": coverage,
                "covered_requirements": covered,
                "missing_requirements": missing,
                "source_mapping_requirements": [str(item) for item in card.get("source_mapping_requirements") or []][:8],
                "human_only_items": [str(item) for item in card.get("human_only_items") or []][:8],
                "revision_checks": [str(item) for item in card.get("revision_checks") or []][:8],
                "suggested_action": suggested,
            }
        )
    return output


def _card_audit_requirements(card: dict) -> list[str]:
    values: list[str] = []
    for key in ("generation_moves", "detail_design_rules"):
        for item in card.get(key) or []:
            text = str(item).strip()
            if not text or text.lower().startswith("use these moves") or text.lower().startswith("allocate target word count"):
                continue
            values.append(text)
    return list(dict.fromkeys(values))[:16]


def _requirement_tokens(text: str) -> list[str]:
    normalized = _normalize_text(text)
    if not normalized:
        return []
    tokens = []
    tokens.extend(match.group(0) for match in re.finditer(r"[a-z0-9][a-z0-9_-]{3,}", normalized))
    tokens.extend(match.group(0) for match in re.finditer(r"[\u4e00-\u9fff]{2,}", normalized))
    for phrase in _CHINESE_AUDIT_PHRASES:
        normalized_phrase = _normalize_text(phrase)
        if normalized_phrase and normalized_phrase in normalized:
            tokens.append(normalized_phrase)
    if not tokens and len(normalized) >= 4:
        tokens.append(normalized)
    return list(dict.fromkeys(tokens))[:20]


_CHINESE_AUDIT_PHRASES = [
    "施工准备",
    "测量放样",
    "工艺流程",
    "过程控制",
    "检查验收",
    "人员",
    "设备",
    "材料",
    "作业条件",
    "特殊情况处理",
    "成品保护",
    "记录资料",
    "质量目标",
    "保证体系",
    "责任分工",
    "三检制",
    "验收整改",
    "原材料",
    "工序",
    "试验检测",
    "隐蔽验收",
    "安全目标",
    "危险源",
    "技术交底",
    "现场检查",
    "应急响应",
    "消防",
    "防汛",
    "临电",
    "机械",
    "起重",
    "爆破",
    "扬尘",
    "噪声",
    "废水",
    "固废",
    "水土保持",
    "文明施工",
    "劳动力",
    "机械设备",
    "材料供应",
    "资金保障",
    "总体工期",
    "阶段划分",
    "关键线路",
    "节点控制",
    "纠偏措施",
]


def _prompt_card_suggested_action(card: dict, missing: list[str], coverage: float | None) -> str:
    if coverage is None or not missing:
        return "accept"
    pattern_key = str(card.get("pattern_key") or "")
    missing_text = _normalize_text("\n".join(missing))
    human_items = [str(item) for item in card.get("human_only_items") or []]
    if human_items and any(_normalize_text(item) in missing_text for item in human_items if _normalize_text(item)):
        return "request_human_input"
    if pattern_key == "craft" and coverage < 0.7 and _has_any_phrase(
        missing_text,
        ["施工准备", "测量放样", "工艺流程", "过程控制", "检查验收", "人员", "设备", "材料", "作业条件"],
    ):
        return "expand_subsections"
    if pattern_key in {"quality", "safety", "environment", "schedule_resource"} and coverage < 0.55:
        return "regenerate"
    return "regenerate" if coverage < 0.4 else "accept"


def _has_any_phrase(normalized_text: str, phrases: list[str]) -> bool:
    return any(_normalize_text(phrase) in normalized_text for phrase in phrases)


def _normalize_text(text: str) -> str:
    return re.sub(r"[\s#`*_\-:：;；,，.。()\[\]{}]+", "", text or "").lower()


def _generated_body(markdown: str) -> str:
    text = markdown or ""
    match = re.search(r"^##\s+生成正文\s*$|^##\s+鐢熸垚姝ｆ枃\s*$", text, flags=re.M)
    if not match:
        return text
    start = match.end()
    next_heading = re.search(r"^##\s+", text[start:], flags=re.M)
    end = start + next_heading.start() if next_heading else len(text)
    return text[start:end].strip()


def _prompt_card_issue(audit: dict) -> str:
    missing = "；".join(str(item) for item in (audit.get("missing_requirements") or [])[:4]) or "-"
    return (
        f"Pattern prompt card `{audit.get('pattern_key')}` suggests `{audit.get('suggested_action')}`; "
        f"coverage={audit.get('coverage_ratio') if audit.get('coverage_ratio') is not None else '-'}; missing={missing}."
    )


def _prompt_card_next_actions(audits: list[dict]) -> list[str]:
    if not audits:
        return []
    actions: list[str] = []
    for audit in audits:
        action = audit.get("suggested_action")
        if action == "expand_subsections":
            actions.append(
                "Split or expand this chapter using the missing local writing-pattern cue groups before regenerating with mapped evidence."
            )
        elif action == "request_human_input":
            actions.append("Collect human supplements for missing pattern items that cannot be source-backed.")
        elif action == "regenerate":
            actions.append(
                "Regenerate this chapter with the persisted pattern_prompt_cards, mapped evidence, and missing card requirements in the revision context."
            )
    return list(dict.fromkeys(actions))
