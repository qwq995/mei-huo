from __future__ import annotations

import re

from coalplan.application.serialization import dump_model, to_json_text
from coalplan.application.chapter_skill_library import (
    load_chapter_skills,
    match_chapter_skills,
    relevant_toc_for_expansion,
    render_outline_skill_context,
)
from coalplan.domain.documents import SourceTocItem
from coalplan.domain.documents import stable_id
from coalplan.domain.outline import (
    ChapterSummary,
    OutlineGenerationStep,
    OutlineProjectSummary,
    TemplateOutlineNode,
    TemplateOutlinePlan,
)
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
    outline.plan_source = "ai_plan"
    outline = _clean_outline(outline, template_tree, toc_items)
    outline = _ensure_skill_expansions(outline, template_tree, toc_items)
    result = TemplateOutlinePlanValidator().validate(outline, template_tree, toc_items)
    if not result.passed:
        raise ValueError("; ".join(issue.message for issue in result.issues))
    outline = summarize_outline_context(
        outline=outline,
        profile=profile,
        toc_items=toc_items,
        llm=llm,
    )
    outline = _optimize_outline_context(outline)
    outline.generation_steps = build_outline_generation_steps(outline, template_tree)
    outline.artifact_json_path = artifacts.write_text(project_id, "outline/generated_outline.json", to_json_text(dump_model(outline)))
    outline.artifact_markdown_path = artifacts.write_text(project_id, "outline/generated_outline.md", render_outline_markdown(outline))
    return outline


def build_template_outline_plan(
    *,
    profile: ProjectProfile,
    toc_items: list[SourceTocItem],
    template_tree: TemplateTree,
) -> TemplateOutlinePlan:
    outline = _fallback_outline(profile, template_tree, toc_items)
    outline.plan_source = "template"
    outline = _clean_outline(outline, template_tree, toc_items)
    outline = _ensure_skill_expansions(outline, template_tree, toc_items)
    outline = _fallback_outline_summaries(outline, profile, toc_items)
    outline = _optimize_outline_context(outline)
    outline.generation_steps = build_outline_generation_steps(outline, template_tree)
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
            "已匹配的特化 skill（只用于子章节结构扩充，不是项目事实）：",
            render_outline_skill_context(template_tree, toc_items),
            "",
            "任务：",
            "同时受目标模板和投标文档目录约束生成本项目目录规划，并为每个可生成小章节填写四个模块。",
            "",
            "输出要求：",
            "只输出 JSON，不要 Markdown，不要解释。",
            "schema：",
            '{"template_id":"string","nodes":[{"node_id":"string","title":"string","level":1,"parent_node_id":"string|null","enabled":true,"origin":"template|bid|skill|hybrid","template_anchor_id":"string","source_hints":["section_id"],"source_toc_paths":["string"],"matched_skill_keys":["string"],"main_sources":["string"],"auto_fill":["string"],"manual_fill":["string"],"special_notes":["string"],"target_word_count":800}]}',
            "",
            "规则：",
            "- 目标模板中的一级章节必须全部保留，标题、顺序和父子边界不得改变。",
            "- 模板既有节点使用原 node_id 和 origin=template。",
            "- 可以在模板章节下新增更细粒度子章节，但不得新增模板外一级章节；新增节点必须设置 parent_node_id、template_anchor_id 和 origin=bid/skill/hybrid。",
            "- 新增节点优先覆盖投标目录中的高价值施工对象、工序、质量、安全、环保和验收主题。",
            "- 面临工艺、安全、质量、环境、进度资源章节时，匹配一个特化 skill，直接采用其 outline_expansion 作为候选，再按投标目录删减和改名。",
            "- source_hints 只能引用真实 section_id。",
            "- 新增节点如没有 source_hints，只能保留为 skill 结构节点并在 manual_fill 明确证据缺口；不得写成项目事实。",
            "- main_sources 必须描述真实投标文档中可依据的章节或内容。",
            "- auto_fill 只能写模型可归纳、润色、组织的内容。",
            "- manual_fill 必须写现场、图纸、合同、审批、实测、人员设备等需人工确认项。",
            "- special_notes 仅在边界、地质、水文、施工参数、质量验收、安全风险等重难点出现；没有则为空数组。",
            "- target_word_count 为本节建议目标字数，可为 null；不得为了凑字数编造来源不支持的参数。",
        ]
    )


