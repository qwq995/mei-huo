from __future__ import annotations

import re

from coalplan.application.serialization import dump_model, to_json_text
from coalplan.domain.documents import MarkdownSection, SourceTocItem
from coalplan.domain.generation import SourceMatch
from coalplan.domain.outline import SourceMappingMatch, SourceMappingResult
from coalplan.domain.profile import ProjectProfile
from coalplan.domain.templates import TemplateNode
from coalplan.infrastructure.validation.json_contract import SourceMappingValidator
from coalplan.ports.llm import StructuredLLMClient
from coalplan.ports.repository import ArtifactRepository

from .source_evidence import attach_evidence_ids, build_source_evidence


_HIGH_VALUE_DETAIL_TERMS = (
    "气温",
    "降水",
    "水文",
    "地质",
    "工程量",
    "机械",
    "设备",
    "工期",
    "进度",
    "质量",
    "安全",
    "标准",
    "规范",
    "参数",
    "压力",
    "流量",
    "压实",
    "厚度",
    "灌浆",
    "注水",
    "覆盖",
    "交通",
    "临时",
    "供水",
    "供电",
    "监测",
    "验收",
)


def map_chapter_sources(
    *,
    project_id: str,
    profile: ProjectProfile,
    toc_items: list[SourceTocItem],
    sections: list[MarkdownSection],
    node: TemplateNode,
    llm: StructuredLLMClient,
    artifacts: ArtifactRepository,
    max_matches: int = 8,
    max_evidence_spans: int = 14,
    mapping_context: str = "",
) -> tuple[SourceMappingResult, list[MarkdownSection], list[SourceMatch]]:
    try:
        data = llm.complete_json(
            build_source_mapping_prompt(
                profile=profile,
                toc_items=toc_items,
                node=node,
                max_matches=max_matches,
                mapping_context=mapping_context,
            ),
            schema_name="SourceMappingResult",
        )
        mapping = SourceMappingResult(**data)
    except Exception as exc:
        mapping = _fallback_mapping(
            node=node,
            toc_items=toc_items,
            sections=sections,
            max_matches=max_matches,
            mapping_context=mapping_context,
        )
        mapping.validation_issues.append(f"AI source mapping failed; used keyword fallback: {exc}")
    mapping = _clean_mapping(mapping, toc_items, node=node, sections=sections, max_matches=max_matches)
    result = SourceMappingValidator().validate(mapping, toc_items)
    if not result.passed:
        mapping.validation_issues = [issue.message for issue in result.issues]
        mapping.matches = [match for match in mapping.matches if match.section_id in {item.section_id for item in toc_items}]
    mapping = _expand_matches_with_descendants(
        mapping=mapping,
        toc_items=toc_items,
        sections=sections,
        node=node,
        max_matches=max_matches,
        mapping_context=mapping_context,
    )
    section_by_id = {section.id: section for section in sections}
    selected_sections = [section_by_id[match.section_id] for match in mapping.matches if match.section_id in section_by_id]
    mapping.evidence = build_source_evidence(
        node=node,
        matches=mapping.matches,
        sections=selected_sections,
        max_total=max_evidence_spans,
        extra_terms=_terms(mapping_context),
    )
    attach_evidence_ids(mapping.matches, mapping.evidence)
    match_by_section_id = {match.section_id: match for match in mapping.matches}
    evidence_by_section_id: dict[str, list[str]] = {}
    for span in mapping.evidence:
        evidence_by_section_id.setdefault(span.section_id, []).append(f"{span.evidence_id}: {span.summary}")
    source_matches = [
        SourceMatch(
            section_id=section.id,
            title_path=section.title_path,
            snippet=_source_match_snippet(section.content, evidence_by_section_id.get(section.id, [])),
            score=round(match_by_section_id[section.id].confidence, 3) if section.id in match_by_section_id else 0,
        )
        for section in selected_sections
    ]
    mapping.evidence_artifact_path = artifacts.write_text(project_id, f"mapping/{node.id}.evidence.md", _render_evidence_markdown(mapping))
    mapping.artifact_path = artifacts.write_text(project_id, f"mapping/{node.id}.json", to_json_text(dump_model(mapping)))
    return mapping, selected_sections, source_matches


