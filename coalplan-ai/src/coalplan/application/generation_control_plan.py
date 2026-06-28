from __future__ import annotations

from coalplan.application.writing_pattern_library import build_pattern_prompt_card, match_patterns_for_text, pattern_for_key
from coalplan.domain.documents import SourceTocItem, stable_id
from coalplan.domain.generation_control import (
    ChapterGenerationPolicy,
    GenerationControlPlan,
    OutlineCoverageItem,
    RevisionTrigger,
)
from coalplan.domain.templates import TemplateNode, TemplateTree, iter_template_nodes


REQUIRED_CONSTRUCTION_TOPICS: list[tuple[str, tuple[str, ...]]] = [
    ("编制依据", ("编制依据", "编制说明", "编制原则")),
    ("工程概况", ("工程概况", "工程概述", "建设规模", "工程范围")),
    ("施工条件", ("地质", "水文", "气象", "交通", "施工条件")),
    ("重难点分析", ("重点", "难点", "特点", "风险")),
    ("施工部署", ("施工部署", "施工组织", "组织机构", "施工布置原则")),
    ("施工总平面与临建", ("总平面", "平面布置", "临建", "营地", "供水", "供电", "通讯")),
    ("施工准备", ("施工准备", "技术准备", "现场准备", "材料准备", "设备准备")),
    ("进度计划", ("进度", "工期", "关键线路", "节点")),
    ("资源配置", ("机械", "设备", "劳动力", "材料", "资源配置")),
    ("主要施工技术方案", ("施工方案", "施工工艺", "技术要求", "主要施工")),
    ("质量管理", ("质量", "检验", "试验", "验收", "过程控制")),
    ("安全管理", ("安全", "职业健康", "危险源", "安全生产")),
    ("环境保护", ("环保", "环境保护", "水保", "绿色施工")),
    ("文明施工", ("文明施工", "标准化", "现场管理")),
    ("应急与防灾", ("应急", "防洪", "度汛", "消防", "防灾")),
    ("成果与附件", ("竣工", "成果", "资料", "附件", "移交")),
]

DEEP_DETAIL_TERMS = (
    "混凝土",
    "灌浆",
    "支护",
    "锚杆",
    "钻孔",
    "注水",
    "覆盖",
    "封堵",
    "开挖",
    "洞室",
    "爆破",
    "管网",
    "焊接",
    "安装",
    "调试",
)

QUALITY_GATE_TERMS = ("质量", "安全", "环保", "文明", "应急", "进度", "验收", "测量", "试验")

NON_SPLIT_CONTEXT_TERMS = (
    "概况",
    "概述",
    "位置",
    "交通",
    "现状",
    "工程量",
    "进度",
    "成果",
    "编制",
    "依据",
    "原则",
    "目标",
    "组织",
    "部署",
)


def build_generation_control_plan(
    *,
    template_tree: TemplateTree,
    toc_items: list[SourceTocItem],
    project_id: str | None = None,
) -> GenerationControlPlan:
    nodes = iter_template_nodes(template_tree.nodes)
    coverage = [_coverage_for_topic(topic, terms, nodes, toc_items) for topic, terms in REQUIRED_CONSTRUCTION_TOPICS]
    policies = [_chapter_policy(node, toc_items) for node in nodes if node.has_generation_contract]
    triggers = _revision_triggers(coverage, policies)
    return GenerationControlPlan(
        project_id=project_id,
        outline_coverage=coverage,
        chapter_policies=policies,
        revision_triggers=triggers,
    )


