from __future__ import annotations

from coalplan.application.serialization import dump_model, to_json_text
from coalplan.domain.documents import MarkdownSection
from coalplan.domain.enums import TaskStatus
from coalplan.domain.generation import ChapterDraft, ChapterTask
from coalplan.domain.profile import ProjectProfile
from coalplan.domain.templates import TemplateNode
from coalplan.ports.llm import LLMClient
from coalplan.ports.repository import ArtifactRepository

from .validate_chapter import validate_chapter


MAX_SECTION_CHARS = 6000


def generate_chapter(
    *,
    project_id: str,
    node: TemplateNode,
    task: ChapterTask,
    llm: LLMClient,
    artifacts: ArtifactRepository,
    project_profile: ProjectProfile | None = None,
    selected_source_sections: list[MarkdownSection] | None = None,
    user_context: str = "",
) -> ChapterDraft:
    task.status = TaskStatus.running
    prompt = build_chapter_prompt(
        node=node,
        task=task,
        project_profile=project_profile,
        selected_source_sections=selected_source_sections or [],
        user_context=user_context,
    )
    markdown = llm.complete(prompt)
    draft = ChapterDraft(
        node_id=node.id,
        title=node.title,
        markdown=markdown,
        source_section_ids=[match.section_id for match in task.source_matches],
        source_mapping=task.source_mapping,
        missing_items=node.manual_fill,
    )
    draft = validate_chapter(draft, expected_title=node.title, source_count=len(task.source_matches))
    if draft.validation_status == TaskStatus.failed:
        task.status = TaskStatus.needs_repair
        repair_prompt = build_repair_prompt(node=node, task=task, bad_markdown=markdown)
        repaired = llm.complete(repair_prompt)
        draft.markdown = repaired
        draft = validate_chapter(draft, expected_title=node.title, source_count=len(task.source_matches))
    if draft.validation_status == TaskStatus.passed:
        task.status = TaskStatus.passed
    else:
        task.status = TaskStatus.failed
        task.error_message = "; ".join(issue.message for issue in draft.validation_issues)
    draft.artifact_path = artifacts.write_text(project_id, f"chapters/{node.id}.md", draft.markdown)
    task.draft_id = draft.id
    return draft


def build_chapter_prompt(
    *,
    node: TemplateNode,
    task: ChapterTask,
    project_profile: ProjectProfile | None,
    selected_source_sections: list[MarkdownSection],
    user_context: str = "",
) -> str:
    word_count_instruction = _word_count_instruction(task.target_word_count)
    source_lines = [
        f"- section_id: {match.section_id}；标题路径：{' > '.join(match.title_path)}；摘要：{match.snippet}"
        for match in task.source_matches
    ] or ["- 未在投标文档中识别到强匹配章节。"]
    evidence_map = _render_source_evidence(task)
    return "\n".join(
        [
            "你是施工组织设计正文生成 agent。你必须依据真实投标文档内容生成当前小章节 Markdown。",
            "严禁把缺失信息写成确定事实；严禁编造合同编号、坐标、工程量、施工参数、审批结论、监测数据或验收结论。",
            "",
            "输入一：项目概况 JSON",
            to_json_text(dump_model(project_profile)) if project_profile else "{}",
            "",
            "输入二：当前小章节模板 JSON",
            to_json_text(dump_model(node)),
            "",
            f"当前小章节标题：{node.title}",
            "",
            "## 本章目标字数",
            word_count_instruction,
            "",
            "## 模板主要来源",
            *[f"- {item}" for item in node.source_rules],
            "",
            "## 模板自动补充",
            *[f"- {item}" for item in node.auto_fill],
            "",
            "## 人工补充项",
            *[f"- {item}" for item in node.manual_fill],
            "",
            "## 特殊备注",
            *[f"- {item}" for item in node.special_notes],
            "",
            "## 已匹配来源章节摘要",
            *source_lines,
            "",
            "## 原文文段映射表（模板要求 -> 输入文档证据）",
            evidence_map,
            "",
            "## 已确认来源章节全文",
            _render_full_source_sections(selected_source_sections),
            "",
            "## 本章用户补充材料与历史版本",
            user_context or "无。",
            "",
            "任务：",
            "生成当前小章节的施工组织设计正文。正文应尽量具体，必须使用来源章节中的项目名称、工程范围、工程量、施工条件、工艺方法、质量安全环保要求等真实内容。",
            "当来源材料只支持概括性表达时，可以归纳组织；当来源材料缺少关键参数时，必须保留人工补充占位。",
            "",
            "输出要求：",
            "只输出 Markdown，不要 JSON，不要解释。",
            "必须严格包含且只包含以下二级模块：",
            f"# {node.title}",
            "## 主要来源摘要",
            "## 生成正文",
            "## 人工补充需补充",
            "如特殊备注非空，再追加：",
            "## 特殊备注",
            "",
            "正文写作规则：",
            "- 优先依据“原文文段映射表”组织正文；涉及项目事实、工程量、工艺参数、质量安全要求时，应从 evidence_id 对应原文摘录中取材。",
            "- “主要来源摘要”必须列出来源章节 section_id、标题路径和依据摘要。",
            "- “主要来源摘要”中优先写出 evidence_id、section_id、标题路径和依据摘要，便于追溯每个小章节对应的原文段落。",
            "- “生成正文”必须是可直接进入施工组织设计的小章节正文，不要写“系统依据”“可整理为”等流程说明。",
            "- 应围绕目标字数控制详略：有可靠来源时展开工艺、工程量、组织和控制措施；来源不足时用人工补充占位，不得为了达到字数编造事实。",
            "- 优先写成完整段落；需要表达工程量、范围、工艺、控制目标时可使用表格或条列。",
            "- 所有数字、单位、工程量和专有名词必须来自来源章节；不能确定的写为 `【需人工补充：...】`。",
            "- 不得新增大章节，不得输出模板外模块名。",
        ]
    )


