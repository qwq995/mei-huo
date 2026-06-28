from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable

from coalplan.domain.documents import stable_id
from coalplan.domain.templates import TemplateTree


STRUCTURE_ONLY_NOTE = "本地施组目录/人类参考仅作为目录组织结构参考，不作为本项目事实来源；事实仍须来自投标文档 section_id/evidence_id、用户补充或人工占位。"


@dataclass(frozen=True)
class SplitRule:
    key: str
    title_keywords: tuple[str, ...]
    child_titles: tuple[str, ...]
    source_hint: str
    auto_hint: str
    manual_hint: str
    special_hint: str


COAL_FIRE_SPLIT_RULES: tuple[SplitRule, ...] = (
    SplitRule(
        key="water_injection",
        title_keywords=("注水",),
        child_titles=("注水范围与作业条件", "注水工艺流程", "压力流量控制", "温度、裂隙与塌陷监测反馈", "异常处置与安全控制", "质量检查与记录"),
        source_hint="优先映射投标文件中注水施工、火区状态、监测反馈、安全控制、质量记录等章节。",
        auto_hint="按作业条件、工艺流程、参数控制、监测反馈、异常处置和记录闭环组织正文。",
        manual_hint="需核验现场可实施注水范围、注水孔/管线布置、压力流量控制值、监测频率、审批记录和现场记录表。",
        special_hint="注水压力、流量、温度反馈和裂隙塌陷情况属于强现场数据，不得由目录参考推断。",
    ),
    SplitRule(
        key="drilling_grouting",
        title_keywords=("钻孔", "灌", "注浆"),
        child_titles=("孔位布置", "钻孔成孔", "套管与封孔", "浆液制备", "灌注浆参数控制", "质量检查与记录", "安全环保控制"),
        source_hint="优先映射投标文件中钻孔、成孔、套管封孔、浆液制备、灌注浆参数、质量安全环保等章节。",
        auto_hint="按孔位、成孔、封孔、制浆、灌浆参数、质量记录和安全环保控制展开。",
        manual_hint="需核验孔位图、孔深孔径、套管封孔做法、浆液配比、注浆压力/流量/终止标准、试验记录和环保要求。",
        special_hint="孔位、孔深、浆液参数、灌注浆压力和终止标准必须来自投标/设计/现场确认，不得编造。",
    ),
    SplitRule(
        key="cover_sealing",
        title_keywords=("覆盖封堵",),
        child_titles=("覆盖范围与材料", "分层回填", "压实与厚度控制", "防复燃控制", "排水与边坡稳定", "质量验收与记录"),
        source_hint="优先映射投标文件中覆盖封堵、土方回填、材料、压实、排水、边坡、安全质量验收等章节。",
        auto_hint="按范围材料、分层回填、压实厚度、防复燃、排水稳定和验收记录组织正文。",
        manual_hint="需核验覆盖范围、材料来源及检测、分层厚度、压实标准、排水布置、边坡稳定验算和验收记录。",
        special_hint="覆盖厚度、压实参数、防复燃评价和排水边坡稳定需依据设计、检测或现场资料确认。",
    ),
)


