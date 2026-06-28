from __future__ import annotations

from coalplan.application.serialization import dump_model, to_json_text
from coalplan.domain.documents import MarkdownSection
from coalplan.domain.enums import TaskStatus
from coalplan.domain.generation import ChapterDraft, ChapterTask
from coalplan.domain.generation_control import ChapterGenerationPolicy, EvidenceUtilizationAudit
from coalplan.domain.profile import ProjectProfile
from coalplan.domain.templates import TemplateNode
from coalplan.domain.validation import ValidationIssue
from coalplan.ports.llm import LLMClient
from coalplan.ports.repository import ArtifactRepository

from .chapter_writing_guidance import guidance_for_node, render_writing_guidance
from .evidence_utilization import audit_evidence_utilization, extract_required_source_facts
from .generation_metadata_audit import audit_version_generation_metadata
from .validate_chapter import validate_chapter
from .word_count_targets import count_words
from .writing_pattern_library import match_patterns_for_text, render_pattern_matches_for_prompt


MAX_SECTION_CHARS = 3000


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
    required_fact_hints: list[str] | None = None,
    generation_policy: ChapterGenerationPolicy | None = None,
) -> ChapterDraft:
    task.status = TaskStatus.running
    prompt = build_chapter_prompt(
        node=node,
        task=task,
        project_profile=project_profile,
        selected_source_sections=selected_source_sections or [],
        user_context=user_context,
        required_fact_hints=required_fact_hints or [],
        generation_policy=generation_policy,
    )
    markdown = llm.complete(prompt)
    if _exceeds_word_budget(markdown, task.target_word_count):
        markdown = llm.complete(
            build_word_budget_repair_prompt(
                node=node,
                task=task,
                overlong_markdown=markdown,
                required_fact_hints=required_fact_hints or [],
            )
        )
    draft = ChapterDraft(
        node_id=node.id,
        title=node.title,
        markdown=markdown,
        source_section_ids=[match.section_id for match in task.source_matches],
        source_mapping=task.source_mapping,
        missing_items=node.manual_fill,
        generation_metadata=build_generation_metadata(node=node, task=task, generation_policy=generation_policy),
    )
    draft = validate_chapter(draft, expected_title=node.title, source_count=len(task.source_matches))
    if draft.validation_status == TaskStatus.failed:
        task.status = TaskStatus.needs_repair
        repair_prompt = build_repair_prompt(node=node, task=task, bad_markdown=markdown, required_fact_hints=required_fact_hints or [])
        repaired = llm.complete(repair_prompt)
        draft.markdown = repaired
        draft = validate_chapter(draft, expected_title=node.title, source_count=len(task.source_matches))
    draft.evidence_audit = audit_evidence_utilization(
        node=node,
        markdown=draft.markdown,
        evidence=task.source_mapping.evidence if task.source_mapping else [],
        manual_items=node.manual_fill,
        required_fact_hints=required_fact_hints or [],
    )
    if draft.validation_status == TaskStatus.passed and _evidence_audit_requires_revision(draft.evidence_audit):
        issue_codes = ", ".join(issue.code for issue in draft.evidence_audit.issues) if draft.evidence_audit else ""
        draft.validation_status = TaskStatus.needs_repair
        draft.validation_issues.append(
            ValidationIssue(
                code="evidence_utilization_requires_revision",
                message=f"Mapped source evidence was not sufficiently absorbed by the generated chapter: {issue_codes}",
                severity="warning",
            )
        )
    metadata_audit = audit_version_generation_metadata({"markdown": draft.markdown, "generation_metadata": draft.generation_metadata})
    draft.generation_metadata["generation_metadata_audit"] = metadata_audit
    if draft.validation_status == TaskStatus.passed and _metadata_audit_requires_revision(metadata_audit):
        issue_count = metadata_audit.get("metrics", {}).get("actionable_count", 0)
        draft.validation_status = TaskStatus.needs_repair
        draft.validation_issues.append(
            ValidationIssue(
                code="writing_pattern_requires_revision",
                message=(
                    "Generated chapter did not satisfy local construction-plan writing-pattern requirements; "
                    f"actionable pattern issue count={issue_count}."
                ),
                severity="warning",
            )
        )
    if draft.validation_status == TaskStatus.passed:
        task.status = TaskStatus.passed
    elif draft.validation_status == TaskStatus.needs_repair:
        task.status = TaskStatus.needs_repair
        task.error_message = "; ".join(issue.message for issue in draft.validation_issues)
    else:
        task.status = TaskStatus.failed
        task.error_message = "; ".join(issue.message for issue in draft.validation_issues)
    draft.artifact_path = artifacts.write_text(project_id, f"chapters/{node.id}.md", draft.markdown)
    artifacts.write_text(project_id, f"chapters/{node.id}.generation_metadata.json", to_json_text(draft.generation_metadata))
    task.draft_id = draft.id
    return draft