def build_repair_prompt(*, node: TemplateNode, task: ChapterTask, bad_markdown: str) -> str:
    return "\n".join(
        [
            "你是 Markdown 格式修复 agent。你只修复格式，不新增事实。",
            "",
            f"期望标题：{node.title}",
            "",
            "本章目标字数：",
            _word_count_instruction(task.target_word_count),
            "",
            "必须保留的人工补充项：",
            *[f"- {item}" for item in node.manual_fill],
            "",
            "来源片段：",
            *[f"- section_id: {match.section_id}；标题路径：{' > '.join(match.title_path)}；摘要：{match.snippet}" for match in task.source_matches],
            "",
            "原文文段映射表：",
            _render_source_evidence(task),
            "",
            "原始输出：",
            bad_markdown,
            "",
            "输出要求：",
            "只输出 Markdown。",
            "必须包含：",
            f"# {node.title}",
            "## 主要来源摘要",
            "## 生成正文",
            "## 人工补充需补充",
            "",
            "规则：",
            "- 保留原文中可依据来源的内容。",
            "- 删除 JSON、解释性话术、模板外标题。",
            "- 缺失人工补充项必须用 `【需人工补充：...】` 补齐。",
        ]
    )


def _render_full_source_sections(sections: list[MarkdownSection]) -> str:
    if not sections:
        return "未选择到可靠来源章节。"
    blocks: list[str] = []
    for section in sections:
        title_path = " > ".join(section.title_path)
        content = section.content.strip() or "（本章节无正文内容）"
        if len(content) > MAX_SECTION_CHARS:
            content = content[:MAX_SECTION_CHARS].rstrip() + "\n【来源章节已截断：后续内容未纳入本次提示词】"
        blocks.append(
            "\n".join(
                [
                    f"### section_id: {section.id}",
                    f"标题路径：{title_path}",
                    "正文：",
                    content,
                ]
            )
        )
    return "\n\n---\n\n".join(blocks)


def _render_source_evidence(task: ChapterTask) -> str:
    mapping = task.source_mapping
    if mapping is None or not mapping.evidence:
        return "未抽取到细粒度原文证据；只能依据已匹配来源章节摘要和全文谨慎生成。"
    lines: list[str] = []
    for span in mapping.evidence:
        title_path = " > ".join(span.title_path)
        line_range = ""
        if span.start_line is not None and span.end_line is not None:
            line_range = f"L{span.start_line}-L{span.end_line}"
        terms = "、".join(span.matched_terms) if span.matched_terms else "无显式关键词"
        lines.extend(
            [
                f"### evidence_id: {span.evidence_id}",
                f"- section_id: {span.section_id}",
                f"- 标题路径: {title_path}",
                f"- 行号范围: {line_range or 'unknown'}",
                f"- 用途: {span.usage}",
                f"- 对应模板模块: {span.template_module}",
                f"- 匹配词: {terms}",
                f"- 匹配理由: {span.reason or '作为本节来源证据'}",
                f"- 置信度: {span.confidence}",
                "- 原文摘录:",
                "```text",
                span.quote.strip(),
                "```",
                "",
            ]
        )
    return "\n".join(lines).strip()


def _word_count_instruction(target_word_count: int | None) -> str:
    if not target_word_count:
        return "未设置固定目标字数；请按来源材料详略自然展开，避免空泛。"
    lower = max(150, int(target_word_count * 0.85))
    upper = int(target_word_count * 1.2)
    return f"目标约 {target_word_count} 字，允许约 {lower}-{upper} 字范围内浮动；不得为了凑字数编造来源未支持的信息。"