def render_generation_control_plan(plan: GenerationControlPlan) -> str:
    lines = ["# Generation Control Plan", ""]
    lines.extend(["## Outline Coverage", ""])
    for item in plan.outline_coverage:
        lines.append(f"- {item.topic}: {item.status}；nodes={', '.join(item.matched_node_ids) or '-'}；sources={', '.join(item.matched_source_section_ids[:5]) or '-'}")
    lines.extend(["", "## Chapter Policies", ""])
    for policy in plan.chapter_policies:
        split = "split" if policy.split_required else "single"
        lines.append(
            f"- `{policy.node_id}` {policy.title}: {policy.detail_level}/{split}, "
            f"matches={policy.max_source_matches}, evidence={policy.max_evidence_spans}, "
            f"target={policy.target_word_count or '-'}"
        )
        if policy.writing_pattern_matches:
            lines.append(f"  - writing_patterns: {', '.join(policy.writing_pattern_matches)}")
        if policy.pattern_required_source_facts:
            lines.append(f"  - pattern_required_source_facts: {', '.join(policy.pattern_required_source_facts[:12])}")
        if policy.pattern_prompt_cards:
            lines.append("  - pattern_prompt_cards: " + ", ".join(str(card.get("pattern_key")) for card in policy.pattern_prompt_cards[:3]))
        if policy.source_subtopics:
            lines.append(f"  - source_subtopics: {', '.join(policy.source_subtopics[:12])}")
    lines.extend(["", "## Revision Triggers", ""])
    if not plan.revision_triggers:
        lines.append("- none")
    for trigger in plan.revision_triggers:
        lines.append(f"- [{trigger.severity}] {trigger.title}: {trigger.action}；{trigger.reason}")
    return "\n".join(lines).strip() + "\n"


def build_outline_repair_proposal_nodes(
    *,
    plan: GenerationControlPlan,
    toc_items: list[SourceTocItem],
    existing_node_ids: set[str] | None = None,
    start_sort_order: int = 1000,
) -> list[dict]:
    existing_node_ids = existing_node_ids or set()
    toc_by_id = {item.section_id: item for item in toc_items}
    nodes: list[dict] = []
    order = start_sort_order
    for item in plan.outline_coverage:
        if item.status != "missing" or not item.matched_source_section_ids:
            continue
        node_id = stable_id("ctrlnode", item.topic)
        if node_id in existing_node_ids:
            continue
        source_titles = [_toc_title(toc_by_id[section_id]) for section_id in item.matched_source_section_ids if section_id in toc_by_id]
        profile = _topic_profile(item.topic)
        nodes.append(
            {
                "__action": "create",
                "node_id": node_id,
                "parent_id": None,
                "title": profile["title"],
                "level": 1,
                "sort_order": order,
                "enabled": True,
                "source_rules": [
                    f"控制计划识别到输入文档中存在“{item.topic}”相关来源，应在施组目录中承接。",
                    *[f"{title}" for title in source_titles[:6]],
                ],
                "auto_fill": profile["auto_fill"],
                "manual_fill": profile["manual_fill"],
                "special_notes": profile["special_notes"],
                "target_word_count": profile["target_word_count"],
            }
        )
        order += 10
    return nodes


def build_subsection_proposal_nodes(
    *,
    plan: GenerationControlPlan,
    parent_node: TemplateNode,
    existing_child_titles: set[str] | None = None,
    start_sort_order: int = 100,
) -> list[dict]:
    existing_child_titles = existing_child_titles or set()
    policy = next((item for item in plan.chapter_policies if item.node_id == parent_node.id), None)
    if policy is None or not policy.split_required:
        return []
    subtopics = policy.source_subtopics or policy.required_subtopics or _fallback_subtopics(parent_node.title)
    nodes: list[dict] = []
    order = start_sort_order
    per_node_target = _subsection_target(policy.target_word_count, len(subtopics))
    for subtopic in subtopics:
        title = _subsection_title(parent_node.title, subtopic)
        if title in existing_child_titles:
            continue
        profile = _subtopic_profile(parent_node.title, subtopic, per_node_target)
        nodes.append(
            {
                "__action": "create",
                "node_id": stable_id("subnode", parent_node.id, subtopic),
                "parent_id": parent_node.id,
                "title": title,
                "level": parent_node.level + 1,
                "sort_order": order,
                "enabled": True,
                "source_rules": profile["source_rules"],
                "auto_fill": profile["auto_fill"],
                "manual_fill": profile["manual_fill"],
                "special_notes": profile["special_notes"],
                "target_word_count": profile["target_word_count"],
            }
        )
        order += 10
    return nodes