def _evidence_audit_requires_revision(audit: EvidenceUtilizationAudit | None) -> bool:
    if audit is None:
        return False
    return any(
        issue.suggested_action in {"regenerate", "remap_sources", "expand_subsections", "repair_format"}
        for issue in audit.issues
    )


def _metadata_audit_requires_revision(audit: dict | None) -> bool:
    if not audit:
        return False
    card_audits = audit.get("prompt_card_audits") or []
    if not card_audits:
        return False
    primary_card = card_audits[0]
    if primary_card.get("suggested_action") != "regenerate":
        return False
    coverage = primary_card.get("coverage_ratio")
    if coverage is None or float(coverage) <= 0.25:
        return True
    return False


def build_chapter_prompt(
    *,
    node: TemplateNode,
    task: ChapterTask,
    project_profile: ProjectProfile | None,
    selected_source_sections: list[MarkdownSection],
    user_context: str = "",
    required_fact_hints: list[str] | None = None,
    generation_policy: ChapterGenerationPolicy | None = None,
) -> str:
    word_count_instruction = _word_count_instruction(task.target_word_count)
    source_lines = [
        f"- section_id: {match.section_id}；标题路径：{' > '.join(match.title_path)}；摘要：{match.snippet}"
        for match in task.source_matches
    ] or ["- 未在投标文档中识别到强匹配章节。"]
    evidence_map = _render_source_evidence(task)
    required_source_facts = _render_required_source_facts(task)
    feedback_required_facts = _render_feedback_required_facts(required_fact_hints or [])
    policy_context = _render_generation_policy(generation_policy)
    guidance = guidance_for_node(node)
    writing_guidance = render_writing_guidance(guidance)
    local_pattern = render_pattern_matches_for_prompt(_node_pattern_text(node), primary_key=guidance.pattern_key)
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
            "## 生成控制策略",
            policy_context,
            "",
            "## 施组写作模式参考",
            writing_guidance,
            "",
            "## 本地施组模式库规则",
            local_pattern or "无。",
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
            "## required_source_facts（必须优先写入生成正文的原文事实）",
            required_source_facts,
            "",
            "## quality_feedback_required_facts（质量审计要求本次必须承接的事实）",
            feedback_required_facts,
            "",
            "## 已确认来源章节全文",
            _render_full_source_sections(selected_source_sections, target_word_count=task.target_word_count),
            "",
            "## 本章用户补充材料与历史版本",
            user_context or "无。",
            "",
            "任务：",
            "生成当前小章节的施工组织设计正文。正文应尽量具体，必须使用来源章节中的项目名称、工程范围、工程量、施工条件、工艺方法、质量安全环保要求等真实内容。",
            "本地施组样本只用于学习目录组织、章节展开顺序、工程/安全/质量/环保等要点覆盖方式；不得追求人类参考文段逐字一致，也不得从参考模式中迁移当前项目没有来源支持的事实。",
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
            "- 先按“本地施组模式库规则”判断本章应该覆盖哪些组织要点，如对象、范围、工艺流程、资源条件、质量控制、安全风险、环保文明、检查验收、资料闭环等；再用当前项目的来源证据填充这些要点。",
            "- 本地施组样本中的高频标题和写法只作为目录与要点组织参考，不作为事实来源；不要为了接近人类参考文段而扩写无证据内容。",
            "- 参考“施组写作模式参考”的推荐展开顺序组织正文，但不得新增固定输出模块；这些只是写作骨架，不是事实来源。",
            "- 优先依据“原文文段映射表”组织正文；涉及项目事实、工程量、工艺参数、质量安全要求时，应从 evidence_id 对应原文摘录中取材。",
            "- `required_source_facts` 中列出的数字、单位、日期、规范编号、施工参数和工艺控制点必须优先写入“生成正文”；确因章节范围不适用而不写时，必须在“人工补充需补充”说明原因。",
            "- `quality_feedback_required_facts` 来自上一轮质量审计和 trace 诊断；若当前来源章节支持，必须写入“生成正文”，确属本章不适用时必须在“人工补充需补充”逐条说明。",
            "- “主要来源摘要”必须列出来源章节 section_id、标题路径和依据摘要。",
            "- “主要来源摘要”中优先写出 evidence_id、section_id、标题路径和依据摘要，便于追溯每个小章节对应的原文段落。",
            "- “生成正文”必须是可直接进入施工组织设计的小章节正文，不要写“系统依据”“可整理为”等流程说明。",
            "- 应围绕目标字数控制详略：有可靠来源时展开工艺、工程量、组织和控制措施；来源不足时用人工补充占位，不得为了达到字数编造事实。",
            "- 必须遵守“生成控制策略”：detail_level 决定展开深度，source_subtopics/required_subtopics 是正文内部展开顺序；如策略要求拆小节，应优先围绕这些小节写，而不是压缩成泛泛一段。",
            "- 优先写成完整段落；需要表达工程量、范围、工艺、控制目标时可使用表格或条列。",
            "- 所有数字、单位、工程量和专有名词必须来自来源章节；不能确定的写为 `【需人工补充：...】`。",
            "- 不得新增大章节，不得输出模板外模块名。",
        ]
    )


