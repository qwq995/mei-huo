from __future__ import annotations

import json
import re
from functools import lru_cache
from importlib import resources

from pydantic import BaseModel, Field


class WritingPattern(BaseModel):
    key: str
    aliases: list[str] = Field(default_factory=list)
    source_topics: list[str] = Field(default_factory=list)
    corpus_common_headings: list[str] = Field(default_factory=list)
    preferred_structure: list[str] = Field(default_factory=list)
    required_source_facts: list[str] = Field(default_factory=list)
    auto_writable_moves: list[str] = Field(default_factory=list)
    human_only_items: list[str] = Field(default_factory=list)
    revision_signals: list[str] = Field(default_factory=list)
    corpus_basis: list[str] = Field(default_factory=list)


class WritingPatternLibrary(BaseModel):
    version: str
    corpus_scope: str
    patterns: dict[str, WritingPattern]


class WritingPatternMatch(BaseModel):
    pattern_key: str
    score: int
    matched_terms: list[str] = Field(default_factory=list)
    required_source_facts: list[str] = Field(default_factory=list)
    human_only_items: list[str] = Field(default_factory=list)
    revision_signals: list[str] = Field(default_factory=list)


class WritingPatternPromptCard(BaseModel):
    pattern_key: str
    match_score: int | str | None = None
    matched_terms: list[str] = Field(default_factory=list)
    evidence_scope: str = "Pattern guidance is structural only; project facts must come from mapped section_id/evidence_id, user supplements, or manual placeholders."
    organization_policy: list[str] = Field(default_factory=list)
    outline_guidance: list[str] = Field(default_factory=list)
    source_mapping_requirements: list[str] = Field(default_factory=list)
    detail_design_rules: list[str] = Field(default_factory=list)
    generation_moves: list[str] = Field(default_factory=list)
    human_only_items: list[str] = Field(default_factory=list)
    revision_checks: list[str] = Field(default_factory=list)
    corpus_basis: list[str] = Field(default_factory=list)


@lru_cache(maxsize=1)
def load_writing_pattern_library() -> WritingPatternLibrary:
    try:
        text = resources.files("coalplan.assets.generation").joinpath("writing_patterns.json").read_text(encoding="utf-8")
        data = json.loads(text)
        return WritingPatternLibrary.model_validate(data)
    except Exception:
        return _fallback_library()


def pattern_for_key(key: str) -> WritingPattern | None:
    return load_writing_pattern_library().patterns.get(key)


def match_patterns_for_text(text: str, *, limit: int = 3) -> list[WritingPatternMatch]:
    """Return local-corpus writing patterns that match a chapter or template node."""

    normalized = _normalize_match_text(text)
    if not normalized:
        return []
    matches: list[WritingPatternMatch] = []
    for pattern in load_writing_pattern_library().patterns.values():
        score = 0
        matched_terms: list[str] = []
        for term in pattern.aliases:
            if _term_hits(normalized, term):
                score += 4
                matched_terms.append(term)
        for term in pattern.source_topics:
            if _term_hits(normalized, term):
                score += 3
                matched_terms.append(term)
        for term in pattern.corpus_common_headings:
            if _term_hits(normalized, term):
                score += 2
                matched_terms.append(term)
        for term in pattern.required_source_facts:
            if _term_hits(normalized, term):
                score += 1
                matched_terms.append(term)
        if score <= 0:
            continue
        matches.append(
            WritingPatternMatch(
                pattern_key=pattern.key,
                score=score,
                matched_terms=list(dict.fromkeys(matched_terms))[:12],
                required_source_facts=pattern.required_source_facts,
                human_only_items=pattern.human_only_items,
                revision_signals=pattern.revision_signals,
            )
        )
    matches.sort(key=lambda item: (-item.score, item.pattern_key))
    return matches[:limit]