def summarize_outline_context(
    *,
    outline: TemplateOutlinePlan,
    profile: ProjectProfile,
    toc_items: list[SourceTocItem],
    llm: StructuredLLMClient,
) -> TemplateOutlinePlan:
    fallback = _fallback_outline_summaries(outline, profile, toc_items)
    try:
        data = llm.complete_json(
            build_outline_summary_prompt(outline=fallback, profile=profile, toc_items=toc_items),
            schema_name="OutlineContextSummary",
        )
        valid_source_ids = {item.section_id for item in toc_items}
        project_data = data.get("project_summary") or {}
        project_data["source_section_ids"] = [
            item for item in project_data.get("source_section_ids", []) if item in valid_source_ids
        ]
        project_summary = OutlineProjectSummary(**project_data)
        if project_summary.overview:
            fallback.project_summary = project_summary
        summaries = {
            str(item.get("node_id")): ChapterSummary(**item)
            for item in data.get("chapter_summaries", [])
            if item.get("node_id")
        }
        for node in fallback.nodes:
            summary = summaries.get(node.node_id)
            if summary and summary.overview:
                allowed_basis = {*node.source_hints, *node.source_toc_paths}
                summary.source_basis = [
                    item
                    for item in summary.source_basis
                    if item in allowed_basis
                ]
                node.chapter_summary = summary
    except Exception:
        pass
    return fallback


def build_outline_summary_prompt(
    *,
    outline: TemplateOutlinePlan,
    profile: ProjectProfile,
    toc_items: list[SourceTocItem],
) -> str:
    node_payload = [
        {
            "node_id": node.node_id,
            "title": node.title,
            "parent_node_id": node.parent_node_id,
            "origin": node.origin,
            "source_hints": node.source_hints,
            "source_toc_paths": node.source_toc_paths,
            "matched_skill_keys": node.matched_skill_keys,
        }
        for node in outline.nodes
        if node.enabled
    ]
    relevant_ids = {section_id for node in outline.nodes for section_id in node.source_hints}
    source_payload = [
        item
        for item in _compact_toc(toc_items)
        if item["section_id"] in relevant_ids
    ][:180]
    return "\n".join(
        [
            "你是施工组织设计目录概况生成 agent。目录树已经生成，现在只能依据投标文档目录摘要和已抽取项目画像，为整棵目录树补充简要概况。",
            "",
            "项目画像：",
            to_json_text(dump_model(profile)),
            "",
            "目录节点：",
            to_json_text(node_payload),
            "",
            "投标文档依据：",
            to_json_text(source_payload),
            "",
            "输出 JSON schema：",
            '{"project_summary":{"overview":"","construction_scope":[],"key_conditions":[],"key_methods":[],"key_risks":[],"source_section_ids":[]},"chapter_summaries":[{"node_id":"","overview":"","scope":[],"key_points":[],"source_basis":["section_id或目录路径"],"missing_information":[]}]}',
            "",
            "规则：",
            "- 概况只做简要导航，不写长正文。",
            "- 项目概况和章节概况的事实必须来自输入项目画像或投标文档依据。",
            "- 每个启用节点都返回章节概况；父章节概括其子章节覆盖范围，叶节点概括拟生成内容。",
            "- skill只决定章节组织，不是事实来源。",
            "- 无事实依据的具体参数写入 missing_information，不得猜测。",
        ]
    )


def apply_outline_to_template_tree(template_tree: TemplateTree, outline: TemplateOutlinePlan) -> TemplateTree:
    enabled = [node for node in outline.nodes if node.enabled]
    by_parent: dict[str | None, list[TemplateOutlineNode]] = {}
    for node in enabled:
        by_parent.setdefault(node.parent_node_id, []).append(node)

    def build(parent_id: str | None) -> list[TemplateNode]:
        return [_outline_node_to_template(node, children=build(node.node_id)) for node in by_parent.get(parent_id, [])]

    roots = build(None)
    return TemplateTree(id=template_tree.id, name=template_tree.name, nodes=roots)