def build_project_subsection_proposal_nodes(
    *,
    plan: GenerationControlPlan,
    template_tree: TemplateTree,
    existing_outline_nodes: list[dict] | None = None,
) -> list[dict]:
    existing_outline_nodes = existing_outline_nodes or []
    nodes_by_id = {node.id: node for node in iter_template_nodes(template_tree.nodes)}
    existing_children_by_parent: dict[str, list[dict]] = {}
    for item in existing_outline_nodes:
        parent_id = item.get("parent_id")
        if parent_id:
            existing_children_by_parent.setdefault(parent_id, []).append(item)

    preview_nodes: list[dict] = []
    seen_ids = {item.get("node_id") for item in existing_outline_nodes}
    for policy in plan.chapter_policies:
        if not policy.split_required:
            continue
        parent = nodes_by_id.get(policy.node_id)
        if parent is None:
            continue
        existing_children = existing_children_by_parent.get(parent.id, [])
        start_sort_order = (max([int(item.get("sort_order") or 0) for item in existing_children] or [0]) + 10)
        children = build_subsection_proposal_nodes(
            plan=plan,
            parent_node=parent,
            existing_child_titles={item["title"] for item in existing_children if item.get("title")},
            start_sort_order=start_sort_order,
        )
        for child in children:
            if child["node_id"] in seen_ids:
                continue
            seen_ids.add(child["node_id"])
            preview_nodes.append(child)
    return preview_nodes


def _coverage_for_topic(
    topic: str,
    terms: tuple[str, ...],
    nodes: list[TemplateNode],
    toc_items: list[SourceTocItem],
) -> OutlineCoverageItem:
    matched_nodes = [node.id for node in nodes if _contains_any(node.title, terms)]
    matched_sources = [item.section_id for item in toc_items if _contains_any(" ".join(item.title_path), terms)]
    if matched_nodes and matched_sources:
        status = "covered"
        reason = "模板目录和输入目录均有对应主题。"
    elif matched_sources and not matched_nodes:
        status = "missing"
        reason = "输入文档存在该主题，但当前模板目录没有承接节点，建议扩展目录或并入相邻节点。"
    elif matched_nodes and not matched_sources:
        status = "partial"
        reason = "模板有该主题，但输入目录未识别到强来源，生成时应要求人工补充或降级处理。"
    else:
        status = "not_applicable"
        reason = "模板和输入目录均未识别该主题。"
    return OutlineCoverageItem(
        topic=topic,
        status=status,
        matched_node_ids=matched_nodes,
        matched_source_section_ids=matched_sources[:12],
        reason=reason,
    )


