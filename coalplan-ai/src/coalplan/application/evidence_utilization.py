from __future__ import annotations

import re
from collections.abc import Iterable

from coalplan.domain.generation_control import EvidenceUtilizationAudit, EvidenceUtilizationIssue, RequiredSourceFact
from coalplan.domain.outline import SourceEvidenceSpan
from coalplan.domain.templates import TemplateNode


NUMERIC_FACT_RE = re.compile(
    r"\d+(?:\.\d+)?(?:\s*(?:-|~|～|—|至)\s*\d+(?:\.\d+)?)?\s*(?:万)?\s*"
    r"(?:m³/min|m3/min|m3|m³|m2|m²|mm|cm|km|m|t|kg|MPa|kPa|kN|kW|MW|%|℃|°|"
    r"天|日|月|年|根|孔|台|套|人|班|次|处|座|条|项|分钟|小时|"
    r"米|毫米|厘米|千米|吨|立方米|平方米|公顷)",
    re.IGNORECASE,
)
DATE_RE = re.compile(r"\d{4}\s*年\s*\d{1,2}\s*月\s*\d{1,2}\s*日|\d{4}[-/.]\d{1,2}[-/.]\d{1,2}")
STANDARD_RE = re.compile(r"(?:GB|GB/T|DL/T|JGJ|SL|DZ/T|HJ|NB/T|TB|JTJ|JTG)\s*[-A-Z0-9./]+", re.IGNORECASE)
CHINESE_TERM_RE = re.compile(r"[\u4e00-\u9fff]{2,12}")

HIGH_VALUE_TERMS = {
    "工程量",
    "工期",
    "开工",
    "完工",
    "质量目标",
    "安全目标",
    "环保",
    "环境保护",
    "机械",
    "设备",
    "劳动力",
    "人员",
    "参数",
    "压力",
    "流量",
    "孔深",
    "孔径",
    "灌浆",
    "注水",
    "覆盖",
    "压实",
    "压实度",
    "验收",
    "试验",
    "检测",
    "监测",
    "应急",
    "施工方法",
    "施工工艺",
    "施工顺序",
    "平面布置",
    "临建",
}

MANUAL_HINTS = {
    "工程量": {"工程量", "数量", "m3", "m³", "m2", "m²", "根", "孔", "台", "套"},
    "工期": {"工期", "开工", "完工", "竣工", "计划", "天", "月", "日"},
    "质量": {"质量", "合格", "优良", "验收", "检测", "试验"},
    "安全": {"安全", "事故", "风险", "应急", "防护"},
    "环保": {"环保", "环境保护", "水土保持", "扬尘", "噪声", "废水"},
    "机械": {"机械", "设备", "台", "套", "配置"},
    "人员": {"人员", "劳动力", "班组", "人"},
    "参数": {"参数", "压力", "流量", "孔深", "孔径", "配比", "压实度"},
    "图纸": {"图纸", "设计", "坐标", "桩号", "断面"},
    "审批": {"审批", "批复", "报审", "许可"},
}

STOP_TERMS = {
    "本工程",
    "施工组织",
    "施工设计",
    "主要来源",
    "生成正文",
    "人工补充",
    "特殊备注",
    "需要人工",
    "源章节",
}

LOCATION_TITLE_TERMS = {"位置", "地理", "坐标", "边界", "范围", "地点"}
LOCATION_FACT_TERMS = {
    "位置",
    "地理",
    "坐标",
    "边界",
    "范围",
    "地点",
    "距离",
    "面积",
    "公顷",
    "m2",
    "m²",
    "深度",
    "长轴",
    "短轴",
    "拐点",
    "管辖",
}
STRONG_LOCATION_FACT_TERMS = LOCATION_FACT_TERMS - {"范围"}
TRAFFIC_TITLE_TERMS = {"交通", "道路", "铁路", "公路", "运输"}
TRAFFIC_FACT_TERMS = {"交通", "道路", "铁路", "公路", "国道", "县道", "运输", "通行", "连通"}
CRAFT_QUANTITY_TERMS = {
    "帷幕灌浆",
    "灌浆工程",
    "钻孔",
    "注水",
    "覆盖",
    "黄泥浆",
    "粉煤灰浆",
    "水泥",
    "施工内容",
}


