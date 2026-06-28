from __future__ import annotations

from pydantic import BaseModel, Field

from coalplan.domain.templates import TemplateNode


class ChapterWritingGuidance(BaseModel):
    pattern_key: str = "general"
    category: str
    structure: list[str] = Field(default_factory=list)
    focus_points: list[str] = Field(default_factory=list)
    avoid: list[str] = Field(default_factory=list)
    corpus_basis: list[str] = Field(default_factory=list)


def guidance_for_node(node: TemplateNode) -> ChapterWritingGuidance:
    title_text = " ".join([node.title, *node.source_rules, *node.auto_fill])
    text = " ".join([title_text, *node.manual_fill, *node.special_notes])
    if _has(title_text, ("工程概况", "工程概述", "建设规模", "工程范围", "火区位置", "交通", "现状")):
        return _with_pattern(_overview_guidance(), "overview")
    if _has(title_text, ("施工部署", "总平面", "平面布置", "临建", "供水", "供电", "通讯", "施工准备")):
        return _with_pattern(_deployment_guidance(), "deployment")
    if _has(text, ("混凝土", "灌浆", "钻孔", "注水", "覆盖", "封堵", "支护", "锚杆", "开挖", "爆破", "管网", "安装", "调试")):
        return _with_pattern(_craft_guidance(text), "craft")
    if _has(text, ("质量", "检验", "试验", "验收")):
        return _with_pattern(_quality_guidance(), "quality")
    if _has(text, ("安全", "职业健康", "危险源", "应急", "消防", "防洪", "度汛")):
        return _with_pattern(_safety_guidance(), "safety")
    if _has(text, ("环保", "环境保护", "水保", "绿色施工", "文明施工")):
        return _with_pattern(_environment_guidance(), "environment")
    if _has(text, ("进度", "工期", "关键线路", "资源", "机械", "劳动力", "材料")):
        return _with_pattern(_schedule_resource_guidance(), "schedule_resource")
    return _with_pattern(_general_guidance(), "general")


def render_writing_guidance(guidance: ChapterWritingGuidance) -> str:
    lines = [f"- 类型：{guidance.category}"]
    if guidance.corpus_basis:
        lines.append("- 本地施组样本依据：" + "；".join(guidance.corpus_basis))
    if guidance.structure:
        lines.append("- 推荐展开顺序：")
        lines.extend(f"  {index}. {item}" for index, item in enumerate(guidance.structure, start=1))
    if guidance.focus_points:
        lines.append("- 写作重点：")
        lines.extend(f"  - {item}" for item in guidance.focus_points)
    if guidance.avoid:
        lines.append("- 避免：")
        lines.extend(f"  - {item}" for item in guidance.avoid)
    return "\n".join(lines)


def _with_pattern(guidance: ChapterWritingGuidance, pattern_key: str) -> ChapterWritingGuidance:
    guidance.pattern_key = pattern_key
    return guidance


def _craft_guidance(text: str) -> ChapterWritingGuidance:
    focus = ["工艺流程必须从来源中抽取，不得凭经验补参数。", "质量、安全、环保控制要贴合当前工序风险。"]
    if _has(text, ("灌浆", "钻孔")):
        focus.extend(["重点写孔位布置、钻孔成孔、浆液制备、灌浆控制、结束标准和质量检查。"])
    if _has(text, ("注水",)):
        focus.extend(["重点写注水范围、注水工艺、压力流量控制、温度监测和异常处置。"])
    if _has(text, ("混凝土",)):
        focus.extend(["重点写模板钢筋、浇筑振捣、养护温控、缺陷处理和试验检测。"])
    if _has(text, ("支护", "锚杆", "喷混凝土")):
        focus.extend(["重点写支护参数、施工工序、材料设备、质量检验和安全控制。"])
    return ChapterWritingGuidance(
        category="工艺类章节",
        structure=["适用范围和施工对象", "施工依据和已知工程量", "工艺流程", "作业条件、人员、机械、材料", "施工方法和控制要求", "质量检查、试验与验收", "安全、环保、文明施工控制", "缺失参数占位"],
        focus_points=focus,
        avoid=["把来源没有的压力、流量、配合比、孔位、验收结论写成确定事实。", "只写原则性套话而不落到工序。"],
        corpus_basis=["本地 34 份施组目录中“主要工艺”主题覆盖 34 份。", "高频标题包括施工方法、施工工艺流程、施工程序、质量控制措施、质量检查和验收。"],
    )


def _quality_guidance() -> ChapterWritingGuidance:
    return ChapterWritingGuidance(
        category="质量管理类章节",
        structure=["质量目标", "质量管理组织和职责", "质量保证体系和制度", "原材料、工序、试验检测控制", "关键工艺质量控制点", "检查验收、整改闭环和资料归档", "人工确认项"],
        focus_points=["质量措施要和当前项目工艺对应，优先引用来源中的检验、试验、验收要求。", "对缺少检验批、试验计划、验收标准的内容保留人工补充。"],
        avoid=["泛泛写 ISO 或质量口号但没有过程控制。"],
        corpus_basis=["本地样本中“质量”主题覆盖 33 份。", "高频标题包括质量保证措施、质量目标、质量保证体系、质量控制措施、质量检查和验收。"],
    )