def build_outline_generation_steps(outline: TemplateOutlinePlan, template_tree: TemplateTree) -> list[OutlineGenerationStep]:
    parent_by_id = _template_parent_map(template_tree)
    enabled_by_id = {node.node_id: node for node in outline.nodes if node.enabled}
    grouped: dict[tuple[int, str | None], list[TemplateOutlineNode]] = {}
    for node in outline.nodes:
        if not node.enabled:
            continue
        parent_id = node.parent_node_id if node.parent_node_id is not None else parent_by_id.get(node.node_id)
        if parent_id is not None and parent_id not in enabled_by_id:
            parent_id = None
        grouped.setdefault((node.level, parent_id), []).append(node)
    steps: list[OutlineGenerationStep] = []
    for (level, parent_id), nodes in sorted(grouped.items(), key=lambda item: (item[0][0], item[0][1] or "")):
        node_ids = [node.node_id for node in nodes]
        source_ids: list[str] = []
        for node in nodes:
            for source_id in node.source_hints:
                if source_id not in source_ids:
                    source_ids.append(source_id)
        step_parent = parent_id or "root"
        steps.append(
            OutlineGenerationStep(
                step_id=f"outline_level_{level}_{step_parent}",
                level=level,
                parent_node_id=parent_id,
                node_ids=node_ids,
                source_section_ids=source_ids,
                description=_outline_step_description(level=level, parent_id=parent_id, nodes=nodes),
            )
        )
    return steps