def audit_evidence_utilization(
    *,
    node: TemplateNode,
    markdown: str,
    evidence: Iterable[SourceEvidenceSpan] | None,
    manual_items: Iterable[str] | None = None,
    required_fact_hints: Iterable[str] | None = None,
) -> EvidenceUtilizationAudit:
    spans = list(evidence or [])
    audit_spans = _applicable_spans_for_node(node, spans)
    body_markdown = _heading_block(markdown, "生成正文") or markdown
    manual_markdown = _heading_block(markdown, "人工补充需补充")
    normalized_body = _normalize(body_markdown)
    normalized_body_or_manual = _normalize("\n".join([body_markdown, manual_markdown]))
    used_ids: list[str] = []
    unused_high_value_ids: list[str] = []
    required_facts = [
        fact
        for fact in extract_required_source_facts(audit_spans)
        if _required_fact_applicable_to_node(node, fact)
    ]
    omitted_fact_ids = [
        fact.fact_id for fact in required_facts if not _required_fact_is_used(normalized_body, fact)
    ]
    feedback_required_facts = _clean_required_fact_hints(required_fact_hints or [])
    omitted_feedback_facts = [
        fact for fact in feedback_required_facts if not _required_hint_is_used(normalized_body_or_manual, fact)
    ]

    for span in audit_spans:
        tokens = _evidence_tokens(span)
        if _evidence_is_used(normalized_body, span, tokens):
            used_ids.append(span.evidence_id)
        elif _is_high_value(span, tokens):
            unused_high_value_ids.append(span.evidence_id)

    manual_supported = _manual_items_with_source_support(
        markdown=markdown,
        items=list(manual_items if manual_items is not None else node.manual_fill),
        evidence=spans,
    )
    coverage_ratio = round(len(used_ids) / len(audit_spans), 3) if audit_spans else None

    issues: list[EvidenceUtilizationIssue] = []
    if omitted_fact_ids:
        omitted = [fact for fact in required_facts if fact.fact_id in omitted_fact_ids]
        issues.append(
            EvidenceUtilizationIssue(
                code="omitted_required_source_facts",
                message="Generated body omitted high-value facts that were present in mapped source evidence.",
                severity="warning",
                evidence_ids=sorted({fact.evidence_id for fact in omitted}),
                terms=[fact.text for fact in omitted[:12]],
                suggested_action="regenerate",
            )
        )
    if omitted_feedback_facts:
        issues.append(
            EvidenceUtilizationIssue(
                code="omitted_feedback_required_facts",
                message="Generated chapter omitted source facts required by previous quality feedback.",
                severity="warning",
                terms=omitted_feedback_facts[:12],
                suggested_action="regenerate",
            )
        )
    if manual_supported:
        issues.append(
            EvidenceUtilizationIssue(
                code="manual_item_has_source_support",
                message="Some manual-fill placeholders appear to be supported by mapped source evidence.",
                terms=manual_supported,
                evidence_ids=_supporting_evidence_ids(manual_supported, spans),
                suggested_action="regenerate",
            )
        )
    if audit_spans and coverage_ratio is not None and coverage_ratio < 0.35 and len(unused_high_value_ids) >= 2:
        issues.append(
            EvidenceUtilizationIssue(
                code="low_evidence_utilization",
                message="Generated chapter used too little mapped high-value source evidence.",
                evidence_ids=unused_high_value_ids[:8],
                suggested_action="regenerate",
            )
        )

    return EvidenceUtilizationAudit(
        node_id=node.id,
        title=node.title,
        evidence_count=len(spans),
        required_source_facts=required_facts,
        omitted_required_fact_ids=omitted_fact_ids,
        feedback_required_fact_hints=feedback_required_facts,
        omitted_feedback_fact_hints=omitted_feedback_facts,
        used_evidence_ids=used_ids,
        unused_high_value_evidence_ids=unused_high_value_ids,
        coverage_ratio=coverage_ratio,
        manual_items_with_source_support=manual_supported,
        issues=issues,
    )


