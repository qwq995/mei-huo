from __future__ import annotations

import re
from dataclasses import dataclass, field

from coalplan.domain.documents import MarkdownSection, stable_id
from coalplan.domain.generation_context import WritingUnitSpec
from coalplan.domain.generation_control import ChapterGenerationPolicy
from coalplan.domain.outline import SourceEvidenceSpan
from coalplan.domain.reference_library import AtomRetrievalResult
from coalplan.domain.templates import TemplateNode

from .chapter_writing_guidance import guidance_for_node


MAX_WRITING_UNITS = 4
MIN_UNIT_TARGET = 350
MAX_UNIT_TARGET = 850
TECHNICAL_FAMILIES: dict[str, tuple[str, ...]] = {
    "blasting": ("爆破", "装药", "起爆", "炮孔", "雷管", "炸药", "火工"),
    "excavation": ("开挖", "洞挖", "明挖", "出渣", "超欠挖"),
    "support": ("支护", "锚杆", "钢架", "小导管", "喷射混凝土", "锚喷"),
    "concrete": ("衬砌", "浇筑", "振捣", "入仓", "模板", "钢筋", "养护", "泌水"),
    "grouting": ("灌浆", "注浆", "制浆", "帷幕", "固结", "回填灌浆"),
    "water_diversion": ("导流", "围堰", "截流", "度汛", "排水"),
    "earth_rock_fill": ("填筑", "碾压", "堆石", "坝体"),
    "metal_structure": ("金属结构", "闸门", "启闭机", "埋件", "焊接"),
}


@dataclass
class ChapterWritingUnitContext:
    spec: WritingUnitSpec
    selected_source_sections: list[MarkdownSection] = field(default_factory=list)
    evidence_spans: list[SourceEvidenceSpan] = field(default_factory=list)
    reference_atom_results: list[AtomRetrievalResult] = field(default_factory=list)