def _fallback_mapping(
    *,
    node: TemplateNode,
    toc_items: list[SourceTocItem],
    sections: list[MarkdownSection],
    max_matches: int,
    mapping_context: str = "",
) -> SourceMappingResult:
    terms = _terms(" ".join([node.title, *node.source_rules, *node.auto_fill, *node.special_notes, mapping_context]))
    section_by_id = {section.id: section for section in sections}
    scored: list[tuple[float, SourceTocItem]] = []
    for item in toc_items:
        haystack = " ".join([*item.title_path, item.snippet, section_by_id.get(item.section_id).content[:800] if item.section_id in section_by_id else ""])
        score = _term_score(haystack, terms)
        if score > 0:
            scored.append((score, item))
    if not scored:
        scored = [(1.0, item) for item in toc_items if item.char_count > 0][:max_matches]
    scored.sort(key=lambda item: (item[0], item[1].char_count), reverse=True)
    matches = [
        SourceMappingMatch(
            section_id=item.section_id,
            title_path=item.title_path,
            usage="fact",
            reason="keyword_fallback_mapping",
            confidence=round(min(0.75, 0.35 + score / 20), 3),
        )
        for score, item in scored[:max_matches]
    ]
    return SourceMappingResult(node_id=node.id, matches=matches)


def build_source_mapping_prompt(
    *,
    profile: ProjectProfile,
    toc_items: list[SourceTocItem],
    node: TemplateNode,
    max_matches: int = 8,
    mapping_context: str = "",
) -> str:
    return "\n".join(
        [
            "你是施工组织设计来源匹配 agent。你只负责判断当前模板小章节应引用投标文档中的哪些章节，不生成正文。",
            "",
            "项目概况：",
            to_json_text(dump_model(profile)),
            "",
            "投标文档目录：",
            to_json_text(_compact_toc(toc_items)),
            "",
            "当前小章节：",
            to_json_text(dump_model(node)),
            "",
            "当前小章节主要来源要求：",
            to_json_text(node.source_rules),
            "",
            "## Mapping Control Context",
            mapping_context or "none",
            "",
            "任务：",
            "从投标文档目录中选择最相关的章节，供后续生成正文使用。",
            "",
            "输出要求：",
            "只输出 JSON，不要 Markdown，不要解释。",
            "schema：",
            '{"node_id":"string","matches":[{"section_id":"string","title_path":["string"],"usage":"fact|method|quantity|risk|schedule|quality|safety|environment|acceptance","reason":"string","confidence":0.0}],"missing_evidence":["string"]}',
            "",
            "规则：",
            "- node_id 必须等于当前小章节 id。",
            "- section_id 必须来自输入目录。",
            f"- 最多返回 {max_matches} 个 matches。",
            "- confidence 范围 0 到 1。",
            "- 找不到可靠来源时 matches 为空，并说明 missing_evidence。",
            "- 不得虚构章节、页码、条款或参数。",
        ]
    )


def _clean_mapping(
    mapping: SourceMappingResult,
    toc_items: list[SourceTocItem],
    *,
    node: TemplateNode,
    sections: list[MarkdownSection],
    max_matches: int = 8,
) -> SourceMappingResult:
    toc_by_id = {item.section_id: item for item in toc_items}
    section_by_id = {section.id: section for section in sections}
    cleaned: list[SourceMappingMatch] = []
    filtered: list[str] = []
    seen: set[str] = set()
    for match in mapping.matches:
        if match.section_id in seen:
            continue
        seen.add(match.section_id)
        toc = toc_by_id.get(match.section_id)
        section = section_by_id.get(match.section_id)
        if toc and _is_unrelated_source_for_node(node, toc, section):
            filtered.append(match.section_id)
            continue
        if toc and not match.title_path:
            match.title_path = toc.title_path
        match.confidence = max(0, min(1, match.confidence))
        cleaned.append(match)
        if len(cleaned) >= max_matches:
            break
    if filtered and cleaned:
        mapping.validation_issues.append(
            "Filtered unrelated source matches for current chapter: " + ", ".join(_dedupe_text(filtered))
        )
    mapping.matches = cleaned
    return mapping