def _topic_profile(topic: str) -> dict:
    profiles = {
        "编制依据": {
            "title": "编制依据及原则",
            "auto_fill": [
                "依据投标文件、设计文件、合同文件、国家及行业规范、地方管理要求，归纳本施工组织设计的编制依据、适用范围和编制原则。"
            ],
            "manual_fill": [
                "【需人工补充：最终合同文件编号、设计图纸版本、审批文件、现行规范清单及地方主管部门要求。】"
            ],
            "special_notes": [
                "规范、图纸、合同编号和审批结论必须以正式资料核验，不得由模型补造。"
            ],
            "target_word_count": 900,
        },
        "重难点分析": {
            "title": "项目特点及施工重难点分析",
            "auto_fill": [
                "结合工程范围、地形地质、水文气象、施工条件、核心工艺、质量安全环保要求，归纳项目特点、重难点和对应组织措施。"
            ],
            "manual_fill": [
                "【需人工补充：现场复勘结论、设计交底重难点、专家论证意见、重大风险清单和专项方案审批要求。】"
            ],
            "special_notes": [
                "重难点分析应承接真实源文档中的风险、工程量、工艺参数和现场条件，不能泛写。"
            ],
            "target_word_count": 1200,
        },
        "施工部署": {
            "title": "施工部署",
            "auto_fill": ["根据项目范围、施工条件和总体安排，归纳施工组织思路、区段划分、管理职责和施工顺序。"],
            "manual_fill": ["【需人工补充：最终项目组织机构、驻地安排、责任人和审批后的施工部署。】"],
            "special_notes": ["若施工区段、队伍配置或临建布置涉及现场审批，应以审批版资料为准。"],
            "target_word_count": 1200,
        },
        "主要施工技术方案": {
            "title": "主要施工技术方案",
            "auto_fill": [
                "按工程对象和源文档工艺章节，组织主要施工方法、工艺流程、资源条件、过程控制、质量检查和安全环保控制。"
            ],
            "manual_fill": [
                "【需人工补充：专项施工方案审批版、施工参数、设备配置、工艺试验成果、图纸和现场实测数据。】"
            ],
            "special_notes": [
                "若该章信息密度高，应继续拆分为钻孔、注水、灌浆、覆盖封堵、监测评价等源文档子章节后逐节生成。"
            ],
            "target_word_count": 1800,
        },
        "施工总平面与临建": {
            "title": "施工总平面布置及临建设施",
            "auto_fill": ["根据交通、供水供电、施工场地、临建和材料堆场等来源，组织总平面布置原则和临设说明。"],
            "manual_fill": ["【需人工补充：施工总平面图、临建坐标、占地面积、临水临电审批容量。】"],
            "special_notes": ["涉及图纸、坐标、容量和占地手续的内容不得由模型补定。"],
            "target_word_count": 1400,
        },
        "施工准备": {
            "title": "施工准备",
            "auto_fill": ["归纳技术准备、现场准备、机械材料准备、人员进场和试验检测准备。"],
            "manual_fill": ["【需人工补充：实际进场计划、专项方案审批、图纸会审和技术交底记录。】"],
            "special_notes": [],
            "target_word_count": 1000,
        },
        "进度计划": {
            "title": "施工进度计划及工期保证措施",
            "auto_fill": ["根据工期、节点、施工顺序和资源安排，归纳进度计划、关键线路和工期保证措施。"],
            "manual_fill": ["【需人工补充：审批版横道图、网络计划、关键节点日期和资源峰值。】"],
            "special_notes": ["不得虚构具体开完工日期和节点日期。"],
            "target_word_count": 1400,
        },
        "资源配置": {
            "title": "资源配置计划",
            "auto_fill": ["归纳机械设备、劳动力、材料供应和试验检测资源配置原则及保障措施。"],
            "manual_fill": ["【需人工补充：最终机械设备表、劳动力计划表、主要材料进场计划。】"],
            "special_notes": [],
            "target_word_count": 1200,
        },
        "质量管理": {
            "title": "质量管理体系及保证措施",
            "auto_fill": ["按质量目标、质量体系、职责分工、过程控制、检查验收和纠偏闭环组织正文。"],
            "manual_fill": ["【需人工补充：项目质量目标、检验批划分、试验检测计划和验收责任人。】"],
            "special_notes": ["工艺质量控制应回到对应工艺章节来源，不得写泛化保证措施。"],
            "target_word_count": 1800,
        },
        "安全管理": {
            "title": "安全管理体系及保证措施",
            "auto_fill": ["按安全目标、组织机构、危险源辨识、安全制度、专项措施、检查整改和教育培训组织正文。"],
            "manual_fill": ["【需人工补充：项目安全目标、危大工程清单、专项方案审批和应急联系人。】"],
            "special_notes": ["危险源、应急资源和专项方案应由项目资料确认。"],
            "target_word_count": 1800,
        },
        "环境保护": {
            "title": "环境保护及水土保持措施",
            "auto_fill": ["归纳扬尘、噪声、废水、固废、生态保护、水土保持和绿色施工措施。"],
            "manual_fill": ["【需人工补充：环水保审批要求、监测指标、弃渣弃土去向和地方监管要求。】"],
            "special_notes": [],
            "target_word_count": 1200,
        },
        "文明施工": {
            "title": "文明施工管理措施",
            "auto_fill": ["按文明施工目标、现场标准化、围挡标识、材料堆放、道路保洁、人员管理和考核组织正文。"],
            "manual_fill": ["【需人工补充：地方文明施工标准、现场总平面和项目考核要求。】"],
            "special_notes": [],
            "target_word_count": 1000,
        },
        "应急与防灾": {
            "title": "应急预案及防灾保障措施",
            "auto_fill": ["按风险分析、应急组织、预警响应、处置流程、资源保障、演练和信息报告组织正文。"],
            "manual_fill": ["【需人工补充：应急通讯录、物资清单、地方联动单位和审批版应急预案。】"],
            "special_notes": ["防洪度汛、消防、自然灾害和公共卫生事件应按项目适用性取舍。"],
            "target_word_count": 1600,
        },
    }
    return profiles.get(
        topic,
        {
            "title": topic,
            "auto_fill": [f"根据输入文档中“{topic}”相关来源，归纳形成施组正文。"],
            "manual_fill": [f"【需人工补充：{topic}的审批版项目资料、图纸、责任人和现场确认信息。】"],
            "special_notes": [],
            "target_word_count": 1000,
        },
    )