def extract_required_source_facts(
    evidence: Iterable[SourceEvidenceSpan],
    *,
    max_facts: int = 30,
    max_per_evidence: int = 4,
) -> list[RequiredSourceFact]:
    facts: list[RequiredSourceFact] = []
    seen: set[str] = set()
    for span in evidence:
        per_span = 0
        for sentence in _fact_sentences(span):
            tokens = _fact_tokens(sentence)
            if not tokens:
                continue
            key = _normalize(" ".join(tokens[:4]))
            if not key or key in seen:
                continue
            seen.add(key)
            fact_type = _fact_type(sentence)
            facts.append(
                RequiredSourceFact(
                    fact_id=f"{span.evidence_id}:fact_{per_span + 1}",
                    evidence_id=span.evidence_id,
                    section_id=span.section_id,
                    fact_type=fact_type,
                    text=_trim_fact(sentence),
                    tokens=tokens[:8],
                    reason=_fact_reason(fact_type),
                )
            )
            per_span += 1
            if per_span >= max_per_evidence or len(facts) >= max_facts:
                break
        if len(facts) >= max_facts:
            break
    return facts


def _applicable_spans_for_node(node: TemplateNode, spans: list[SourceEvidenceSpan]) -> list[SourceEvidenceSpan]:
    if not spans:
        return []
    applicable = [span for span in spans if _span_applicable_to_node(node, span)]
    return applicable or spans


def _span_applicable_to_node(node: TemplateNode, span: SourceEvidenceSpan) -> bool:
    node_text = _node_context_text(node)
    evidence_text = _span_context_text(span)
    node_title = node.title
    if _contains_any(node_title, LOCATION_TITLE_TERMS):
        if _contains_any(evidence_text, CRAFT_QUANTITY_TERMS):
            return _contains_any(f"{span.summary}\n{span.quote}", STRONG_LOCATION_FACT_TERMS)
        return _contains_any(evidence_text, LOCATION_FACT_TERMS)
    if _contains_any(node_title, TRAFFIC_TITLE_TERMS):
        return _contains_any(evidence_text, TRAFFIC_FACT_TERMS)
    node_terms = _content_terms(node_text)
    evidence_terms = _content_terms(evidence_text)
    if not node_terms:
        return True
    return bool(node_terms.intersection(evidence_terms))


def _required_fact_applicable_to_node(node: TemplateNode, fact: RequiredSourceFact) -> bool:
    title = node.title
    text = fact.text
    if _contains_any(title, LOCATION_TITLE_TERMS):
        return _contains_any(text, LOCATION_FACT_TERMS) or not _contains_any(text, CRAFT_QUANTITY_TERMS)
    if _contains_any(title, TRAFFIC_TITLE_TERMS):
        return _contains_any(text, TRAFFIC_FACT_TERMS)
    if "工程量" in title or "进度" in title:
        return True
    if fact.fact_type in {"quantity", "parameter", "method"} and _contains_any(text, CRAFT_QUANTITY_TERMS):
        return _contains_any(_node_context_text(node), CRAFT_QUANTITY_TERMS)
    return True


def _node_context_text(node: TemplateNode) -> str:
    return "\n".join(
        [
            node.title,
            "\n".join(node.source_rules),
            "\n".join(node.auto_fill),
            "\n".join(node.manual_fill),
            "\n".join(node.special_notes),
        ]
    )


def _span_context_text(span: SourceEvidenceSpan) -> str:
    return "\n".join(
        [
            " > ".join(span.title_path),
            span.summary or "",
            span.quote or "",
            " ".join(span.matched_terms or []),
        ]
    )


def _contains_any(text: str, terms: set[str]) -> bool:
    return any(term in text for term in terms)