def _expand_matches_with_descendants(
    *,
    mapping: SourceMappingResult,
    toc_items: list[SourceTocItem],
    sections: list[MarkdownSection],
    node: TemplateNode,
    max_matches: int,
    mapping_context: str = "",
) -> SourceMappingResult:
    toc_by_id = {item.section_id: item for item in toc_items}
    section_by_id = {section.id: section for section in sections}
    terms = _terms(" ".join([node.title, *node.source_rules, *node.auto_fill, *node.manual_fill, *node.special_notes, mapping_context]))
    expanded: list[SourceMappingMatch] = []
    added_descendants: list[str] = []

    for match in mapping.matches:
        expanded.append(match)
        parent = toc_by_id.get(match.section_id)
        if not parent:
            continue
        parent_content = section_by_id.get(parent.section_id).content if parent.section_id in section_by_id else ""
        if not _should_expand_parent(parent, parent_content, toc_items):
            continue

        candidates: list[tuple[float, SourceTocItem]] = []
        for item in toc_items:
            if item.section_id == parent.section_id or not _is_descendant_path(item.title_path, parent.title_path):
                continue
            section = section_by_id.get(item.section_id)
            if _is_unrelated_source_for_node(node, item, section):
                continue
            score = _descendant_detail_score(item, section, terms)
            if score > 0:
                candidates.append((score, item))
        candidates.sort(key=lambda entry: (entry[0], entry[1].char_count), reverse=True)
        for score, item in candidates[:2]:
            expanded.append(
                SourceMappingMatch(
                    section_id=item.section_id,
                    title_path=item.title_path,
                    usage=match.usage,
                    reason=f"source_child_expansion: parent section `{parent.section_id}` matched; descendant carries detailed evidence.",
                    confidence=round(min(0.86, max(0.45, match.confidence - 0.05 + score / 60)), 3),
                )
            )
            added_descendants.append(item.section_id)

    mapping.matches = _dedupe_matches(expanded)[:max_matches]
    if added_descendants:
        mapping.validation_issues.append(
            "Expanded parent source matches with detailed child sections: " + ", ".join(_dedupe_text(added_descendants))
        )
    return mapping


def _should_expand_parent(parent: SourceTocItem, parent_content: str, toc_items: list[SourceTocItem]) -> bool:
    has_descendant = any(
        item.section_id != parent.section_id and _is_descendant_path(item.title_path, parent.title_path) for item in toc_items
    )
    if not has_descendant:
        return False
    compact = " ".join((parent_content or parent.snippet or "").split())
    return len(compact) < 900 or parent.char_count < 900


def _is_descendant_path(child_path: list[str], parent_path: list[str]) -> bool:
    return len(child_path) > len(parent_path) and child_path[: len(parent_path)] == parent_path


def _descendant_detail_score(item: SourceTocItem, section: MarkdownSection | None, terms: list[str]) -> float:
    content = section.content[:1600] if section else ""
    haystack = " ".join([*item.title_path, item.snippet, content])
    score = _term_score(haystack, terms)
    if item.char_count > 0:
        score += min(item.char_count / 900, 2.5)
    if re.search(r"\d", haystack):
        score += 1.2
    if any(term in haystack for term in _HIGH_VALUE_DETAIL_TERMS):
        score += 1.8
    return score


def _is_unrelated_source_for_node(node: TemplateNode, toc: SourceTocItem, section: MarkdownSection | None) -> bool:
    node_text = " ".join([node.title, *node.source_rules, *node.auto_fill, *node.manual_fill, *node.special_notes])
    haystack = _normalize_mapping_text(" ".join([*toc.title_path, toc.snippet, section.content[:1200] if section else ""]))
    if not _is_craft_node(node_text):
        return False
    relevance_terms = _craft_relevance_terms(node_text)
    if not relevance_terms:
        return False
    if not _contains_any(haystack, relevance_terms):
        return True
    if _contains_any(haystack, _UNRELATED_CRAFT_SOURCE_TERMS) and not _contains_any(haystack, _craft_core_terms(node_text)):
        return True
    return False


def _is_craft_node(text: str) -> bool:
    if _is_non_craft_overview_node(text):
        return False
    return _contains_any(text, {"注水", "灌浆", "钻孔", "覆盖", "封堵", "压实", "灭火", "裂隙", "工艺", "施工方法"})


def _is_non_craft_overview_node(text: str) -> bool:
    return _contains_any(text, {"概况", "现状", "位置", "交通", "自然地理", "勘查", "勘察"})


def _craft_relevance_terms(text: str) -> set[str]:
    terms: set[str] = set()
    if "注水" in text or "降温" in text:
        terms.update({"注水", "降温", "裂隙", "压力", "流量", "喷头", "停注", "水量", "温度"})
    if "灌浆" in text or "帷幕" in text:
        terms.update({"灌浆", "帷幕", "浆液", "粉煤灰", "黄泥浆", "水泥", "配比", "钻孔", "孔深", "孔径", "压力"})
    if "钻孔" in text or "探测" in text:
        terms.update({"钻孔", "探测", "观测孔", "探水孔", "孔深", "孔径", "成孔", "测温"})
    if "覆盖" in text or "封堵" in text:
        terms.update({"覆盖", "封堵", "剥挖", "回填", "压实", "厚度", "土方", "矸石"})
    if "灭火" in text and not _has_specific_craft_term(text):
        terms.update({"灭火", "火区", "高温", "治理区", "采空区", "煤火"})
    return terms