def _fallback_subtopics(title: str) -> list[str]:
    if _contains_any(title, ("混凝土",)):
        return ["施工准备", "模板钢筋", "浇筑振捣", "养护温控", "质量检验"]
    if _contains_any(title, ("灌浆", "钻孔")):
        return ["孔位布置", "钻孔成孔", "浆液制备", "灌浆参数", "质量检查"]
    if _contains_any(title, ("支护", "锚杆", "喷混凝土")):
        return ["支护参数", "施工工序", "材料设备", "质量控制", "安全控制"]
    if _contains_any(title, ("注水",)):
        return ["注水范围", "注水工艺", "流量压力控制", "监测反馈", "安全措施"]
    if _contains_any(title, ("开挖", "洞室")):
        return ["施工准备", "测量放样", "开挖方法", "出渣运输", "支护衔接", "质量安全控制"]
    return ["施工准备", "施工方法", "质量控制", "安全环保控制"]


def _subsection_target(parent_target: int | None, count: int) -> int:
    if not parent_target or count <= 0:
        return 700
    return max(450, min(1200, int(round((parent_target / count) / 50) * 50)))


def _subsection_title(parent_title: str, subtopic: str) -> str:
    if subtopic in parent_title:
        return subtopic
    return subtopic


def _subtopic_profile(parent_title: str, subtopic: str, target_word_count: int) -> dict:
    common_manual = [f"【需人工补充：{parent_title}中“{subtopic}”对应的审批参数、图纸编号、责任人和现场核验数据。】"]
    if subtopic in {"孔位布置", "钻孔成孔"}:
        return {
            "source_rules": [f"从输入文档中匹配{parent_title}的孔位、钻孔、成孔、孔深、孔径、施工顺序等内容。"],
            "auto_fill": ["归纳施工对象、作业流程、设备材料、控制要求和记录要求。"],
            "manual_fill": common_manual,
            "special_notes": ["孔位、孔深、孔径和终孔条件必须来自图纸、设计或审批资料。"],
            "target_word_count": target_word_count,
        }
    if subtopic in {"浆液制备", "灌浆参数"}:
        return {
            "source_rules": [f"从输入文档中匹配{parent_title}的浆液配比、灌浆压力、灌浆量、结束标准和质量检查内容。"],
            "auto_fill": ["按制浆、输浆、灌浆、记录、异常处理和质量检查组织正文。"],
            "manual_fill": common_manual,
            "special_notes": ["浆液配比、压力、流量和结束标准不得由模型推定。"],
            "target_word_count": target_word_count,
        }
    if subtopic in {"流量压力控制", "监测反馈"}:
        return {
            "source_rules": [f"从输入文档中匹配{parent_title}的注水压力、流量、温度、裂隙、监测和反馈控制内容。"],
            "auto_fill": ["归纳控制指标、监测频次、异常处置和安全沟通要求。"],
            "manual_fill": common_manual,
            "special_notes": ["压力、流量、温度阈值和监测结论必须人工核验。"],
            "target_word_count": target_word_count,
        }
    if subtopic in {"模板钢筋", "浇筑振捣", "养护温控"}:
        return {
            "source_rules": [f"从输入文档中匹配{parent_title}的模板、钢筋、浇筑、振捣、养护、温控和缺陷处理内容。"],
            "auto_fill": ["按工序准备、施工方法、过程控制、质量检查和成品保护组织正文。"],
            "manual_fill": common_manual,
            "special_notes": ["配合比、温控指标、浇筑分层和模板支架参数应以审批资料为准。"],
            "target_word_count": target_word_count,
        }
    if subtopic in {"质量检验", "质量控制"}:
        return {
            "source_rules": [f"从输入文档中匹配{parent_title}的质量标准、检查项目、试验检测、验收和记录内容。"],
            "auto_fill": ["按检查项目、检测方法、验收标准、问题整改和资料归档组织正文。"],
            "manual_fill": common_manual,
            "special_notes": [],
            "target_word_count": target_word_count,
        }
    if subtopic in {"安全措施", "安全环保控制"}:
        return {
            "source_rules": [f"从输入文档中匹配{parent_title}的危险源、安全措施、环保文明施工和应急处置内容。"],
            "auto_fill": ["结合工序风险归纳作业安全、设备安全、人员防护、环保和应急措施。"],
            "manual_fill": common_manual,
            "special_notes": [],
            "target_word_count": target_word_count,
        }
    return {
        "source_rules": [f"从输入文档中匹配{parent_title}中与“{subtopic}”相关的工程事实、工艺方法和控制要求。"],
        "auto_fill": ["归纳适用范围、施工方法、资源配置、质量安全环保控制和资料要求。"],
        "manual_fill": common_manual,
        "special_notes": [],
        "target_word_count": target_word_count,
    }


