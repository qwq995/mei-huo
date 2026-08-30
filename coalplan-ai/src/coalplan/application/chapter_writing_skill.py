"""Build a project- and chapter-specific writing skill for chapter generation."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from coalplan.application.chapter_writing_guidance import guidance_for_node
from coalplan.application.serialization import dump_model, to_json_text
from coalplan.domain.generation_control import ChapterGenerationPolicy
from coalplan.domain.templates import TemplateNode
from coalplan.ports.llm import StructuredLLMClient


class SkillCoverageItem(BaseModel):
    topic: str
    purpose: str = ""
    required_points: list[str] = Field(default_factory=list)
    evidence_expectation: str = ""
    output_shape: str = ""
    acceptance_checks: list[str] = Field(default_factory=list)


class ChapterWritingSkill(BaseModel):
    skill_id: str = "ai_chapter_skill"
    version: str = "1.0"
    chapter_title: str
    category: str
    mission: str
    project_focus: list[str] = Field(default_factory=list)
    organization_logic: list[str] = Field(default_factory=list)
    coverage_plan: list[SkillCoverageItem] = Field(default_factory=list)
    detail_strategy: list[str] = Field(default_factory=list)
    transition_rules: list[str] = Field(default_factory=list)
    evidence_rules: list[str] = Field(default_factory=list)
    fact_boundary_rules: list[str] = Field(default_factory=list)
    avoid: list[str] = Field(default_factory=list)
    acceptance_checks: list[str] = Field(default_factory=list)
    prompt_instructions: list[str] = Field(default_factory=list)
    source_basis: list[str] = Field(default_factory=list)
    generated_by: str = "fallback"


def build_chapter_writing_skill_prompt(
    *,
    node: TemplateNode,
    project_profile: Any | None,
    global_context: str,
    policy: ChapterGenerationPolicy | None,
    selected_sections: list[Any],
) -> str:
    guidance = guidance_for_node(node)
    sources = [
        {
            "section_id": section.id,
            "title_path": section.title_path,
            "snippet": " ".join(section.content.split())[:700],
        }
        for section in selected_sections[:6]
    ]
    policy_data = dump_model(policy) if policy is not None else {}
    node_data = dump_model(node)
    return "\n".join(
        [
            "你是施工组织设计章节写作 Skill 设计 agent。请为一个具体章节生成可执行的写作指挥规则。",
            "这不是正文，也不是项目事实摘要；输出的 Skill 将作为后续章节生成模型的上层控制指令。",
            "",
            "## 任务目标",
            "把项目全局重点、当前章节职责、来源证据边界和施组写作逻辑组合成一份可执行 Skill。",
            "必须覆盖章节应该写什么、按什么顺序组织、每个要点需要什么证据、缺失时如何占位、完成后如何检查。",
            "",
            "## 项目概况",
            to_json_text(dump_model(project_profile)) if project_profile else "{}",
            "",
            "## 全局上下文",
            global_context[-8000:] if global_context else "暂无全局上下文。",
            "",
            "## 当前目录节点",
            to_json_text(node_data),
            "",
            "## 当前章节静态写作参考",
            to_json_text(dump_model(guidance)),
            "",
            "## 当前生成策略",
            to_json_text(policy_data),
            "",
            "## 当前已匹配投标来源候选",
            to_json_text(sources),
            "",
            "## 事实边界",
            "投标来源、项目画像和用户明确补充是项目事实来源；优秀原子只能提供工艺展开方式；写作 Skill 只能控制结构和表达。",
            "不得在 Skill 中创造工程量、参数、地名、日期、规范编号、审批结论或验收结论。",
            "",
            "请严格返回 JSON：",
            '{"skill_id":"chapter_skill_xxx","version":"1.0","chapter_title":"","category":"","mission":"",'
            '"project_focus":[],"organization_logic":[],"coverage_plan":[{"topic":"","purpose":"",'
            '"required_points":[],"evidence_expectation":"","output_shape":"","acceptance_checks":[]}],'
            '"detail_strategy":[],"transition_rules":[],"evidence_rules":[],"fact_boundary_rules":[],"avoid":[],"acceptance_checks":[],"prompt_instructions":[],"source_basis":[]}',
            "",
            "约束：",
            "- coverage_plan 按本章节真实职责拆成 4 至 10 个要点，不要输出空泛的万能目录。",
            "- organization_logic 必须说明先后关系、因果关系和哪些内容应合并或分开。",
            "- 每个 coverage_plan 项都要说明证据要求和缺失时的处理方式。",
            "- detail_strategy 要根据目标字数分配详略，不得用字数替代事实依据。",
            "- acceptance_checks 必须能让审查人员判断章节是否完整，至少覆盖事实、工艺、质量安全环保和记录闭环中适用的项目。",
            "- prompt_instructions 使用祈使句，能够直接指导正文生成模型。",
        ]
    )


def fallback_chapter_writing_skill(node: TemplateNode, *, reason: str = "fallback") -> ChapterWritingSkill:
    guidance = guidance_for_node(node)
    coverage = [
        SkillCoverageItem(topic=item, purpose="按当前章节职责展开", required_points=[item], output_shape="形成连续的小节或段落")
        for item in guidance.structure
    ]
    return ChapterWritingSkill(
        skill_id=f"fallback_{guidance.pattern_key}",
        chapter_title=node.title,
        category=guidance.category,
        mission=f"围绕“{node.title}”组织有来源、有工序、有控制闭环的施工组织设计内容。",
        organization_logic=guidance.structure,
        coverage_plan=coverage,
        detail_strategy=["优先展开与当前项目证据相关的部分", "缺少参数时保留人工补充占位"],
        transition_rules=["前一节的施工条件应自然引出后一节的施工方法", "质量、安全和环保控制应贴合对应工序"],
        evidence_rules=["优先使用 evidence_id 对应的投标原文", "没有证据的项目专属事实不得写成确定内容"],
        fact_boundary_rules=["原子和技巧不提供项目事实", "缺失参数改为定性要求或人工补充项"],
        avoid=guidance.avoid,
        acceptance_checks=["章节覆盖当前节点职责", "事实均有来源或人工确认", "工艺、控制和检查形成闭环"],
        prompt_instructions=["只输出当前写作单元正文", "不要输出生成过程说明"],
        source_basis=guidance.corpus_basis,
        generated_by=reason,
    )


def generate_chapter_writing_skill(
    *,
    node: TemplateNode,
    project_profile: Any | None,
    global_context: str,
    policy: ChapterGenerationPolicy | None,
    selected_sections: list[Any],
    llm: StructuredLLMClient,
) -> ChapterWritingSkill:
    fallback = fallback_chapter_writing_skill(node)
    try:
        data = llm.complete_json(
            build_chapter_writing_skill_prompt(
                node=node,
                project_profile=project_profile,
                global_context=global_context,
                policy=policy,
                selected_sections=selected_sections,
            ),
            schema_name="ChapterWritingSkill",
        )
        result = ChapterWritingSkill.model_validate({**fallback.model_dump(), **(data or {}), "generated_by": "llm"})
        return result
    except Exception:
        return fallback


def render_chapter_writing_skill(skill: ChapterWritingSkill) -> str:
    lines = [
        f"Skill ID：{skill.skill_id}；版本：{skill.version}；生成方式：{skill.generated_by}",
        f"章节任务：{skill.mission}",
        "项目侧重点：" + "；".join(skill.project_focus or ["按当前项目证据组织"]) + "。",
        "组织逻辑：",
        *[f"- {item}" for item in skill.organization_logic],
        "覆盖计划：",
    ]
    for item in skill.coverage_plan:
        lines.append(f"- {item.topic}：{item.purpose}")
        if item.required_points:
            lines.append("  要点：" + "；".join(item.required_points))
        if item.evidence_expectation:
            lines.append("  证据要求：" + item.evidence_expectation)
        if item.output_shape:
            lines.append("  输出形态：" + item.output_shape)
        if item.acceptance_checks:
            lines.append("  检查：" + "；".join(item.acceptance_checks))
    for title, values in (
        ("详略策略", skill.detail_strategy),
        ("衔接规则", skill.transition_rules),
        ("事实与来源规则", skill.evidence_rules + skill.fact_boundary_rules),
        ("避免", skill.avoid),
        ("验收检查", skill.acceptance_checks),
        ("生成指令", skill.prompt_instructions),
    ):
        if values:
            lines.extend([f"{title}：", *[f"- {item}" for item in values]])
    return "\n".join(lines)