MANAGEMENT_GAP_NODES: tuple[dict, ...] = (
    {
        "title": "编制依据及原则",
        "keywords": ("编制依据", "编制原则", "依据"),
        "target_word_count": 800,
        "source_rules": ["映射投标文件中的编制依据、规范标准、招标范围、技术要求等章节。"],
        "auto_fill": ["整理编制依据、编制原则和文件适用范围。"],
        "manual_fill": ["需人工核验最新法律法规、规范版本、招标文件编号、合同文件和审批文件。"],
    },
    {
        "title": "项目特点及施工重难点分析",
        "keywords": ("特点", "重难点", "难点", "风险"),
        "target_word_count": 1100,
        "source_rules": ["映射投标文件中的工程特点、火区现状、治理难点、风险控制和施工条件章节。"],
        "auto_fill": ["归纳项目特点、施工重点、难点和对应组织措施。"],
        "manual_fill": ["需人工核验火区边界、温度异常区、塌陷裂隙、交通组织、现场限制和最新风险源。"],
        "special_notes": ["重难点可学习人类施组的组织方式，但风险事实必须由投标资料、勘查设计或现场补充支撑。"],
    },
    {
        "title": "施工部署",
        "keywords": ("施工部署", "组织机构", "施工组织", "职责"),
        "target_word_count": 1200,
        "source_rules": ["映射投标文件中的施工部署、组织机构、施工区段、总体安排等章节。"],
        "auto_fill": ["组织施工总体思路、阶段划分、管理机构和作业衔接。"],
        "manual_fill": ["需人工核验项目组织架构、岗位职责、分包安排、驻地与现场管理责任人。"],
    },
    {
        "title": "施工总平面布置及临时设施",
        "keywords": ("总平面", "临建", "临时设施", "施工用水", "施工用电", "便道"),
        "target_word_count": 1200,
        "source_rules": ["映射投标文件中的施工总平面、临建设施、便道、用水用电、材料堆场和交通组织章节。"],
        "auto_fill": ["按临建、道路、材料堆场、施工用水用电、消防环保和交通组织展开。"],
        "manual_fill": ["需人工核验平面布置图、临时用地、供水供电接入、消防设施、交通疏解和现场审批。"],
    },
    {
        "title": "施工准备",
        "keywords": ("施工准备", "技术准备", "现场准备", "物资准备"),
        "target_word_count": 1000,
        "source_rules": ["映射投标文件中的技术准备、人员设备进场、材料准备、测量复核、试验检测等章节。"],
        "auto_fill": ["整理技术、人员、设备、材料、现场和试验准备工作。"],
        "manual_fill": ["需人工核验图纸会审、技术交底、人员证书、设备检定、材料试验、复测成果和开工条件。"],
    },
    {
        "title": "资源配置计划",
        "keywords": ("资源", "劳动力", "机械", "设备", "材料"),
        "target_word_count": 1000,
        "source_rules": ["映射投标文件中的劳动力计划、主要机械设备、材料供应和投入计划章节。"],
        "auto_fill": ["按劳动力、机械设备、材料供应和检测仪器配置组织。"],
        "manual_fill": ["需人工核验实际进场人员、设备型号数量、材料供应计划、租赁合同和检测仪器校准状态。"],
    },
    {
        "title": "质量管理体系及保证措施",
        "keywords": ("质量", "检验", "验收", "试验"),
        "target_word_count": 1600,
        "source_rules": ["映射投标文件中的质量目标、质量体系、过程控制、检验试验、验收资料章节。"],
        "auto_fill": ["按目标体系、过程控制、工序验收、试验检测、资料闭合组织质量措施。"],
        "manual_fill": ["需人工核验质量目标、检验批划分、试验计划、检测机构、验收标准和质量责任人。"],
    },
    {
        "title": "安全管理体系及保证措施",
        "keywords": ("安全", "危险源", "职业健康", "防火"),
        "target_word_count": 1600,
        "source_rules": ["映射投标文件中的安全目标、安全体系、危险源辨识、火区作业安全、应急防护章节。"],
        "auto_fill": ["按安全目标、组织体系、风险管控、专项防护、检查教育和应急联动展开。"],
        "manual_fill": ["需人工核验危险源清单、专项方案审批、特种作业证、监测报警、消防器材和安全交底记录。"],
        "special_notes": ["煤火治理涉及高温、有害气体、塌陷裂隙和机械钻孔交叉风险，安全措施需与现场监测联动。"],
    },
    {
        "title": "环境保护、水土保持及文明施工措施",
        "keywords": ("环保", "环境保护", "水土保持", "文明施工", "扬尘", "噪声"),
        "target_word_count": 1400,
        "source_rules": ["映射投标文件中的环保、水保、文明施工、扬尘噪声、弃土弃浆、生态恢复章节。"],
        "auto_fill": ["按扬尘噪声、废水弃浆、生态保护、水土保持、文明施工和复垦恢复组织。"],
        "manual_fill": ["需人工核验环水保审批、弃土弃浆去向、监测要求、洗车降尘设施、生态恢复标准和地方要求。"],
    },
    {
        "title": "应急预案及防灾保障措施",
        "keywords": ("应急", "预案", "防灾", "抢险", "消防"),
        "target_word_count": 1300,
        "source_rules": ["映射投标文件中的应急预案、火区异常、塌陷、机械伤害、消防、防洪防风等章节。"],
        "auto_fill": ["按应急组织、预警监测、处置流程、资源保障、演练和信息报送展开。"],
        "manual_fill": ["需人工核验应急联系人、救援资源、地方联动机制、专项预案审批和演练记录。"],
    },
)