def _toc_title(item: SourceTocItem) -> str:
    return " > ".join(item.title_path) if item.title_path else item.section_id


def _chapter_policy(node: TemplateNode, toc_items: list[SourceTocItem]) -> ChapterGenerationPolicy:
    title_blob = " ".join([node.title, *node.source_rules, *node.auto_fill, *node.special_notes])
    pattern_matches = match_patterns_for_text(title_blob, limit=3)
    pattern_keys = [match.pattern_key for match in pattern_matches]
    primary_pattern = pattern_keys[0] if pattern_keys else None
    pattern_required_source_facts = _merge_ordered(*[match.required_source_facts for match in pattern_matches])
    pattern_human_only_items = _merge_ordered(*[match.human_only_items for match in pattern_matches])
    pattern_prompt_cards = _pattern_prompt_cards(pattern_matches)
    target = node.target_word_count
    deep = _contains_any(title_blob, DEEP_DETAIL_TERMS) or primary_pattern == "craft"
    split_candidate = _is_split_candidate_node(node.title, primary_pattern)
    gate = _contains_any(title_blob, QUALITY_GATE_TERMS) or primary_pattern in {"deployment", "quality", "safety", "environment", "schedule_resource"}
    source_subtopics = _source_subtopics_for_node(node, toc_items)
    split_required = bool(split_candidate and ((target is None or target >= 1200) or len(source_subtopics) >= 3))
    if split_required:
        detail_level = "subsection_required"
    elif deep or (target and target >= 1800):
        detail_level = "deep"
    elif gate:
        detail_level = "normal"
    else:
        detail_level = "brief" if target and target <= 500 else "normal"
    return ChapterGenerationPolicy(
        node_id=node.id,
        title=node.title,
        detail_level=detail_level,
        target_word_count=target,
        split_required=split_required,
        max_source_matches=14 if split_required else 10 if deep else 8,
        max_evidence_spans=28 if split_required else 20 if deep else 14,
        generate_when_no_source=False,
        required_subtopics=_merge_ordered(_required_subtopics(title_blob), source_subtopics),
        source_subtopics=source_subtopics,
        writing_pattern_key=primary_pattern,
        writing_pattern_matches=pattern_keys,
        pattern_required_source_facts=pattern_required_source_facts,
        pattern_human_only_items=pattern_human_only_items,
        pattern_prompt_cards=pattern_prompt_cards,
        reason=_append_pattern_reason(
            _policy_reason(deep=deep, gate=gate, split_required=split_required, source_subtopics=source_subtopics),
            primary_pattern,
        ),
    )