def _craft_core_terms(text: str) -> set[str]:
    terms: set[str] = set()
    if "注水" in text or "降温" in text:
        terms.update({"注水", "降温注水", "裂隙注水", "鸭嘴式喷头", "停注"})
    if "灌浆" in text or "帷幕" in text:
        terms.update({"灌浆", "帷幕灌浆", "浆液", "黄泥浆", "粉煤灰浆", "灌浆孔"})
    if "钻孔" in text or "探测" in text:
        terms.update({"钻孔", "探测孔", "观测孔", "探水孔", "成孔", "测温孔"})
    if "覆盖" in text or "封堵" in text:
        terms.update({"覆盖", "封堵", "压实", "回填", "剥挖"})
    if "灭火" in text and not _has_specific_craft_term(text):
        terms.update({"灭火", "煤火", "火区", "治理区", "采空区", "高温"})
    return terms or _craft_relevance_terms(text)


def _has_specific_craft_term(text: str) -> bool:
    return any(term in text for term in ("注水", "降温", "灌浆", "帷幕", "钻孔", "探测", "覆盖", "封堵"))


_UNRELATED_CRAFT_SOURCE_TERMS = {
    "火区勘查",
    "作业技术依据",
    "安全法规",
    "岩土工程勘察规范",
    "勘查点位",
    "勘查结果",
    "业绩",
    "类似项目",
    "代表工程",
    "承担工作",
    "开工日期",
    "完工日期",
    "合同额",
    "水利枢纽",
    "水电站",
    "电站装机",
    "多年平均发电量",
    "灌溉输水洞",
    "导流隧洞",
    "TBM",
    "项目经理",
    "投标人",
}


def _contains_any(text: str, terms: set[str]) -> bool:
    return any(term in text for term in terms)


def _normalize_mapping_text(text: str) -> str:
    return (text or "").replace("注水泥", "水泥")


def _dedupe_matches(matches: list[SourceMappingMatch]) -> list[SourceMappingMatch]:
    deduped: list[SourceMappingMatch] = []
    seen: set[str] = set()
    for match in matches:
        if match.section_id in seen:
            continue
        seen.add(match.section_id)
        deduped.append(match)
    return deduped


def _dedupe_text(items: list[str]) -> list[str]:
    deduped: list[str] = []
    for item in items:
        if item not in deduped:
            deduped.append(item)
    return deduped


def _snippet(text: str, limit: int = 420) -> str:
    compact = " ".join(text.split())
    return compact if len(compact) <= limit else compact[:limit].rstrip() + "..."


def _source_match_snippet(section_content: str, evidence_summaries: list[str]) -> str:
    if evidence_summaries:
        return " | ".join(evidence_summaries[:3])
    return _snippet(section_content)


def _render_evidence_markdown(mapping: SourceMappingResult) -> str:
    lines = [f"# Source Evidence Map: {mapping.node_id}", ""]
    if not mapping.evidence:
        lines.append("No source evidence spans were selected.")
        return "\n".join(lines).strip() + "\n"
    for span in mapping.evidence:
        title_path = " > ".join(span.title_path)
        line_range = ""
        if span.start_line is not None and span.end_line is not None:
            line_range = f"L{span.start_line}-L{span.end_line}"
        lines.extend(
            [
                f"## {span.evidence_id}",
                f"- section_id: `{span.section_id}`",
                f"- title_path: {title_path}",
                f"- lines: {line_range or 'unknown'}",
                f"- usage: {span.usage}",
                f"- template_module: {span.template_module}",
                f"- confidence: {span.confidence}",
                f"- matched_terms: {', '.join(span.matched_terms) if span.matched_terms else 'none'}",
                f"- reason: {span.reason or 'none'}",
                "",
                "```text",
                span.quote.strip(),
                "```",
                "",
            ]
        )
    return "\n".join(lines).strip() + "\n"


def _compact_toc(toc_items: list[SourceTocItem]) -> list[dict]:
    return [
        {
            "section_id": item.section_id,
            "title_path": item.title_path,
            "level": item.level,
            "char_count": item.char_count,
        }
        for item in toc_items
    ]


def _terms(text: str) -> list[str]:
    stop = {"施工", "工程", "组织", "设计", "方案", "章节", "主要", "来源", "自动", "补充"}
    seen: list[str] = []
    for term in re.findall(r"[\u4e00-\u9fff]{2,8}|[A-Za-z][A-Za-z0-9_-]{1,30}|\d+(?:\.\d+)?", text or ""):
        if term in stop or term in seen:
            continue
        seen.append(term)
    return seen


def _term_score(text: str, terms: list[str]) -> float:
    compact = re.sub(r"\s+", " ", text or "")
    score = 0.0
    for term in terms:
        count = compact.count(term)
        if count:
            score += min(count, 5) * (1 + min(len(term), 8) / 10)
    return score