def build_pre_generation_outline_refine(
    *,
    template_tree: TemplateTree,
    current_outline_nodes: list[dict],
    toc_items: Iterable[object] = (),
    mode: str = "balanced",
    project_type: str = "auto",
    use_local_corpus: bool = True,
    use_human_reference: bool = False,
    human_reference_markdown: str | None = None,
) -> dict:
    normalized_mode = mode if mode in {"conservative", "balanced", "aggressive"} else "balanced"
    project_kind = _resolve_project_type(project_type, current_outline_nodes, toc_items)
    existing_titles = {str(item.get("title") or "").strip() for item in current_outline_nodes}
    existing_node_ids = {str(item.get("node_id") or item.get("id") or "") for item in current_outline_nodes}
    existing_by_parent: dict[str | None, list[dict]] = {}
    for node in current_outline_nodes:
        existing_by_parent.setdefault(node.get("parent_id"), []).append(node)

    preview_nodes: list[dict] = []
    structural_notes = _structural_guidance_notes(
        use_local_corpus=use_local_corpus,
        use_human_reference=use_human_reference,
        human_reference_markdown=human_reference_markdown,
    )
    if project_kind == "coal_fire":
        preview_nodes.extend(
            _coal_fire_core_children(
                current_outline_nodes=current_outline_nodes,
                existing_node_ids=existing_node_ids,
                existing_by_parent=existing_by_parent,
                structural_notes=structural_notes,
            )
        )
    if normalized_mode in {"balanced", "aggressive"}:
        preview_nodes.extend(
            _management_gap_nodes(
                current_outline_nodes=current_outline_nodes,
                existing_titles=existing_titles,
                existing_node_ids=existing_node_ids,
                mode=normalized_mode,
                structural_notes=structural_notes,
            )
        )

    summary = {
        "mode": normalized_mode,
        "project_type": project_kind,
        "added_node_count": len([node for node in preview_nodes if node.get("__action") == "create"]),
        "updated_node_count": len([node for node in preview_nodes if node.get("__action") == "update"]),
        "estimated_target_word_delta": sum(int(node.get("target_word_count") or 0) for node in preview_nodes if node.get("__action") == "create"),
        "structural_reference": {
            "use_local_corpus": use_local_corpus,
            "use_human_reference": use_human_reference,
            "note": STRUCTURE_ONLY_NOTE,
            "human_reference_headings": _extract_reference_headings(human_reference_markdown or "")[:12] if use_human_reference else [],
        },
        "manual_confirmation_items": _manual_confirmation_items(preview_nodes),
    }
    return {
        "summary": summary,
        "preview_nodes": preview_nodes,
        "markdown": render_pre_generation_outline_refine_markdown(summary, preview_nodes),
    }