def build_generation_metadata(
    *,
    node: TemplateNode,
    task: ChapterTask,
    generation_policy: ChapterGenerationPolicy | None = None,
) -> dict:
    guidance = guidance_for_node(node)
    pattern_text = _node_pattern_text(node)
    local_matches = match_patterns_for_text(pattern_text, limit=3)
    selected_pattern_keys: list[str] = []
    if guidance.pattern_key:
        selected_pattern_keys.append(guidance.pattern_key)
    selected_pattern_keys.extend(match.pattern_key for match in local_matches)
    if generation_policy and generation_policy.writing_pattern_matches:
        selected_pattern_keys.extend(generation_policy.writing_pattern_matches)
    selected_pattern_keys = list(dict.fromkeys(selected_pattern_keys))
    return {
        "node_id": node.id,
        "title": node.title,
        "target_word_count": task.target_word_count,
        "source_section_ids": [match.section_id for match in task.source_matches],
        "writing_guidance": dump_model(guidance),
        "local_pattern_matches": [dump_model(match) for match in local_matches],
        "selected_pattern_keys": selected_pattern_keys,
        "generation_policy": dump_model(generation_policy) if generation_policy else None,
        "pattern_evidence_scope": (
            "Local construction-plan patterns are structural guidance only; project facts must come from mapped "
            "section_id/evidence_id, user supplements, or manual placeholders."
        ),
        "prompt_sections": [
            "施工组织写作模式参考",
            "本地施组模式库规划",
            "生成控制策略",
            "原文文段映射表",
            "required_source_facts",
        ],
        "non_factual_pattern_rules": [
            "Use corpus patterns to decide subsection order, key point coverage, and control-loop shape.",
            "Do not copy human-reference wording or transfer unsupported project facts from the pattern library.",
            "Keep missing drawings, approvals, final parameters, site measurements, personnel/equipment lists, and acceptance conclusions as manual placeholders unless source evidence supports them.",
        ],
    }


def build_repair_prompt(*, node: TemplateNode, task: ChapterTask, bad_markdown: str, required_fact_hints: list[str] | None = None) -> str:
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
            "质量反馈要求必须承接的事实：",
            _render_feedback_required_facts(required_fact_hints or []),
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
            "- 质量反馈要求必须承接的事实不得删除；如无法写入正文，必须在 `## 人工补充需补充` 中说明原因。",
        ]
    )