def render_pattern_for_prompt(key: str) -> str:
    pattern = pattern_for_key(key)
    if pattern is None:
        return ""
    return render_pattern_prompt_card(build_pattern_prompt_card(pattern))
    lines = [f"- pattern_key: {pattern.key}"]
    if pattern.source_topics:
        lines.append("- source_topics: " + "；".join(pattern.source_topics))
    if pattern.corpus_common_headings:
        lines.append("- local_corpus_common_headings: " + "；".join(pattern.corpus_common_headings[:12]))
    if pattern.preferred_structure:
        lines.append("- preferred_structure:")
        lines.extend(f"  {index}. {item}" for index, item in enumerate(pattern.preferred_structure, start=1))
    if pattern.required_source_facts:
        lines.append("- required_source_facts: " + "；".join(pattern.required_source_facts))
    if pattern.auto_writable_moves:
        lines.append("- auto_writable_moves: " + "；".join(pattern.auto_writable_moves))
    if pattern.human_only_items:
        lines.append("- human_only_items: " + "；".join(pattern.human_only_items))
    if pattern.revision_signals:
        lines.append("- revision_signals: " + "；".join(pattern.revision_signals))
    if pattern.corpus_basis:
        lines.append("- corpus_basis: " + "；".join(pattern.corpus_basis))
    return "\n".join(lines)


def build_pattern_prompt_card(
    pattern: WritingPattern,
    *,
    match: WritingPatternMatch | None = None,
    match_score: int | str | None = None,
) -> WritingPatternPromptCard:
    score = match.score if match else match_score
    matched_terms = match.matched_terms if match else []
    organization_policy = [
        "Learn reusable organization from human-written construction plans: directory placement, subsection order, key point coverage, and control-loop shape.",
        "Do not imitate human reference wording, page length, or project-specific facts unless the current mapped evidence supports them.",
        "Use corpus patterns to decide what a chapter should cover; use mapped source evidence to decide what this project can state.",
    ]
    outline = [
        "Match template node title, four-module text, and source TOC headings against these aliases/source topics.",
        "Use corpus_common_headings as subsection candidates only when the current source TOC or user outline supports them.",
    ]
    if pattern.aliases:
        outline.append("aliases: " + "；".join(pattern.aliases[:12]))
    if pattern.source_topics:
        outline.append("source_topics: " + "；".join(pattern.source_topics[:12]))
    if pattern.corpus_common_headings:
        outline.append("local_corpus_common_headings: " + "；".join(pattern.corpus_common_headings[:12]))

    source_mapping = [
        "Before writing, find source sections/evidence spans for each required_source_fact that is relevant to the current chapter.",
        "If evidence is missing, return missing_evidence or keep a manual placeholder; never invent the fact from the pattern.",
    ]
    if pattern.required_source_facts:
        source_mapping.append("required_source_facts: " + "；".join(pattern.required_source_facts[:16]))

    detail_rules = [
        "Allocate target word count across the preferred_structure instead of writing one generic paragraph.",
        "For dense craft or management chapters, split into source-derived subchapters before long-form generation.",
    ]
    if pattern.preferred_structure:
        detail_rules.extend(f"{index}. {item}" for index, item in enumerate(pattern.preferred_structure[:10], start=1))

    generation_moves = [
        "Use these moves to organize prose under `## 生成正文`; do not add external module headings unless the outline already has them.",
        *pattern.auto_writable_moves[:12],
    ]
    revision_checks = [
        "If any revision signal appears and source evidence exists, regenerate with required facts; if evidence is missing, remap or request human input.",
        *pattern.revision_signals[:12],
    ]
    return WritingPatternPromptCard(
        pattern_key=pattern.key,
        match_score=score,
        matched_terms=matched_terms[:12],
        organization_policy=organization_policy,
        outline_guidance=outline,
        source_mapping_requirements=source_mapping,
        detail_design_rules=detail_rules,
        generation_moves=generation_moves,
        human_only_items=pattern.human_only_items[:16],
        revision_checks=revision_checks,
        corpus_basis=pattern.corpus_basis[:8],
    )


