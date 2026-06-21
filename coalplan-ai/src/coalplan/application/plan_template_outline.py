from __future__ import annotations

from coalplan.application.serialization import dump_model, to_json_text
from coalplan.domain.documents import SourceTocItem
from coalplan.domain.outline import TemplateOutlineNode, TemplateOutlinePlan
from coalplan.domain.profile import ProjectProfile
from coalplan.domain.templates import TemplateNode, TemplateTree, iter_template_nodes
from coalplan.infrastructure.validation.json_contract import TemplateOutlinePlanValidator
from coalplan.ports.llm import StructuredLLMClient
from coalplan.ports.repository import ArtifactRepository


def plan_template_outline(
    *,
    project_id: str,
    profile: ProjectProfile,
    toc_items: list[SourceTocItem],
    template_tree: TemplateTree,
    llm: StructuredLLMClient,
    artifacts: ArtifactRepository,
) -> TemplateOutlinePlan:
    try:
        data = llm.complete_json(
            build_template_outline_prompt(profile=profile, toc_items=toc_items, template_tree=template_tree),
            schema_name="TemplateOutlinePlan",
        )
        outline = TemplateOutlinePlan(**data)
    except Exception:
        outline = _fallback_outline(profile, template_tree, toc_items)
    outline = _clean_outline(outline, template_tree, toc_items)
    result = TemplateOutlinePlanValidator().validate(outline, template_tree, toc_items)
    if not result.passed:
        raise ValueError("; ".join(issue.message for issue in result.issues))
    outline.artifact_json_path = artifacts.write_text(project_id, "outline/generated_outline.json", to_json_text(dump_model(outline)))
    outline.artifact_markdown_path = artifacts.write_text(project_id, "outline/generated_outline.md", render_outline_markdown(outline))
    return outline


def build_template_outline_prompt(*, profile: ProjectProfile, toc_items: list[SourceTocItem], template_tree: TemplateTree) -> str:
    return "\n".join(
        [
            "你是施工组织设计目录规划 agent。你需要依据项目概况、投标文档目录和目标模板，生成适合本项目的完整施组目录规划。",
            "",
            "项目概况：",
            to_json_text(dump_model(profile)),
            "",
            "投标文档目录：",
            to_json_text(_compact_toc(toc_items)),
            "",
            "目标模板树：",
            to_json_text(_flat_template_nodes(template_tree)),
            "",
            "任务：",
            "按目标模板结构生成本项目目录规划，并为每个可生成小章节填写四个模块。",
            "",
            "输出要求：",
            "只输出 JSON，不要 Markdown，不要解释。",
            "schema：",
            '{"template_id":"string","nodes":[{"node_id":"string","title":"string","level":1,"enabled":true,"source_hints":["section_id"],"main_sources":["string"],"auto_fill":["string"],"manual_fill":["string"],"special_notes":["string"],"target_word_count":800}]}',
            "",
            "规则：",
            "- node_id 必须来自目标模板树。",
            "- 不得新增模板外大章节。",
            "- source_hints 只能引用真实 section_id。",
            "- main_sources 必须描述真实投标文档中可依据的章节或内容。",
            "- auto_fill 只能写模型可归纳、润色、组织的内容。",
            "- manual_fill 必须写现场、图纸、合同、审批、实测、人员设备等需人工确认项。",
            "- special_notes 仅在边界、地质、水文、施工参数、质量验收、安全风险等重难点出现；没有则为空数组。",
            "- target_word_count 为本节建议目标字数，可为 null；不得为了凑字数编造来源不支持的参数。",
        ]
    )


def apply_outline_to_template_tree(template_tree: TemplateTree, outline: TemplateOutlinePlan) -> TemplateTree:
    by_id = {node.node_id: node for node in outline.nodes if node.enabled}
    return TemplateTree(id=template_tree.id, name=template_tree.name, nodes=[_apply_outline_node(node, by_id) for node in template_tree.nodes])