def build_word_budget_repair_prompt(
    *,
    node: TemplateNode,
    task: ChapterTask,
    overlong_markdown: str,
    required_fact_hints: list[str] | None = None,
) -> str:
    return "\n".join(
        [
            "你是施工组织设计章节压缩 agent。你只压缩篇幅、整理层级，不新增事实，不删除必要的人工补充占位。",
            "",
            f"章节标题：{node.title}",
            "",
            "目标字数控制：",
            _word_count_instruction(task.target_word_count),
            "",
            "必须保留的人工补充项：",
            *[f"- {item}" for item in node.manual_fill],
            "",
            "必须尽量保留的质量反馈事实：",
            _render_feedback_required_facts(required_fact_hints or []),
            "",
            "已生成但超长的 Markdown：",
            overlong_markdown,
            "",
            "输出要求：",
            "只输出压缩后的 Markdown，不要解释。",
            "必须保留且只保留以下二级模块：",
            f"# {node.title}",
            "## 主要来源摘要",
            "## 生成正文",
            "## 人工补充需补充",
            "如原文存在必要特殊备注，可保留：",
            "## 特殊备注",
            "",
            "压缩规则：",
            "- 主要来源摘要最多 6 条，每条只写 section_id/evidence_id、标题路径和一句依据摘要。",
            "- 生成正文优先保留本节标题最相关的工艺流程、控制要点、质量安全环保措施和验收记录要求。",
            "- 删除来源全文复述、重复解释、泛泛表态和与本节标题关系弱的段落。",
            "- 数字、单位、规范编号、施工参数只能保留原文已经出现的内容；不确定信息写为 `【需人工补充：...】`。",
            "- 内部小标题不超过 5 个；人工补充需补充不超过 6 条。",
        ]
    )


def _render_full_source_sections(sections: list[MarkdownSection], *, target_word_count: int | None = None) -> str:
    if not sections:
        return "未选择到可靠来源章节。"
    blocks: list[str] = []
    section_limit = _section_char_limit(target_word_count)
    max_sections = _max_full_source_sections(target_word_count)
    for section in sections[:max_sections]:
        title_path = " > ".join(section.title_path)
        content = section.content.strip() or "（本章节无正文内容）"
        if len(content) > section_limit:
            content = content[:section_limit].rstrip() + "\n【来源章节已截断：后续内容未纳入本次提示词】"
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
    if len(sections) > max_sections:
        blocks.append(f"【已按目标字数限幅省略 {len(sections) - max_sections} 个低优先级来源章节；完整映射仍见 source_mapping 记录。】")
    return "\n\n---\n\n".join(blocks)


def _section_char_limit(target_word_count: int | None) -> int:
    if not target_word_count:
        return MAX_SECTION_CHARS
    if target_word_count <= 900:
        return 1600
    if target_word_count <= 1400:
        return 2200
    if target_word_count <= 2200:
        return 2800
    return MAX_SECTION_CHARS


def _max_full_source_sections(target_word_count: int | None) -> int:
    if not target_word_count:
        return 10
    if target_word_count <= 900:
        return 5
    if target_word_count <= 1400:
        return 6
    if target_word_count <= 2200:
        return 8
    return 10


def _node_pattern_text(node: TemplateNode) -> str:
    return " ".join(
        [
            node.title,
            *node.source_rules,
            *node.auto_fill,
            *node.manual_fill,
            *node.special_notes,
        ]
    )


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


def _render_required_source_facts(task: ChapterTask) -> str:
    mapping = task.source_mapping
    if mapping is None or not mapping.evidence:
        return "无。"
    facts = extract_required_source_facts(mapping.evidence)
    if not facts:
        return "无。"
    lines: list[str] = []
    for fact in facts:
        token_text = "、".join(fact.tokens) if fact.tokens else "-"
        lines.append(
            f"- fact_id: {fact.fact_id}；evidence_id: {fact.evidence_id}；section_id: {fact.section_id}；"
            f"type: {fact.fact_type}；tokens: {token_text}；fact: {fact.text}；要求: {fact.reason}"
        )
    return "\n".join(lines)