def render_pre_generation_outline_refine_markdown(summary: dict, preview_nodes: list[dict]) -> str:
    lines = [
        "# 生成前目录精修建议",
        "",
        f"- mode: `{summary.get('mode')}`",
        f"- project_type: `{summary.get('project_type')}`",
        f"- added_node_count: {summary.get('added_node_count', 0)}",
        f"- estimated_target_word_delta: {summary.get('estimated_target_word_delta', 0)}",
        f"- structural_reference: {summary.get('structural_reference', {}).get('note', STRUCTURE_ONLY_NOTE)}",
        "",
        "## 建议节点",
        "",
    ]
    if not preview_nodes:
        lines.append("- 无新增目录建议。")
    for node in preview_nodes:
        parent = node.get("parent_id") or "root"
        lines.extend(
            [
                f"### {node.get('title')}",
                "",
                f"- node_id: `{node.get('node_id')}`",
                f"- parent_id: `{parent}`",
                f"- level: {node.get('level')}",
                f"- target_word_count: {node.get('target_word_count') or '-'}",
                f"- reason: {node.get('__reason') or '-'}",
                "- source_rules:",
                *[f"  - {item}" for item in node.get("source_rules", [])],
                "- manual_fill:",
                *[f"  - {item}" for item in node.get("manual_fill", [])],
                "",
            ]
        )
    return "\n".join(lines).strip() + "\n"


def _coal_fire_core_children(
    *,
    current_outline_nodes: list[dict],
    existing_node_ids: set[str],
    existing_by_parent: dict[str | None, list[dict]],
    structural_notes: list[str],
) -> list[dict]:
    preview: list[dict] = []
    for parent in current_outline_nodes:
        title = str(parent.get("title") or "")
        rule = _match_split_rule(title)
        if rule is None:
            continue
        children = existing_by_parent.get(parent.get("node_id"), [])
        existing_child_titles = {str(child.get("title") or "").strip() for child in children}
        start_order = max([int(child.get("sort_order") or 0) for child in children] or [int(parent.get("sort_order") or 0) * 100]) + 10
        target = _child_target_word_count(parent.get("target_word_count"), len(rule.child_titles))
        for index, child_title in enumerate(rule.child_titles):
            if child_title in existing_child_titles:
                continue
            node_id = stable_id("prefine", str(parent.get("node_id") or parent.get("title") or rule.key), child_title)
            if node_id in existing_node_ids:
                continue
            preview.append(
                {
                    "__action": "create",
                    "__reason": f"煤火核心工艺“{title}”生成前拆细，便于逐小节映射来源和控制详略。",
                    "node_id": node_id,
                    "parent_id": parent.get("node_id"),
                    "title": child_title,
                    "level": int(parent.get("level") or 1) + 1,
                    "sort_order": start_order + index * 10,
                    "enabled": True,
                    "target_word_count": target,
                    "source_rules": [rule.source_hint, "生成前需先由来源映射选择真实投标文档 section_id。", *structural_notes],
                    "auto_fill": [rule.auto_hint],
                    "manual_fill": [rule.manual_hint],
                    "special_notes": [rule.special_hint, *structural_notes],
                }
            )
    return preview


def _management_gap_nodes(
    *,
    current_outline_nodes: list[dict],
    existing_titles: set[str],
    existing_node_ids: set[str],
    mode: str,
    structural_notes: list[str],
) -> list[dict]:
    preview: list[dict] = []
    all_titles_text = "\n".join(existing_titles)
    start_order = max([int(node.get("sort_order") or 0) for node in current_outline_nodes] or [0]) + 10
    for item in MANAGEMENT_GAP_NODES:
        title = item["title"]
        if _has_topic(all_titles_text, item["keywords"], aggressive=(mode == "aggressive")):
            continue
        node_id = stable_id("prefine", "management", title)
        if node_id in existing_node_ids:
            continue
        special_notes = [*item.get("special_notes", []), *structural_notes]
        preview.append(
            {
                "__action": "create",
                "__reason": "本地施组目录模式中高频出现，当前项目目录尚缺明确承接节点。",
                "node_id": node_id,
                "parent_id": None,
                "title": title,
                "level": 1,
                "sort_order": start_order + len(preview) * 10,
                "enabled": True,
                "target_word_count": item["target_word_count"],
                "source_rules": [*item["source_rules"], "生成前需先由来源映射选择真实投标文档 section_id。", *structural_notes],
                "auto_fill": item["auto_fill"],
                "manual_fill": item["manual_fill"],
                "special_notes": special_notes,
            }
        )
    return preview