def render_outline_markdown(outline: TemplateOutlinePlan) -> str:
    lines = [
        f"# 生成目录规划：{outline.template_id}",
        "",
        "## 项目概况",
        "",
        outline.project_summary.overview or "【待基于投标文档生成】",
        "",
    ]
    for label, items in (
        ("施工范围", outline.project_summary.construction_scope),
        ("关键条件", outline.project_summary.key_conditions),
        ("主要工法", outline.project_summary.key_methods),
        ("关键风险", outline.project_summary.key_risks),
        ("概况来源", outline.project_summary.source_section_ids),
    ):
        rendered_items = [f"- {item}" for item in items] or ["- 【无】"]
        lines.extend([f"### {label}", *rendered_items, ""])
    if outline.generation_steps:
        lines.extend(["## 分层生成步骤", ""])
        for step in outline.generation_steps:
            parent = step.parent_node_id or "root"
            lines.extend(
                [
                    f"- `{step.step_id}`：level={step.level}，parent={parent}，nodes={', '.join(step.node_ids)}",
                    f"  - {step.description}",
                ]
            )
            if step.source_section_ids:
                lines.append(f"  - source_hints: {', '.join(step.source_section_ids[:12])}")
        lines.append("")
    for node in outline.nodes:
        if not node.enabled:
            continue
        heading = "#" * min(max(node.level + 1, 2), 6)
        lines.extend(
            [
                f"{heading} {node.title}",
                "",
                f"- node_id: `{node.node_id}`",
                f"- parent_node_id: `{node.parent_node_id or 'root'}`",
                f"- origin: `{node.origin}`",
                f"- matched_skills: {', '.join(node.matched_skill_keys) or '-'}",
                "",
                "[章节概况]",
                node.chapter_summary.overview or "【待基于投标文档生成】",
                *[f"- 范围：{item}" for item in node.chapter_summary.scope],
                *[f"- 要点：{item}" for item in node.chapter_summary.key_points],
                *[f"- 来源：{item}" for item in node.chapter_summary.source_basis],
                *[f"- 缺失：{item}" for item in node.chapter_summary.missing_information],
                f"- 生成职责：{node.chapter_summary.generation_role}",
                f"- 证据覆盖：{node.chapter_summary.coverage_status}",
                *[f"- 建议写作单元：{item}" for item in node.chapter_summary.writing_unit_hints],
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
    parent_map = _template_parent_map(template_tree)
    return [
        {
            "id": node.id,
            "parent_id": parent_map.get(node.id),
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


def _template_parent_map(template_tree: TemplateTree) -> dict[str, str | None]:
    mapping: dict[str, str | None] = {}

    def visit(nodes: list[TemplateNode], parent_id: str | None) -> None:
        for node in nodes:
            mapping[node.id] = parent_id
            visit(node.children, node.id)

    visit(template_tree.nodes, None)
    return mapping


def _outline_step_description(*, level: int, parent_id: str | None, nodes: list[TemplateOutlineNode]) -> str:
    titles = "、".join(node.title for node in nodes[:8])
    if len(nodes) > 8:
        titles += f" 等 {len(nodes)} 个节点"
    parent = f"父节点 `{parent_id}` 下" if parent_id else "根层"
    return f"{parent}第 {level} 层目录规划：{titles}"


def _compact_toc(toc_items: list[SourceTocItem]) -> list[dict]:
    # Keep the planning prompt bounded. Full source matching happens later per chapter.
    selected = sorted(toc_items, key=lambda item: (item.char_count == 0, -item.char_count))[:180]
    return [
        {
            "section_id": item.section_id,
            "title_path": item.title_path,
            "level": item.level,
            "char_count": item.char_count,
            "snippet": item.snippet[:300],
        }
        for item in selected
    ]


def _fallback_outline(profile: ProjectProfile, template_tree: TemplateTree, toc_items: list[SourceTocItem]) -> TemplateOutlinePlan:
    valid_source_ids = {item.section_id for item in toc_items}
    source_hints = [section_id for section_id in profile.source_section_ids if section_id in valid_source_ids][:8]
    nodes: list[TemplateOutlineNode] = []
    parent_map = _template_parent_map(template_tree)
    for node in iter_template_nodes(template_tree.nodes):
        has_modules = bool(node.source_rules and node.auto_fill and node.manual_fill)
        nodes.append(
            TemplateOutlineNode(
                node_id=node.id,
                title=node.title,
                level=node.level,
                parent_node_id=parent_map.get(node.id),
                enabled=has_modules,
                origin="template",
                template_anchor_id=node.id,
                source_hints=source_hints if has_modules else [],
                main_sources=node.source_rules,
                auto_fill=node.auto_fill,
                manual_fill=node.manual_fill,
                special_notes=node.special_notes,
                target_word_count=node.target_word_count,
            )
        )
    return TemplateOutlinePlan(template_id=template_tree.id, nodes=nodes)


def _ensure_skill_expansions(
    outline: TemplateOutlinePlan,
    template_tree: TemplateTree,
    toc_items: list[SourceTocItem],
) -> TemplateOutlinePlan:
    template_by_id = {node.id: node for node in iter_template_nodes(template_tree.nodes)}
    existing_ids = {node.node_id for node in outline.nodes}
    for parent in list(outline.nodes):
        if not parent.enabled or parent.origin != "template" or parent.level > 2:
            continue
        template_node = template_by_id.get(parent.node_id)
        if template_node is None:
            continue
        context = " ".join(
            [
                *template_node.source_rules,
                *template_node.auto_fill,
                *template_node.manual_fill,
                *template_node.special_notes,
            ]
        )
        matches = match_chapter_skills(title=parent.title, context=context, limit=1)
        if not matches:
            continue
        match = matches[0]
        parent.matched_skill_keys = [match.skill_key]
        children = [node for node in outline.nodes if node.parent_node_id == parent.node_id and node.enabled]
        existing_titles = {node.title for node in children}
        minimum_children = 5
        for expansion in match.skill.outline_expansion:
            if len(children) >= minimum_children:
                break
            if expansion.title in existing_titles:
                continue
            sources = relevant_toc_for_expansion(expansion, toc_items)
            source_paths = [" > ".join(item.title_path) for item in sources]
            node_id = stable_id("outline", outline.template_id, parent.node_id, expansion.title)
            if node_id in existing_ids:
                continue
            child = TemplateOutlineNode(
                node_id=node_id,
                title=expansion.title,
                level=min(6, parent.level + 1),
                parent_node_id=parent.node_id,
                enabled=True,
                origin="hybrid" if sources else "skill",
                template_anchor_id=parent.template_anchor_id or parent.node_id,
                source_hints=[item.section_id for item in sources],
                source_toc_paths=source_paths,
                matched_skill_keys=[match.skill_key],
                main_sources=[f"投标文档目录：{path}" for path in source_paths]
                or list(template_node.source_rules),
                auto_fill=list(match.skill.generation_rules),
                manual_fill=list(dict.fromkeys([*template_node.manual_fill, *match.skill.human_only_items])),
                special_notes=list(template_node.special_notes),
                target_word_count=700,
            )
            outline.nodes.append(child)
            children.append(child)
            existing_ids.add(node_id)
            existing_titles.add(expansion.title)
    return outline


def _fallback_outline_summaries(
    outline: TemplateOutlinePlan,
    profile: ProjectProfile,
    toc_items: list[SourceTocItem],
) -> TemplateOutlinePlan:
    valid_ids = {item.section_id for item in toc_items}
    outline.project_summary = OutlineProjectSummary(
        overview="；".join(
            item
            for item in [
                profile.project_name or "",
                profile.project_type or "",
                profile.location or "",
            ]
            if item
        ),
        construction_scope=profile.construction_scope[:8],
        key_conditions=[*profile.key_quantities[:4], *profile.schedule[:3]],
        key_methods=profile.main_methods[:8],
        key_risks=profile.risk_points[:8],
        source_section_ids=[item for item in profile.source_section_ids if item in valid_ids],
    )
    for node in outline.nodes:
        source_paths = node.source_toc_paths[:6]
        overview = f"本章围绕“{node.title}”组织"
        if source_paths:
            overview += "，主要依据投标文档中的" + "、".join(source_paths[:3])
        elif node.matched_skill_keys:
            overview += "，按匹配的特化 skill 组织结构，具体项目事实待证据映射"
        node.chapter_summary = ChapterSummary(
            overview=overview + "。",
            scope=node.auto_fill[:4],
            key_points=[*node.main_sources[:3], *node.special_notes[:2]],
            source_basis=[*node.source_hints[:6], *source_paths[:3]],
            missing_information=node.manual_fill[:6],
        )
    return outline


def _optimize_outline_context(outline: TemplateOutlinePlan) -> TemplateOutlinePlan:
    enabled = {node.node_id: node for node in outline.nodes if node.enabled}
    children_by_parent: dict[str, list[TemplateOutlineNode]] = {}
    for node in enabled.values():
        if node.parent_node_id:
            children_by_parent.setdefault(node.parent_node_id, []).append(node)
    for node in enabled.values():
        children = children_by_parent.get(node.node_id, [])
        if children:
            node.chapter_summary.generation_role = "container"
            node.chapter_summary.coverage_status = "aggregate"
            node.chapter_summary.writing_unit_hints = [child.title for child in children[:12]]
            child_scope = [child.title for child in children]
            node.chapter_summary.scope = list(dict.fromkeys([*node.chapter_summary.scope, *child_scope]))[:12]
            continue
        node.chapter_summary.generation_role = "leaf"
        if node.source_hints:
            node.chapter_summary.coverage_status = "grounded"
        elif node.origin == "skill":
            node.chapter_summary.coverage_status = "manual_required"
        else:
            node.chapter_summary.coverage_status = "mapping_required"
        node.chapter_summary.writing_unit_hints = _writing_unit_hints(node)
    return outline


def _writing_unit_hints(node: TemplateOutlineNode) -> list[str]:
    hints: list[str] = []
    for path in node.source_toc_paths:
        title = path.split(" > ")[-1].strip()
        if title and title != node.title and title not in hints:
            hints.append(title)
    for skill_key in node.matched_skill_keys:
        skill = load_chapter_skills().get(skill_key)
        if skill is None:
            continue
        for item in skill.outline_expansion:
            if item.title not in hints:
                hints.append(item.title)
    if not hints:
        hints.extend(item.rstrip("。") for item in node.auto_fill[:3] if item.strip())
    return hints[:8]


def _clean_outline(outline: TemplateOutlinePlan, template_tree: TemplateTree, toc_items: list[SourceTocItem]) -> TemplateOutlinePlan:
    outline.template_id = template_tree.id
    template_by_id = {node.id: node for node in iter_template_nodes(template_tree.nodes)}
    template_parent = _template_parent_map(template_tree)
    valid_source_ids = {item.section_id for item in toc_items}
    toc_by_id = {item.section_id: item for item in toc_items}
    ai_by_template_id = {node.node_id: node for node in outline.nodes if node.node_id in template_by_id}
    cleaned: list[TemplateOutlineNode] = []

    # Template nodes are the hard skeleton: restore omitted nodes and immutable hierarchy.
    for template_node in iter_template_nodes(template_tree.nodes):
        proposed = ai_by_template_id.get(template_node.id)
        has_modules = template_node.has_generation_contract
        node = proposed or TemplateOutlineNode(
            node_id=template_node.id,
            title=template_node.title,
            level=template_node.level,
            enabled=has_modules,
        )
        node.title = template_node.title
        node.level = template_node.level
        node.parent_node_id = template_parent.get(template_node.id)
        node.origin = "template"
        node.template_anchor_id = template_node.id
        if node.parent_node_id is None:
            node.enabled = True
        elif not has_modules and not (node.main_sources or node.auto_fill or node.manual_fill or node.special_notes):
            node.enabled = False
        node.source_hints = [
            item
            for item in node.source_hints
            if item in valid_source_ids and _outline_source_relevant(node.title, toc_by_id[item])
        ]
        node.source_toc_paths = [" > ".join(toc_by_id[item].title_path) for item in node.source_hints]
        node.main_sources = node.main_sources or template_node.source_rules
        node.auto_fill = node.auto_fill or template_node.auto_fill
        node.manual_fill = node.manual_fill or template_node.manual_fill
        node.special_notes = node.special_notes or template_node.special_notes
        node.matched_skill_keys = _skill_keys_for_title(node.title)
        cleaned.append(node)

    known_ids = {node.node_id for node in cleaned}
    dynamic_candidates = [node for node in outline.nodes if node.node_id not in template_by_id]
    pending = list(dynamic_candidates)
    id_remap: dict[str, str] = {}
    while pending:
        progressed = False
        for node in list(pending):
            if node.parent_node_id in id_remap:
                node.parent_node_id = id_remap[node.parent_node_id]
            if not node.title.strip():
                pending.remove(node)
                continue
            if node.parent_node_id not in known_ids:
                continue
            parent = next(item for item in cleaned if item.node_id == node.parent_node_id)
            anchor_id = node.template_anchor_id if node.template_anchor_id in template_by_id else parent.template_anchor_id
            if not anchor_id:
                pending.remove(node)
                continue
            original_id = node.node_id
            node.node_id = stable_id("outline", outline.template_id, node.parent_node_id, node.title)
            if node.node_id in known_ids:
                pending.remove(node)
                continue
            node.level = min(6, parent.level + 1)
            node.origin = node.origin if node.origin in {"bid", "skill", "hybrid"} else "hybrid"
            node.template_anchor_id = anchor_id
            node.source_hints = [
                item
                for item in node.source_hints
                if item in valid_source_ids and _outline_source_relevant(node.title, toc_by_id[item])
            ]
            node.source_toc_paths = [" > ".join(toc_by_id[item].title_path) for item in node.source_hints]
            direct_skill_keys = _skill_keys_for_title(node.title)
            inherited_skill_keys = [
                key
                for key in [*parent.matched_skill_keys, *_skill_keys_for_title(template_by_id[anchor_id].title)]
                if key
            ]
            expansion_owner_keys = _skill_expansion_owner_keys(node.title)
            if expansion_owner_keys and not set(expansion_owner_keys).intersection(inherited_skill_keys):
                pending.remove(node)
                progressed = True
                continue
            allowed_skill_keys = set([*direct_skill_keys, *inherited_skill_keys])
            node.matched_skill_keys = [
                key for key in _valid_skill_keys(node.matched_skill_keys) if key in allowed_skill_keys
            ]
            if not node.matched_skill_keys and direct_skill_keys:
                node.matched_skill_keys = direct_skill_keys
            anchor = template_by_id[anchor_id]
            if not node.main_sources:
                node.main_sources = (
                    [f"投标文档目录：{'；'.join(node.source_toc_paths)}"]
                    if node.source_toc_paths
                    else list(anchor.source_rules)
                )
            node.auto_fill = node.auto_fill or list(anchor.auto_fill)
            node.manual_fill = node.manual_fill or list(anchor.manual_fill)
            node.special_notes = node.special_notes or list(anchor.special_notes)
            cleaned.append(node)
            known_ids.add(node.node_id)
            id_remap[original_id] = node.node_id
            pending.remove(node)
            progressed = True
        if not progressed:
            break
    outline.nodes = cleaned
    return outline


def _valid_skill_keys(keys: list[str]) -> list[str]:
    available = load_chapter_skills()
    return [key for key in dict.fromkeys(keys) if key in available]


_OUTLINE_SOURCE_TERM_GROUPS = (
    ("工程概况", "项目概况", "工程说明", "合同工程", "工程范围", "主要内容"),
    ("水文", "气象", "洪水", "径流"),
    ("地质", "围岩", "地层", "岩性", "断层"),
    ("交通", "道路", "运输"),
    ("组织机构", "管理机构", "项目组织", "人员配置", "岗位职责"),
    ("进度", "工期", "节点", "关键线路", "施工计划"),
    ("施工布置", "总平面", "临时设施", "施工场地"),
    ("供电", "用电", "变电", "电源"),
    ("供水", "用水", "排水", "污水"),
    ("供风", "压缩空气", "空压"),
    ("通风", "排烟", "防尘", "有害气体"),
    ("地下洞室", "地下工程", "隧洞", "洞身", "泄洪洞", "溢洪洞", "交通洞"),
    ("测量", "放样", "控制网"),
    ("钻孔", "炮孔", "造孔"),
    ("装药", "爆破", "起爆", "联网", "火工品"),
    ("出渣", "装渣", "弃渣", "有用料"),
    ("支护", "锚杆", "锚喷", "喷射混凝土", "钢拱架", "小导管", "管棚"),
    ("塌方", "突涌", "不良地质", "危岩"),
    ("混凝土", "模板", "钢筋", "浇筑", "振捣", "养护"),
    ("灌浆", "制浆", "压水试验", "封孔"),
    ("金属结构", "启闭机", "闸门", "机电安装"),
    ("质量", "检验", "验收", "试验检测"),
    ("安全", "职业健康", "危险源", "应急"),
    ("环境", "水土保持", "文明施工", "环保", "固废"),
    ("防洪度汛", "施工导流", "水流控制"),
    ("编制依据", "控制目标", "管理目标", "保证与承诺"),
)


def _outline_source_relevant(title: str, item: SourceTocItem) -> bool:
    title_text = _normalize_outline_text(title)
    source_text = _normalize_outline_text(" ".join(item.title_path) + " " + item.snippet[:600])
    matched_groups = [
        group
        for group in _OUTLINE_SOURCE_TERM_GROUPS
        if any(_normalize_outline_text(term) in title_text for term in group)
    ]
    if matched_groups:
        return any(
            any(_normalize_outline_text(term) in source_text for term in group)
            for group in matched_groups
        )
    plain_title = re.sub(r"^第?[一二三四五六七八九十百0-9.]+[章节]?\s*", "", title).strip()
    terms = [
        _normalize_outline_text(term)
        for term in re.split(r"[、，,/（）()：:\s]|与|及|和", plain_title)
        if len(_normalize_outline_text(term)) >= 2
    ]
    return any(term in source_text for term in terms)


def _normalize_outline_text(value: str) -> str:
    return re.sub(r"[\s*#_\-—]+", "", value or "").lower()


def _skill_keys_for_title(title: str) -> list[str]:
    return [item.skill_key for item in match_chapter_skills(title=title, limit=1)]


def _skill_expansion_owner_keys(title: str) -> list[str]:
    normalized = _normalize_outline_text(title)
    return [
        skill.key
        for skill in load_chapter_skills().values()
        if any(_normalize_outline_text(item.title) == normalized for item in skill.outline_expansion)
    ]


def _outline_node_to_template(node: TemplateOutlineNode, *, children: list[TemplateNode]) -> TemplateNode:
    return TemplateNode(
        id=node.node_id,
        title=node.title,
        level=node.level,
        source_rules=node.main_sources,
        auto_fill=node.auto_fill,
        manual_fill=node.manual_fill,
        special_notes=node.special_notes,
        target_word_count=node.target_word_count,
        origin=node.origin,
        template_anchor_id=node.template_anchor_id,
        source_hints=node.source_hints,
        matched_skill_keys=node.matched_skill_keys,
        chapter_summary=dump_model(node.chapter_summary),
        children=children,
    )