def _render_feedback_required_facts(facts: list[str]) -> str:
    if not facts:
        return "无。"
    return "\n".join(f"- {fact}" for fact in facts)


def _render_generation_policy(policy: ChapterGenerationPolicy | None) -> str:
    if policy is None:
        return "未提供控制策略；按模板、来源映射和目标字数自然展开。"
    lines = [
        f"- detail_level: {policy.detail_level}",
        f"- split_required: {policy.split_required}",
        f"- max_source_matches: {policy.max_source_matches}",
        f"- max_evidence_spans: {policy.max_evidence_spans}",
    ]
    if policy.writing_pattern_key:
        lines.append(f"- writing_pattern_key: {policy.writing_pattern_key}")
    if policy.writing_pattern_matches:
        lines.append("- writing_pattern_matches: " + ", ".join(policy.writing_pattern_matches))
    if policy.source_subtopics:
        lines.append("- source_subtopics（来自输入目录，可作为正文内部展开顺序）:")
        lines.extend(f"  - {item}" for item in policy.source_subtopics[:12])
    if policy.required_subtopics:
        lines.append("- required_subtopics（本类章节常见必要小节）:")
        lines.extend(f"  - {item}" for item in policy.required_subtopics[:12])
    if policy.pattern_required_source_facts:
        lines.append("- pattern_required_source_facts（生成前应优先从来源中寻找）:")
        lines.extend(f"  - {item}" for item in policy.pattern_required_source_facts[:12])
    if policy.pattern_human_only_items:
        lines.append("- pattern_human_only_items（不得由模型编造）:")
        lines.extend(f"  - {item}" for item in policy.pattern_human_only_items[:12])
    if policy.pattern_prompt_cards:
        lines.append("- pattern_prompt_cards:")
        lines.append(_render_policy_prompt_cards(policy.pattern_prompt_cards))
    if policy.reason:
        lines.append(f"- reason: {policy.reason}")
    return "\n".join(lines)


def _render_policy_prompt_cards(cards: list[dict]) -> str:
    blocks: list[str] = []
    for card in cards[:3]:
        lines = [f"  - pattern_key: {card.get('pattern_key') or '-'}"]
        if card.get("matched_terms"):
            lines.append("    matched_terms: " + ", ".join(str(item) for item in card.get("matched_terms", [])[:8]))
        for label in (
            "organization_policy",
            "source_mapping_requirements",
            "detail_design_rules",
            "generation_moves",
            "human_only_items",
            "revision_checks",
        ):
            values = [str(item) for item in card.get(label, [])[:6]]
            if not values:
                continue
            lines.append(f"    {label}:")
            lines.extend(f"      - {item}" for item in values)
        blocks.append("\n".join(lines))
    return "\n".join(blocks)


def _word_count_instruction(target_word_count: int | None) -> str:
    if not target_word_count:
        return "未设置固定目标字数；请按来源材料详略自然展开，避免空泛。"
    lower = max(150, int(target_word_count * 0.85))
    upper = int(target_word_count * 1.15)
    hard_upper = _hard_word_limit(target_word_count)
    return (
        f"目标约 {target_word_count} 字，建议控制在 {lower}-{upper} 字，硬上限 {hard_upper} 字"
        "（含主要来源摘要、生成正文、人工补充需补充和特殊备注）。"
        "若来源证据很多，只筛选与本节标题最相关的事实，不得复述来源全文；"
        "主要来源摘要最多 6 条、每条不超过 60 字；生成正文内部小标题不超过 5 个；"
        "人工补充需补充最多 6 条。宁可少写并保留人工占位，也不要为了展开篇幅编造或堆砌事实。"
    )


def _hard_word_limit(target_word_count: int | None) -> int | None:
    if not target_word_count:
        return None
    return max(250, int(target_word_count * 1.35))


def _exceeds_word_budget(markdown: str, target_word_count: int | None) -> bool:
    hard_limit = _hard_word_limit(target_word_count)
    if hard_limit is None:
        return False
    return count_words(markdown) > hard_limit