def _evidence_is_used(normalized_markdown: str, span: SourceEvidenceSpan, tokens: set[str]) -> bool:
    if span.evidence_id and span.evidence_id in normalized_markdown and _token_hits(normalized_markdown, tokens) >= 1:
        return True
    if span.section_id and span.section_id in normalized_markdown and _token_hits(normalized_markdown, tokens) >= 1:
        return True
    numeric_tokens = {token for token in tokens if any(char.isdigit() for char in token)}
    if numeric_tokens and _token_hits(normalized_markdown, numeric_tokens) >= 1:
        return True
    return _token_hits(normalized_markdown, tokens) >= 3


def _required_fact_is_used(normalized_body: str, fact: RequiredSourceFact) -> bool:
    if not fact.tokens:
        return False
    numeric_tokens = [token for token in fact.tokens if any(char.isdigit() for char in token)]
    if numeric_tokens:
        return any(_normalize(token) in normalized_body for token in numeric_tokens)
    normalized_tokens = {_normalize(token) for token in fact.tokens}
    return _token_hits(normalized_body, normalized_tokens) >= min(2, len(normalized_tokens))


def _required_hint_is_used(normalized_markdown: str, hint: str) -> bool:
    tokens = _hint_tokens(hint)
    if not tokens:
        return _normalize(hint) in normalized_markdown
    numeric_tokens = [token for token in tokens if any(char.isdigit() for char in token)]
    if numeric_tokens:
        return any(_normalize(token) in normalized_markdown for token in numeric_tokens)
    normalized_tokens = {_normalize(token) for token in tokens}
    return _token_hits(normalized_markdown, normalized_tokens) >= min(2, len(normalized_tokens))


def _clean_required_fact_hints(hints: Iterable[str]) -> list[str]:
    output: list[str] = []
    for hint in hints:
        cleaned = re.sub(r"\s*\[(?:not_prompted|prompted_but_omitted|absorbed_in_response)\s*->\s*[^]]+\]\s*$", "", str(hint)).strip()
        cleaned = cleaned.strip("- ")
        if cleaned and cleaned not in output:
            output.append(cleaned)
    return output


def _hint_tokens(text: str) -> list[str]:
    ordered: list[str] = []
    for regex in (DATE_RE, STANDARD_RE, NUMERIC_FACT_RE):
        for token in regex.findall(text):
            if isinstance(token, tuple):
                token = "".join(token)
            token = token.strip()
            if token and token not in ordered:
                ordered.append(token)
    if ordered:
        return ordered
    for term in _content_terms(text):
        if term not in ordered:
            ordered.append(term)
    return ordered[:8]


def _manual_items_with_source_support(
    *,
    markdown: str,
    items: list[str],
    evidence: list[SourceEvidenceSpan],
) -> list[str]:
    manual_block = _heading_block(markdown, "人工补充需补充")
    if not manual_block:
        return []
    supported: list[str] = []
    evidence_text = _normalize("\n".join(f"{span.summary}\n{span.quote}" for span in evidence))
    for item in items:
        item_terms = _manual_support_terms(item)
        if not item_terms:
            continue
        explicit_placeholder = "【需人工补充" in manual_block
        item_is_placeholder = item in manual_block or (explicit_placeholder and any(term in manual_block for term in item_terms))
        source_has_support = any(_normalize(term) in evidence_text for term in item_terms)
        if item_is_placeholder and source_has_support:
            supported.append(item)
    return supported


def _supporting_evidence_ids(items: list[str], evidence: list[SourceEvidenceSpan]) -> list[str]:
    ids: list[str] = []
    for item in items:
        item_terms = {_normalize(term) for term in _manual_support_terms(item)}
        for span in evidence:
            text = _normalize(f"{span.summary}\n{span.quote}")
            if any(term and term in text for term in item_terms):
                ids.append(span.evidence_id)
    return sorted(set(ids))


def _manual_support_terms(item: str) -> set[str]:
    terms = _content_terms(item)
    for key, hints in MANUAL_HINTS.items():
        if key in item:
            terms.update(hints)
    return terms