def _pattern_prompt_cards(pattern_matches) -> list[dict]:
    cards: list[dict] = []
    for match in pattern_matches[:3]:
        pattern = pattern_for_key(match.pattern_key)
        if pattern is None:
            continue
        cards.append(build_pattern_prompt_card(pattern, match=match).model_dump(mode="json"))
    return cards


def _revision_triggers(
    coverage: list[OutlineCoverageItem],
    policies: list[ChapterGenerationPolicy],
) -> list[RevisionTrigger]:
    triggers: list[RevisionTrigger] = []
    for item in coverage:
        if item.status == "missing":
            triggers.append(
                RevisionTrigger(
                    node_id="outline",
                    title=item.topic,
                    action="expand_subsections",
                    severity="warning",
                    reason=item.reason,
                    evidence=item.matched_source_section_ids[:5],
                )
            )
    for policy in policies:
        if policy.split_required:
            triggers.append(
                RevisionTrigger(
                    node_id=policy.node_id,
                    title=policy.title,
                    action="expand_subsections",
                    severity="info",
                    reason="该章属于高信息密度工艺章节，应先拆小节再逐小节映射和生成。",
                )
            )
    return triggers


def _contains_any(text: str, terms: tuple[str, ...]) -> bool:
    return any(term in text for term in terms)


def _is_split_candidate_node(title: str, primary_pattern: str | None) -> bool:
    if _contains_any(title, NON_SPLIT_CONTEXT_TERMS):
        return False
    if _contains_any(title, DEEP_DETAIL_TERMS):
        return True
    return primary_pattern == "craft"


def _source_subtopics_for_node(node: TemplateNode, toc_items: list[SourceTocItem]) -> list[str]:
    title_blob = " ".join([node.title, *node.source_rules, *node.auto_fill, *node.special_notes])
    anchor_terms = _anchor_terms(title_blob)
    if not anchor_terms:
        return []
    output: list[str] = []
    for item in toc_items:
        if item.char_count <= 0 or not item.title_path:
            continue
        path_text = " > ".join(item.title_path)
        if not _matches_node_source(path_text, anchor_terms, title_blob):
            continue
        leaf = _clean_subtopic_title(item.title_path[-1])
        if not leaf or _same_or_parent_title(leaf, node.title):
            continue
        if not _is_plausible_source_subtopic(leaf):
            continue
        if leaf not in output:
            output.append(leaf)
        if len(output) >= 12:
            break
    return output


def _anchor_terms(text: str) -> list[str]:
    anchors: list[str] = []
    for term in DEEP_DETAIL_TERMS:
        if term in text and term not in anchors:
            anchors.append(term)
    if "灌、注浆" in text and "灌浆" not in anchors:
        anchors.append("灌浆")
    if "钻孔" in text and "灌浆" in text and "注浆" not in anchors:
        anchors.append("注浆")
    return anchors


