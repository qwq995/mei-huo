from __future__ import annotations

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


def map_chapter_sources(
    *,
    project_id: str,
    profile: ProjectProfile,
    toc_items: list[SourceTocItem],
    sections: list[MarkdownSection],
    node: TemplateNode,
    llm: StructuredLLMClient,
    artifacts: ArtifactRepository,
) -> tuple[SourceMappingResult, list[MarkdownSection], list[SourceMatch]]:
    data = llm.complete_json(
        build_source_mapping_prompt(profile=profile, toc_items=toc_items, node=node),
        schema_name="SourceMappingResult",
    )
    mapping = SourceMappingResult(**data)
    mapping = _clean_mapping(mapping, toc_items)
    result = SourceMappingValidator().validate(mapping, toc_items)
    if not result.passed:
        mapping.validation_issues = [issue.message for issue in result.issues]
        mapping.matches = [match for match in mapping.matches if match.section_id in {item.section_id for item in toc_items}]
    section_by_id = {section.id: section for section in sections}
    selected_sections = [section_by_id[match.section_id] for match in mapping.matches if match.section_id in section_by_id]
    mapping.evidence = build_source_evidence(node=node, matches=mapping.matches, sections=selected_sections)
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


def build_source_mapping_prompt(*, profile: ProjectProfile, toc_items: list[SourceTocItem], node: TemplateNode) -> str:
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
            "- 最多返回 8 个 matches。",
            "- confidence 范围 0 到 1。",
            "- 找不到可靠来源时 matches 为空，并说明 missing_evidence。",
            "- 不得虚构章节、页码、条款或参数。",
        ]
    )


def _clean_mapping(mapping: SourceMappingResult, toc_items: list[SourceTocItem]) -> SourceMappingResult:
    toc_by_id = {item.section_id: item for item in toc_items}
    cleaned: list[SourceMappingMatch] = []
    seen: set[str] = set()
    for match in mapping.matches:
        if match.section_id in seen:
            continue
        seen.add(match.section_id)
        toc = toc_by_id.get(match.section_id)
        if toc and not match.title_path:
            match.title_path = toc.title_path
        match.confidence = max(0, min(1, match.confidence))
        cleaned.append(match)
        if len(cleaned) >= 8:
            break
    mapping.matches = cleaned
    return mapping


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
