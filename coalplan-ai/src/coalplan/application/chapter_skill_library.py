from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

from pydantic import BaseModel, Field

from coalplan.application.serialization import dump_model, to_json_text
from coalplan.domain.documents import SourceTocItem
from coalplan.domain.templates import TemplateNode, TemplateTree, iter_template_nodes


class ChapterSkillExpansion(BaseModel):
    title: str
    evidence_terms: list[str] = Field(default_factory=list)


class ChapterSkill(BaseModel):
    key: str
    name: str
    aliases: list[str] = Field(default_factory=list)
    exclude_title_terms: list[str] = Field(default_factory=list)
    outline_expansion: list[ChapterSkillExpansion] = Field(default_factory=list)
    evidence_requirements: list[str] = Field(default_factory=list)
    generation_rules: list[str] = Field(default_factory=list)
    human_only_items: list[str] = Field(default_factory=list)


class ChapterSkillMatch(BaseModel):
    skill_key: str
    score: int
    matched_terms: list[str] = Field(default_factory=list)
    skill: ChapterSkill


@lru_cache(maxsize=1)
def load_chapter_skills() -> dict[str, ChapterSkill]:
    root = Path(__file__).resolve().parents[1] / "assets" / "skills"
    skills: dict[str, ChapterSkill] = {}
    for path in sorted(root.glob("*/references/runtime.json")):
        skill = ChapterSkill.model_validate(json.loads(path.read_text(encoding="utf-8")))
        skills[skill.key] = skill
    return skills


def match_chapter_skills(
    *,
    title: str,
    context: str = "",
    limit: int = 1,
) -> list[ChapterSkillMatch]:
    normalized_title = _normalize(title)
    normalized_context = _normalize(context)
    matches: list[ChapterSkillMatch] = []
    for skill in load_chapter_skills().values():
        if any(_normalize(term) in normalized_title for term in skill.exclude_title_terms):
            continue
        score = 0
        terms: list[str] = []
        title_matched = False
        for alias in skill.aliases:
            token = _normalize(alias)
            if not token:
                continue
            if token in normalized_title:
                score += 10 + min(len(token), 6)
                terms.append(alias)
                title_matched = True
            elif token in normalized_context:
                score += 2
                terms.append(alias)
        # Title hits rank highest, while context-only hits remain eligible. This
        # matters for short nodes such as "专项措施" whose parent/context names
        # the real craft or risk domain.
        if title_matched or score >= 4:
            matches.append(
                ChapterSkillMatch(
                    skill_key=skill.key,
                    score=score,
                    matched_terms=list(dict.fromkeys(terms))[:12],
                    skill=skill,
                )
            )
    matches.sort(key=lambda item: (-item.score, item.skill_key))
    return matches[:limit]


def build_outline_skill_context(
    template_tree: TemplateTree,
    toc_items: list[SourceTocItem],
) -> list[dict]:
    cards: list[dict] = []
    for node in iter_template_nodes(template_tree.nodes):
        context = " ".join(
            [
                *node.source_rules,
                *node.auto_fill,
                *node.manual_fill,
                *node.special_notes,
            ]
        )
        matches = match_chapter_skills(title=node.title, context=context, limit=1)
        if not matches:
            continue
        match = matches[0]
        cards.append(
            {
                "template_node_id": node.id,
                "template_title": node.title,
                "template_level": node.level,
                "skill_key": match.skill_key,
                "matched_terms": match.matched_terms,
                "outline_expansion": [dump_model(item) for item in match.skill.outline_expansion],
                "evidence_requirements": match.skill.evidence_requirements,
                "human_only_items": match.skill.human_only_items,
                "rule": "只增加模板节点下的子章节；必须由投标目录、模板四模块或该skill的结构要求支撑。",
            }
        )
    return cards


def render_outline_skill_context(template_tree: TemplateTree, toc_items: list[SourceTocItem]) -> str:
    cards = build_outline_skill_context(template_tree, toc_items)
    return to_json_text(cards) if cards else "[]"


def render_chapter_skills_for_prompt(node: TemplateNode) -> str:
    keys = list(node.matched_skill_keys)
    if not keys:
        context = " ".join(
            [
                *node.source_rules,
                *node.auto_fill,
                *node.manual_fill,
                *node.special_notes,
                node.chapter_summary.get("overview", "") if node.chapter_summary else "",
            ]
        )
        keys = [item.skill_key for item in match_chapter_skills(title=node.title, context=context, limit=1)]
    blocks: list[str] = []
    for key in keys[:2]:
        skill = load_chapter_skills().get(key)
        if skill is None:
            continue
        blocks.append(
            "\n".join(
                [
                    f"### skill: {skill.key}",
                    f"- 名称：{skill.name}",
                    "- 证据要求：" + "；".join(skill.evidence_requirements),
                    "- 推荐子任务：" + "；".join(item.title for item in skill.outline_expansion),
                    "- 生成顺序与控制：",
                    *[f"  - {item}" for item in skill.generation_rules],
                    "- 必须人工确认：" + "；".join(skill.human_only_items),
                    "- 事实边界：skill只控制结构和写法，不提供当前项目事实或参数。",
                ]
            )
        )
    # The generated pattern library is derived from real local sample TOCs.
    # It contributes structure seeds only; it is deliberately not used as a fact source.
    try:
        from coalplan.application.writing_pattern_library import match_patterns_for_text, pattern_for_key

        pattern_matches = match_patterns_for_text(
            " ".join(
                [
                    node.title,
                    *node.source_rules,
                    *node.auto_fill,
                    *node.manual_fill,
                    *node.special_notes,
                    node.chapter_summary.get("overview", "") if node.chapter_summary else "",
                ]
            ),
            limit=2,
        )
        for match in pattern_matches:
            pattern = pattern_for_key(match.pattern_key)
            if pattern is None:
                continue
            blocks.append(
                "\n".join(
                    [
                        f"### local-corpus-pattern: {pattern.key}",
                        "- 本地样本高频标题：" + "；".join(pattern.corpus_common_headings[:10]),
                        "- 本地样本组织方式：" + "；".join(pattern.preferred_structure),
                        "- 生成动作：" + "；".join(pattern.auto_writable_moves[:8]),
                        "- 本地样本依据：" + "；".join(pattern.corpus_basis[:4]),
                    ]
                )
            )
    except Exception:
        pass
    return "\n\n".join(blocks) or "无匹配特化 skill。"


def relevant_toc_for_expansion(
    expansion: ChapterSkillExpansion,
    toc_items: list[SourceTocItem],
    *,
    limit: int = 8,
) -> list[SourceTocItem]:
    terms = [_normalize(item) for item in expansion.evidence_terms if _normalize(item)]
    scored: list[tuple[int, SourceTocItem]] = []
    for item in toc_items:
        text = _normalize(" ".join(item.title_path) + " " + item.snippet)
        score = sum(1 for term in terms if term in text)
        if score:
            scored.append((score, item))
    scored.sort(key=lambda pair: (-pair[0], -pair[1].char_count, pair[1].section_id))
    return [item for _, item in scored[:limit]]


def _normalize(value: str) -> str:
    return re.sub(r"\s+", "", value or "").lower()