def _evidence_tokens(span: SourceEvidenceSpan) -> set[str]:
    text = "\n".join([span.summary or "", span.quote or "", " ".join(span.matched_terms or [])])
    tokens = set(NUMERIC_FACT_RE.findall(text))
    tokens.update(DATE_RE.findall(text))
    tokens.update(STANDARD_RE.findall(text))
    tokens.update(_content_terms(text))
    return {_normalize(token) for token in tokens if _normalize(token)}


def _content_terms(text: str) -> set[str]:
    terms = {term for term in CHINESE_TERM_RE.findall(text) if term not in STOP_TERMS}
    return {term for term in terms if len(term) >= 2}


def _token_hits(normalized_text: str, tokens: set[str]) -> int:
    return sum(1 for token in tokens if token and token in normalized_text)


def _is_high_value(span: SourceEvidenceSpan, tokens: set[str]) -> bool:
    text = f"{span.summary}\n{span.quote}\n{' '.join(span.matched_terms)}"
    if any(any(char.isdigit() for char in token) for token in tokens):
        return True
    return any(term in text for term in HIGH_VALUE_TERMS)


def _normalize(text: str) -> str:
    return re.sub(r"\s+", "", text or "")


def _heading_block(markdown: str, heading: str) -> str:
    match = re.search(rf"^##\s+{re.escape(heading)}\s*$([\s\S]*?)(?=^##\s+|\Z)", markdown, flags=re.M)
    return match.group(1) if match else ""


def _fact_sentences(span: SourceEvidenceSpan) -> list[str]:
    text = "\n".join(part for part in [span.summary, span.quote] if part).replace("\r", "\n")
    raw_parts = re.split(r"(?<=[。；;.!?])\s+|\n+", text)
    sentences: list[str] = []
    for part in raw_parts:
        cleaned = re.sub(r"\s+", " ", part).strip(" -，,。；;")
        if not cleaned:
            continue
        if len(cleaned) > 220:
            sentences.extend(_split_long_fact_sentence(cleaned))
        else:
            sentences.append(cleaned)
    return sentences


def _split_long_fact_sentence(text: str) -> list[str]:
    parts = re.split(r"(?<=[，,；;])\s*", text)
    output: list[str] = []
    buffer = ""
    for part in parts:
        if not part:
            continue
        if buffer and len(buffer) + len(part) > 180:
            output.append(buffer.strip(" ，,；;"))
            buffer = ""
        buffer += part
    if buffer.strip():
        output.append(buffer.strip(" ，,；;"))
    return output or [text[:180]]


def _fact_tokens(text: str) -> list[str]:
    ordered: list[str] = []
    for regex in (DATE_RE, STANDARD_RE, NUMERIC_FACT_RE):
        for token in regex.findall(text):
            if isinstance(token, tuple):
                token = "".join(token)
            token = token.strip()
            if token and token not in ordered:
                ordered.append(token)
    return ordered


def _fact_type(text: str) -> str:
    if DATE_RE.search(text):
        return "date"
    if STANDARD_RE.search(text):
        return "standard"
    if any(term in text for term in ("压力", "流量", "孔深", "孔径", "配比", "压实度", "温度", "间距", "厚度")):
        return "parameter"
    if any(term in text for term in ("工程量", "数量", "方量", "钻孔", "灌浆", "注水", "覆盖", "回填")):
        return "quantity"
    if any(term in text for term in ("施工", "工艺", "顺序", "流程", "方法")):
        return "method"
    return "other"


def _fact_reason(fact_type: str) -> str:
    return {
        "quantity": "工程量或数量类事实，生成正文应优先保留。",
        "parameter": "施工参数或控制指标，生成正文不得概括省略或改写为未核验参数。",
        "date": "工期/日期类事实，必须来自来源或保留人工补充占位。",
        "standard": "规范标准类事实，引用时应保持编号准确。",
        "method": "工艺流程类事实，应进入对应施工方法正文。",
    }.get(fact_type, "来源中的高价值事实，生成时应尽量吸收。")


def _trim_fact(text: str) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    return text if len(text) <= 180 else text[:177].rstrip() + "..."