def render_pattern_prompt_card(card: WritingPatternPromptCard) -> str:
    lines = [f"- pattern_key: {card.pattern_key}"]
    if card.match_score is not None:
        lines.append(f"- match_score: {card.match_score}")
    if card.matched_terms:
        lines.append("- matched_terms: " + ", ".join(card.matched_terms))
    lines.append("- evidence_scope: " + card.evidence_scope)
    lines.extend(_card_section("organization_policy", card.organization_policy))
    lines.extend(_card_section("outline_guidance", card.outline_guidance))
    lines.extend(_card_section("source_mapping_requirements", card.source_mapping_requirements))
    lines.extend(_card_section("detail_design_rules", card.detail_design_rules))
    lines.extend(_card_section("generation_moves", card.generation_moves))
    lines.extend(_card_section("human_only_items", card.human_only_items))
    lines.extend(_card_section("revision_checks_from_revision_signals", card.revision_checks))
    lines.extend(_card_section("corpus_basis", card.corpus_basis))
    return "\n".join(lines)


def render_pattern_matches_for_prompt(
    text: str,
    *,
    primary_key: str | None = None,
    limit: int = 3,
) -> str:
    matches = match_patterns_for_text(text, limit=limit)
    keys: list[str] = []
    if primary_key:
        keys.append(primary_key)
    keys.extend(match.pattern_key for match in matches)
    unique_keys = list(dict.fromkeys(keys))[:limit]
    blocks: list[str] = []
    match_by_key = {match.pattern_key: match for match in matches}
    for key in unique_keys:
        pattern = pattern_for_key(key)
        if pattern is None:
            continue
        match = match_by_key.get(key)
        blocks.append(
            render_pattern_prompt_card(
                build_pattern_prompt_card(
                    pattern,
                    match=match,
                    match_score="primary guidance" if match is None and key == primary_key else None,
                )
            )
        )
    return "\n\n".join(blocks)


def _normalize_match_text(text: str) -> str:
    return re.sub(r"\s+", "", text or "").lower()


def _term_hits(normalized_text: str, term: str) -> bool:
    normalized_term = _normalize_match_text(term)
    return bool(normalized_term and normalized_term in normalized_text)


def _card_section(label: str, items: list[str]) -> list[str]:
    if not items:
        return []
    return [f"- {label}:"] + [f"  - {item}" for item in items]


def _fallback_library() -> WritingPatternLibrary:
    patterns = {
        "overview": WritingPattern(
            key="overview",
            aliases=["工程概况", "项目概况", "工程概述"],
            preferred_structure=["项目名称、位置和建设背景", "施工范围和工程对象", "主要工程量", "施工条件", "工期和质量安全环保目标", "缺失项"],
            required_source_facts=["项目名称", "位置", "施工范围", "工程量", "工期", "质量安全环保目标"],
            human_only_items=["合同编号", "坐标", "审批结论", "未在来源中出现的工程量"],
            revision_signals=["正文只写概述性套话", "工程量在来源中存在但仍留人工补充"],
        ),
        "craft": WritingPattern(
            key="craft",
            aliases=["施工工艺", "施工方法", "主要施工技术"],
            preferred_structure=["适用范围", "工程量和施工对象", "工艺流程", "资源配置", "施工方法和控制参数", "质量检验验收", "安全环保措施", "缺失项"],
            required_source_facts=["施工对象", "工艺流程", "工程量", "参数", "质量检验要求", "安全风险"],
            human_only_items=["最终参数", "图纸编号", "审批后的专项方案", "现场实测数据"],
            revision_signals=["高密度工艺章节未拆小节", "只写原则没有工序", "证据中的参数没有进入正文"],
        ),
        "management": WritingPattern(
            key="management",
            aliases=["质量", "安全", "环保", "进度", "资源", "文明施工", "应急"],
            preferred_structure=["管理目标", "组织职责", "制度流程", "过程控制", "检查考核与整改", "记录和交付物", "人工确认项"],
            required_source_facts=["目标", "组织职责", "控制措施", "检查验收", "风险或约束"],
            human_only_items=["责任人", "审批后的目标", "应急联系人", "最终资源清单"],
            revision_signals=["脱离项目风险的通用管理套话", "无检查闭环", "未引用来源中的目标或制度"],
        ),
    }
    return WritingPatternLibrary(version="fallback", corpus_scope="built-in defaults", patterns=patterns)