def plan_chapter_writing_units(
    *,
    node: TemplateNode,
    policy: ChapterGenerationPolicy | None,
) -> list[WritingUnitSpec]:
    guidance = guidance_for_node(node)
    target = node.target_word_count or (policy.target_word_count if policy else None) or 700
    policy_topics = list(
        dict.fromkeys(
            [
                *((policy.source_subtopics if policy else []) or []),
                *((policy.required_subtopics if policy else []) or []),
            ]
        )
    )
    hints = [
        str(item).strip()
        for item in (node.chapter_summary.get("writing_unit_hints", []) if node.chapter_summary else [])
        if str(item).strip()
    ]
    topics = _dedupe_topics([*policy_topics, *hints, *guidance.structure])

    should_split = bool(
        target > 900
        or (policy and (policy.split_required or policy.detail_level in {"deep", "subsection_required"}))
        or len(policy_topics) >= 3
    )
    if not should_split:
        return [
            _make_unit(
                node=node,
                title=node.title,
                topics=topics[:6] or [node.title],
                target=target,
                sequence=1,
                pattern_key=guidance.pattern_key,
            )
        ]

    buckets = _topic_buckets(topics)
    selected = [(index, items) for index, items in enumerate(buckets) if items][:MAX_WRITING_UNITS]
    if len(selected) < 2:
        midpoint = max(1, min(len(topics) - 1, len(topics) // 2))
        selected = (
            [(0, topics[:midpoint]), (1, topics[midpoint:])]
            if len(topics) > 1
            else [(1, topics)]
        )
    selected = [(bucket, items) for bucket, items in selected if items]
    per_unit = max(MIN_UNIT_TARGET, min(MAX_UNIT_TARGET, int(target / max(1, len(selected)))))
    units: list[WritingUnitSpec] = []
    for index, (bucket, unit_topics) in enumerate(selected, start=1):
        units.append(
            _make_unit(
                node=node,
                title=_unit_title(bucket, unit_topics, index),
                topics=unit_topics,
                target=per_unit,
                sequence=index,
                pattern_key=guidance.pattern_key,
            )
        )
    return units


def select_sections_for_writing_unit(
    sections: list[MarkdownSection],
    spec: WritingUnitSpec,
    *,
    limit: int = 5,
) -> list[MarkdownSection]:
    terms = _normalized_terms([*spec.evidence_terms, *spec.writing_topics, spec.title])
    query_families = _technical_families(" ".join([spec.objective, *spec.writing_topics]))
    scored: list[tuple[int, int, MarkdownSection]] = []
    for index, section in enumerate(sections):
        raw_text = " ".join(section.title_path) + " " + section.content[:2400]
        if not _technical_compatible(query_families, raw_text):
            continue
        text = _normalize(raw_text)
        score = sum(3 if term in _normalize(" ".join(section.title_path)) else 1 for term in terms if term in text)
        scored.append((score, -index, section))
    matched = [section for score, _, section in sorted(scored, key=lambda item: (-item[0], -item[1])) if score > 0]
    if matched:
        return matched[:limit]
    return sections[: min(limit, len(sections))]


def select_evidence_for_writing_unit(
    evidence: list[SourceEvidenceSpan],
    spec: WritingUnitSpec,
    *,
    limit: int = 8,
) -> list[SourceEvidenceSpan]:
    terms = _normalized_terms([*spec.evidence_terms, *spec.writing_topics, spec.title])
    query_families = _technical_families(" ".join([spec.objective, *spec.writing_topics]))
    scored: list[tuple[int, int, SourceEvidenceSpan]] = []
    for index, span in enumerate(evidence):
        raw_text = (
            " ".join(span.title_path)
            + " "
            + span.summary
            + " "
            + span.quote[:1800]
            + " "
            + " ".join(span.matched_terms)
        )
        if not _technical_compatible(query_families, raw_text):
            continue
        text = _normalize(raw_text)
        score = sum(1 for term in terms if term in text)
        scored.append((score, -index, span))
    matched = [span for score, _, span in sorted(scored, key=lambda item: (-item[0], -item[1])) if score > 0]
    if matched:
        return matched[:limit]
    return evidence[: min(limit, len(evidence))]


def flatten_reference_atom_results(contexts: list[ChapterWritingUnitContext]) -> list[AtomRetrievalResult]:
    output: list[AtomRetrievalResult] = []
    seen: set[str] = set()
    for context in contexts:
        for result in context.reference_atom_results:
            if result.atom_id in seen:
                continue
            seen.add(result.atom_id)
            output.append(result)
    return output


def compact_completed_unit(markdown: str, *, limit: int = 700) -> str:
    text = re.sub(r"^#{1,6}\s+.*$", "", markdown, flags=re.M)
    text = re.sub(r"\s+", " ", text).strip()
    return text if len(text) <= limit else text[:limit].rstrip() + "…"


def _make_unit(
    *,
    node: TemplateNode,
    title: str,
    topics: list[str],
    target: int,
    sequence: int,
    pattern_key: str,
) -> WritingUnitSpec:
    content_functions = _content_functions(topics, pattern_key)
    return WritingUnitSpec(
        unit_id=stable_id("writeunit", node.id, str(sequence), title),
        title=title,
        objective=f"完成“{node.title}”中与“{'、'.join(topics[:4])}”相关的可直接入稿内容。",
        target_word_count=max(MIN_UNIT_TARGET, min(MAX_UNIT_TARGET, int(target))),
        writing_topics=topics[:8],
        evidence_terms=_evidence_terms(topics),
        content_functions=content_functions,
        sequence=sequence,
    )


def _topic_buckets(topics: list[str]) -> list[list[str]]:
    buckets: list[list[str]] = [[], [], [], []]
    for topic in topics:
        if _contains_any(topic, ("安全", "环保", "文明", "应急", "风险", "职业健康")):
            target = 3
        elif _contains_any(topic, ("质量", "检查", "检验", "试验", "验收", "记录", "缺陷")):
            target = 2
        elif _contains_any(topic, ("流程", "方法", "工艺", "参数", "控制", "施工", "作业", "安装", "开挖", "浇筑", "灌浆")):
            target = 1
        else:
            target = 0
        if topic not in buckets[target]:
            buckets[target].append(topic)
    return buckets


def _unit_title(bucket: int, topics: list[str], index: int) -> str:
    labels = {
        0: "适用范围、施工准备与资源条件",
        1: "工艺流程、施工方法与参数控制",
        2: "质量检查、试验验收与记录",
        3: "安全环保、风险防控与异常处置",
    }
    return labels.get(bucket) or (topics[0] if topics else f"写作单元{index}")


def _dedupe_topics(items: list[str]) -> list[str]:
    output: list[str] = []
    normalized: list[str] = []
    for item in items:
        value = str(item or "").strip()
        value = re.sub(r"^(?:[A-Za-z]|[（(]?\d+[）)])\s*[).、]?\s*", "", value)
        value = re.sub(r"^\d+(?:\.\d+){0,5}\s*", "", value)
        value = value.strip("。； ")
        key = _normalize(value)
        if not key or any(key == seen or (len(key) >= 4 and key in seen) for seen in normalized):
            continue
        output.append(value)
        normalized.append(key)
    return output[:16]


def _evidence_terms(topics: list[str]) -> list[str]:
    terms: list[str] = []
    for topic in topics:
        for token in re.findall(r"[\u4e00-\u9fff]{2,8}|[A-Za-z]{2,}", topic):
            if token not in terms:
                terms.append(token)
    return terms[:16]


def _content_functions(topics: list[str], pattern_key: str) -> list[str]:
    text = " ".join(topics)
    functions: list[str] = []
    for label, terms in (
        ("适用条件", ("范围", "对象", "条件")),
        ("工艺流程", ("流程", "顺序", "方法", "工艺")),
        ("资源配置", ("人员", "机械", "材料", "资源")),
        ("控制参数", ("参数", "控制", "压力", "流量", "厚度")),
        ("质量验收", ("质量", "检查", "试验", "验收")),
        ("安全环保", ("安全", "环保", "文明", "风险")),
        ("异常处置", ("异常", "应急", "缺陷", "处置")),
    ):
        if any(term in text for term in terms):
            functions.append(label)
    if not functions:
        functions.append("专业展开" if pattern_key != "general" else "章节正文")
    return functions


def _normalized_terms(items: list[str]) -> list[str]:
    return list(dict.fromkeys(term for item in items for term in _evidence_terms([item]) if len(term) >= 2))


def _normalize(value: str) -> str:
    return re.sub(r"\s+", "", value or "").lower()


def _contains_any(value: str, terms: tuple[str, ...]) -> bool:
    return any(term in value for term in terms)


def _technical_families(text: str) -> set[str]:
    return {
        family
        for family, terms in TECHNICAL_FAMILIES.items()
        if any(term in (text or "") for term in terms)
    }


def _technical_compatible(query_families: set[str], text: str) -> bool:
    if not query_families:
        return True
    candidate_families = _technical_families(text)
    return not candidate_families or bool(query_families & candidate_families)