def _matches_node_source(path_text: str, anchor_terms: list[str], title_blob: str) -> bool:
    hits = sum(1 for term in anchor_terms if term in path_text)
    if hits >= 1:
        return True
    # Some bid documents write "灌、注浆" or "黄泥注浆" while templates write "灌浆".
    if "灌浆" in title_blob and "注浆" in path_text:
        return True
    if "注水" in title_blob and ("水" in path_text and any(term in path_text for term in ("压力", "流量", "温度", "裂隙"))):
        return True
    return False


def _clean_subtopic_title(title: str) -> str:
    cleaned = title.strip()
    for sep in ("—", "-", ".", " "):
        cleaned = cleaned.strip(sep)
    return cleaned


def _same_or_parent_title(candidate: str, parent_title: str) -> bool:
    candidate_key = _title_key(candidate)
    parent_key = _title_key(parent_title)
    return bool(candidate_key and parent_key and (candidate_key == parent_key or candidate_key in parent_key or parent_key in candidate_key))


def _title_key(title: str) -> str:
    return (
        title.replace("、", "")
        .replace("，", "")
        .replace(",", "")
        .replace("与", "")
        .replace("和", "")
        .replace("及", "")
        .replace("工程", "")
        .replace("施工", "")
        .replace("灌注浆", "灌浆")
        .replace("注浆", "灌浆")
        .strip()
    )


def _is_plausible_source_subtopic(title: str) -> bool:
    if len(title) < 3 or len(title) > 32:
        return False
    if title in {"概述", "总述", "一般要求", "施工布置", "施工顺序"}:
        return True
    if any(ch in title for ch in "。；;，,"):
        return False
    return any(
        term in title
        for term in (
            "施工",
            "工艺",
            "方法",
            "流程",
            "程序",
            "参数",
            "控制",
            "压力",
            "流量",
            "质量",
            "检查",
            "验收",
            "试验",
            "安全",
            "材料",
            "设备",
            "制备",
            "冲洗",
            "压水",
            "套管",
            "帷幕",
            "黄泥",
            "温控",
            "浇筑",
            "振捣",
            "钢筋",
            "模板",
            "支护",
            "开挖",
            "爆破",
            "监测",
            "异常",
        )
    )


def _merge_ordered(*groups: list[str]) -> list[str]:
    merged: list[str] = []
    for group in groups:
        for item in group:
            if item not in merged:
                merged.append(item)
    return merged


def _append_pattern_reason(reason: str, pattern_key: str | None) -> str:
    if not pattern_key:
        return reason
    return f"Matched local writing pattern `{pattern_key}`. {reason}"


def _required_subtopics(text: str) -> list[str]:
    subtopics: list[str] = []
    if _contains_any(text, ("混凝土",)):
        subtopics.extend(["施工准备", "模板钢筋", "浇筑振捣", "养护温控", "质量检验"])
    if _contains_any(text, ("灌浆", "钻孔")):
        subtopics.extend(["孔位布置", "钻孔成孔", "浆液制备", "灌浆参数", "质量检查"])
    if _contains_any(text, ("支护", "锚杆", "喷混凝土")):
        subtopics.extend(["支护参数", "施工工序", "材料设备", "质量控制", "安全控制"])
    if _contains_any(text, ("注水",)):
        subtopics.extend(["注水范围", "注水工艺", "流量压力控制", "监测反馈", "安全措施"])
    return list(dict.fromkeys(subtopics))


def _policy_reason(*, deep: bool, gate: bool, split_required: bool, source_subtopics: list[str]) -> str:
    if split_required:
        if source_subtopics:
            return "标题或模板模块命中高信息密度工艺词，且输入目录存在可承接的细分来源小节，应先拆成小节生成。"
        return "标题或模板模块命中高信息密度工艺词，且适合拆成小节生成。"
    if deep:
        return "标题或模板模块命中核心工艺词，应增加来源匹配和证据容量。"
    if gate:
        return "标题或模板模块命中管理保障类主题，应按目标、体系、措施、检查闭环展开。"
    return "按普通施组小节生成策略处理。"