def _safety_guidance() -> ChapterWritingGuidance:
    return ChapterWritingGuidance(
        category="安全/应急类章节",
        structure=["安全目标", "安全组织体系和岗位职责", "危险源辨识", "专项安全措施", "教育培训、检查整改和奖惩", "应急组织、响应流程和资源保障", "人工确认项"],
        focus_points=["危险源必须贴合当前工程和工序。", "应急联系人、物资清单、地方联动单位等必须人工确认。"],
        avoid=["脱离项目风险的通用安全套话。", "虚构应急联系方式、审批结论或专项方案编号。"],
        corpus_basis=["本地样本中“安全”主题覆盖 34 份，“应急防灾”覆盖 33 份。", "高频标题包括安全保证措施、安全目标、安全保证体系、应急预案。"],
    )


def _environment_guidance() -> ChapterWritingGuidance:
    return ChapterWritingGuidance(
        category="环保/文明施工类章节",
        structure=["管理目标", "组织职责", "扬尘、噪声、废水、固废和生态保护措施", "现场标准化和文明施工措施", "检查考核和整改", "人工确认项"],
        focus_points=["环保水保和文明施工措施要结合施工场地、道路、材料堆放、弃渣弃土和地方监管要求。"],
        avoid=["把地方审批指标、监测指标或弃渣去向写成未核验事实。"],
        corpus_basis=["本地样本中“环保”和“文明施工”主题均覆盖 32 份。", "高频标题包括文明施工措施、文明施工保证措施。"],
    )


def _schedule_resource_guidance() -> ChapterWritingGuidance:
    return ChapterWritingGuidance(
        category="进度资源类章节",
        structure=["编制依据和控制目标", "总体安排和关键线路", "分项进度或节点安排", "劳动力、机械、材料配置", "进度控制和纠偏措施", "人工确认项"],
        focus_points=["日期、节点、峰值资源和横道图必须来自来源或人工补充。", "可根据工艺顺序归纳进度控制逻辑，但不得虚构具体工期。"],
        avoid=["没有来源时直接写具体开完工日期。"],
        corpus_basis=["本地样本中“进度”和“资源”主题均覆盖 33 份。", "高频标题包括施工进度计划、资源配置计划、工期保证措施。"],
    )


def _overview_guidance() -> ChapterWritingGuidance:
    return ChapterWritingGuidance(
        category="工程概况类章节",
        structure=["项目名称、位置和建设背景", "施工范围和工程对象", "主要工程量及单位", "自然条件和现场施工条件", "交通、水电、通讯和材料条件", "工期、质量、安全、环保目标", "缺失项"],
        focus_points=["工程量和单位必须保留来源表达。", "没有来源的建设单位、合同编号、坐标、工期目标必须人工补充。"],
        avoid=["将项目画像中的缺失项写成确定事实。"],
        corpus_basis=["本地样本中“工程概况”主题覆盖 31 份，“施工条件”覆盖 34 份。", "高频标题包括工程概况、概述、工程概述、主要工程量。"],
    )


def _deployment_guidance() -> ChapterWritingGuidance:
    return ChapterWritingGuidance(
        category="施工部署/临建类章节",
        structure=["部署原则", "施工区段和作业顺序", "组织机构和职责", "施工总平面和临建布置", "供水、供电、通讯、道路和材料堆场", "现场准备和保障措施", "人工确认项"],
        focus_points=["总平面、临水临电、占地和坐标类内容必须依赖图纸或人工补充。"],
        avoid=["没有图纸来源时编造布置位置、容量和面积。"],
        corpus_basis=["本地样本中“施工部署”覆盖 32 份，“总平面临建”和“施工准备”均覆盖 30 份。", "高频标题包括施工布置、施工部署、施工现场总平面布置、施工用水、施工用电。"],
    )


def _general_guidance() -> ChapterWritingGuidance:
    return ChapterWritingGuidance(
        category="通用施组章节",
        structure=["本节适用范围", "来源中已明确的事实", "可归纳组织的内容", "质量安全环保控制", "需要人工补充的内容"],
        focus_points=["优先使用 evidence_id 对应原文，缺失处保留人工补充占位。"],
        avoid=["输出流程说明或模板解释。"],
        corpus_basis=["本地施组样本显示通用章节通常围绕概况、部署、进度、资源、工艺、质量、安全、环保、文明和应急展开。"],
    )


def _has(text: str, terms: tuple[str, ...]) -> bool:
    return any(term in text for term in terms)