def render_outline_markdown(outline: TemplateOutlinePlan) -> str:
    lines = [f"# 生成目录规划：{outline.template_id}", ""]
    for node in outline.nodes:
        if not node.enabled:
            continue
        heading = "#" * min(max(node.level + 1, 2), 6)
        lines.extend(
            [
                f"{heading} {node.title}",
                "",
                "[目标字数]",
                f"- {node.target_word_count} 字" if node.target_word_count else "- 未设置",
                "",
                "[主要来源]",
                *[f"- {item}" for item in node.main_sources],
                "",
                "[自动补充]",
                *[f"- {item}" for item in node.auto_fill],
                "",
                "[人工补充需补充]",
                *[f"- {item}" for item in node.manual_fill],
                "",
            ]
        )
        if node.special_notes:
            lines.extend(["[特殊备注]", *[f"- {item}" for item in node.special_notes], ""])
    return "\n".join(lines).strip() + "\n"


def _flat_template_nodes(template_tree: TemplateTree) -> list[dict]:
    return [
        {
            "id": node.id,
            "title": node.title,
            "level": node.level,
            "source_rules": node.source_rules,
            "auto_fill": node.auto_fill,
            "manual_fill": node.manual_fill,
            "special_notes": node.special_notes,
            "has_generation_contract": node.has_generation_contract,
            "target_word_count": node.target_word_count,
        }
        for node in iter_template_nodes(template_tree.nodes)
    ]


def _compact_toc(toc_items: list[SourceTocItem]) -> list[dict]:
    # Keep the planning prompt bounded. Full source matching happens later per chapter.
    selected = sorted(toc_items, key=lambda item: (item.char_count == 0, -item.char_count))[:180]
    return [
        {
            "section_id": item.section_id,
            "title_path": item.title_path,
            "level": item.level,
            "char_count": item.char_count,
        }
        for item in selected
    ]


def _fallback_outline(profile: ProjectProfile, template_tree: TemplateTree, toc_items: list[SourceTocItem]) -> TemplateOutlinePlan:
    valid_source_ids = {item.section_id for item in toc_items}
    source_hints = [section_id for section_id in profile.source_section_ids if section_id in valid_source_ids][:8]
    nodes: list[TemplateOutlineNode] = []
    for node in iter_template_nodes(template_tree.nodes):
        has_modules = bool(node.source_rules and node.auto_fill and node.manual_fill)
        nodes.append(
            TemplateOutlineNode(
                node_id=node.id,
                title=node.title,
                level=node.level,
                enabled=has_modules,
                source_hints=source_hints if has_modules else [],
                main_sources=node.source_rules,
                auto_fill=node.auto_fill,
                manual_fill=node.manual_fill,
                special_notes=node.special_notes,
                target_word_count=node.target_word_count,
            )
        )
    return TemplateOutlinePlan(template_id=template_tree.id, nodes=nodes)


def _clean_outline(outline: TemplateOutlinePlan, template_tree: TemplateTree, toc_items: list[SourceTocItem]) -> TemplateOutlinePlan:
    template_by_id = {node.id: node for node in iter_template_nodes(template_tree.nodes)}
    valid_source_ids = {item.section_id for item in toc_items}
    for node in outline.nodes:
        template_node = template_by_id.get(node.node_id)
        if template_node is None:
            continue
        if not template_node.has_generation_contract and not (node.main_sources or node.auto_fill or node.manual_fill or node.special_notes):
            node.enabled = False
            continue
        node.source_hints = [section_id for section_id in node.source_hints if section_id in valid_source_ids]
        if not node.main_sources:
            node.main_sources = template_node.source_rules
        if not node.auto_fill:
            node.auto_fill = template_node.auto_fill
        if not node.manual_fill:
            node.manual_fill = template_node.manual_fill
        if not node.special_notes:
            node.special_notes = template_node.special_notes
    return outline


def _apply_outline_node(node: TemplateNode, outline_by_id: dict[str, TemplateOutlineNode]) -> TemplateNode:
    patch = outline_by_id.get(node.id)
    updated = TemplateNode(
        id=node.id,
        title=node.title,
        level=node.level,
        source_rules=patch.main_sources if patch else node.source_rules,
        auto_fill=patch.auto_fill if patch else node.auto_fill,
        manual_fill=patch.manual_fill if patch else node.manual_fill,
        special_notes=patch.special_notes if patch else node.special_notes,
        target_word_count=patch.target_word_count if patch and patch.target_word_count is not None else node.target_word_count,
        children=[],
    )
    updated.children = [_apply_outline_node(child, outline_by_id) for child in node.children]
    return updated