def _match_split_rule(title: str) -> SplitRule | None:
    normalized = _compact(title)
    for rule in COAL_FIRE_SPLIT_RULES:
        if rule.key == "drilling_grouting":
            if "钻孔" in normalized and ("灌" in normalized or "注浆" in normalized):
                return rule
            continue
        if all(keyword in normalized for keyword in rule.title_keywords):
            return rule
    return None


def _child_target_word_count(parent_target: object, child_count: int) -> int:
    try:
        parent_words = int(parent_target or 0)
    except (TypeError, ValueError):
        parent_words = 0
    if parent_words <= 0:
        return 800
    target = round(max(550, parent_words / max(1, child_count)) / 50) * 50
    return int(min(1200, max(550, target)))


def _has_topic(all_titles_text: str, keywords: Iterable[str], *, aggressive: bool) -> bool:
    compact = _compact(all_titles_text)
    hits = sum(1 for keyword in keywords if keyword and keyword in compact)
    if aggressive:
        return hits >= 2
    return hits >= 1


def _resolve_project_type(project_type: str, current_outline_nodes: list[dict], toc_items: Iterable[object]) -> str:
    if project_type and project_type != "auto":
        return project_type
    text_parts = [str(node.get("title") or "") for node in current_outline_nodes]
    for item in toc_items:
        title_path = getattr(item, "title_path", None)
        if title_path is None and isinstance(item, dict):
            title_path = item.get("title_path")
        if title_path:
            text_parts.extend(str(part) for part in title_path)
    compact = _compact("\n".join(text_parts))
    if any(term in compact for term in ("煤火", "火区", "灭火", "注水", "灌浆", "覆盖封堵")):
        return "coal_fire"
    return "general"


def _structural_guidance_notes(*, use_local_corpus: bool, use_human_reference: bool, human_reference_markdown: str | None) -> list[str]:
    notes: list[str] = []
    if use_local_corpus or (use_human_reference and human_reference_markdown):
        notes.append(STRUCTURE_ONLY_NOTE)
    if use_local_corpus:
        notes.append("本地施组目录模式提示：工程概况、重难点、施工部署、总平面临建、准备、进度资源、质量、安全、环保文明、应急和成果资料通常需要独立承接。")
    if use_human_reference and human_reference_markdown:
        headings = _extract_reference_headings(human_reference_markdown)[:8]
        if headings:
            notes.append("人类参考目录标题样式：" + "；".join(headings))
    return notes


def _extract_reference_headings(markdown: str) -> list[str]:
    headings: list[str] = []
    for raw in markdown.splitlines():
        line = raw.strip()
        if not line:
            continue
        match = re.match(r"^(?:#{1,6}\s+|第[一二三四五六七八九十百]+[章节]\s*|[0-9]+(?:\.[0-9]+)*[、.．\s]+)(.+)$", line)
        if match:
            title = match.group(1).strip()
            if 2 <= len(title) <= 40 and title not in headings:
                headings.append(title)
    return headings


def _manual_confirmation_items(preview_nodes: list[dict]) -> list[str]:
    items: list[str] = []
    for node in preview_nodes:
        for value in node.get("manual_fill", []):
            if value not in items:
                items.append(value)
    return items[:20]


def _compact(value: str) -> str:
    return re.sub(r"\s+", "", value or "")
