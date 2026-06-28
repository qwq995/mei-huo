from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, Field

from coalplan.application.writing_pattern_library import load_writing_pattern_library


OrganizationAction = Literal["accept", "repair_outline_coverage", "expand_subsections", "regenerate", "request_human_input"]


class OrganizationPointAudit(BaseModel):
    point_id: str
    title: str
    terms: list[str] = Field(default_factory=list)
    covered: bool = False


class OrganizationPatternAudit(BaseModel):
    pattern_key: str
    applicable: bool = False
    coverage_ratio: float | None = None
    covered_points: list[str] = Field(default_factory=list)
    missing_points: list[str] = Field(default_factory=list)
    points: list[OrganizationPointAudit] = Field(default_factory=list)
    suggested_action: OrganizationAction = "accept"
    reason: str = ""


class OrganizationAuditReport(BaseModel):
    pattern_count: int = 0
    applicable_pattern_count: int = 0
    average_coverage_ratio: float | None = None
    audits: list[OrganizationPatternAudit] = Field(default_factory=list)
    issues: list[str] = Field(default_factory=list)


POINT_GROUPS: dict[str, list[tuple[str, str, tuple[str, ...]]]] = {
    "overview": [
        ("identity", "项目名称、位置和背景", ("项目名称", "工程名称", "项目概况", "地理位置", "建设地点", "工程概述")),
        ("scope", "施工范围和工程对象", ("施工范围", "工程范围", "主要施工内容", "工程对象", "建设规模")),
        ("quantities", "主要工程量", ("主要工程量", "工程量", "数量", "m³", "m2", "m²", "万m", "万t")),
        ("conditions", "自然和现场施工条件", ("施工条件", "地质", "水文", "气象", "交通", "供水", "供电", "通讯")),
        ("targets", "工期质量安全环保目标", ("工期", "质量目标", "安全目标", "环保目标", "文明施工目标")),
        ("missing", "缺失项和人工确认", ("需人工补充", "人工确认", "合同编号", "审批", "图纸")),
    ],
    "deployment": [
        ("principles", "部署原则和施工分区", ("部署原则", "施工部署", "施工分区", "作业区", "施工顺序")),
        ("organization", "组织机构和职责", ("组织机构", "岗位职责", "项目经理", "管理机构", "职责")),
        ("preparation", "技术、现场、资源准备", ("施工准备", "技术准备", "现场准备", "材料准备", "设备准备")),
        ("temporary", "总平面和临建布置", ("总平面", "平面布置", "临建", "营地", "制浆站", "加工厂", "堆场")),
        ("utilities", "供水供电通讯道路", ("供水", "供电", "用水", "用电", "通讯", "施工道路", "便道")),
        ("manual", "图纸和现场确认项", ("需人工补充", "图纸", "坐标", "占地", "容量", "人工确认")),
    ],
    "craft": [
        ("object", "适用范围和施工对象", ("适用范围", "施工对象", "施工内容", "范围", "分区")),
        ("quantity", "施工依据和已知工程量", ("工程量", "数量", "孔", "m", "m³", "m2", "m²", "t")),
        ("flow", "工艺流程和施工程序", ("工艺流程", "施工流程", "施工程序", "施工顺序", "流程")),
        ("resources", "作业条件、人员、机械、材料", ("人员", "机械", "设备", "材料", "作业条件", "资源")),
        ("method", "施工方法和控制参数", ("施工方法", "控制参数", "压力", "流量", "孔径", "孔距", "厚度", "压实", "配比")),
        ("quality", "质量检查、试验和验收", ("质量检查", "检验", "试验", "验收", "检测", "合格")),
        ("hse", "安全环保文明控制", ("安全", "环保", "文明施工", "风险", "防护", "扬尘", "废水")),
        ("missing", "缺失参数占位", ("需人工补充", "人工确认", "设计要求", "监理", "审批")),
    ],
    "quality": [
        ("target", "质量目标", ("质量目标", "质量要求", "合格", "优良")),
        ("organization", "质量组织和职责", ("质量管理组织", "质量保证体系", "职责", "质检", "质量员")),
        ("system", "制度和流程", ("质量制度", "三检", "报验", "过程控制", "技术交底")),
        ("process", "材料、工序、试验检测控制", ("原材料", "工序", "试验", "检测", "检验", "抽检")),
        ("key_points", "关键工艺质量控制点", ("控制点", "关键工序", "质量通病", "质量控制措施")),
        ("closure", "验收整改和资料闭环", ("验收", "整改", "记录", "资料", "归档", "闭环")),
    ],
    "safety": [
        ("target", "安全目标", ("安全目标", "安全生产", "零事故", "杜绝")),
        ("organization", "安全组织和职责", ("安全组织", "安全保证体系", "安全员", "职责", "责任制")),
        ("hazards", "危险源辨识", ("危险源", "风险", "高处作业", "临时用电", "机械伤害", "坍塌", "火灾")),
        ("measures", "专项安全措施", ("安全措施", "防护", "警戒", "教育培训", "技术交底", "检查")),
        ("correction", "检查整改和奖惩", ("检查", "整改", "隐患", "奖惩", "闭环")),
        ("emergency", "应急组织、响应和资源", ("应急", "预案", "响应", "救援", "物资", "值班", "演练")),
    ],
    "environment": [
        ("target", "环保水保文明目标", ("环保目标", "环境保护", "水土保持", "文明施工", "绿色施工")),
        ("responsibility", "组织职责和标准化", ("组织", "职责", "标准化", "现场管理")),
        ("pollution", "扬尘噪声废水固废控制", ("扬尘", "噪声", "废水", "污水", "固废", "弃渣", "垃圾")),
        ("ecology", "生态和水保措施", ("生态", "植被", "水保", "复绿", "恢复", "冲刷")),
        ("site", "场容道路材料堆放", ("场容", "道路", "冲洗", "围挡", "材料堆放", "覆盖")),
        ("inspection", "检查考核和整改", ("检查", "考核", "整改", "记录", "监测")),
    ],
    "schedule_resource": [
        ("basis", "进度依据和控制目标", ("进度计划", "工期", "控制目标", "编制依据")),
        ("sequence", "施工顺序、关键线路和节点", ("施工顺序", "关键线路", "节点", "里程碑", "阶段")),
        ("arrangement", "分项进度安排", ("分项", "月计划", "周计划", "施工安排", "穿插")),
        ("resources", "机械劳动力材料资源", ("机械", "设备", "劳动力", "人员", "材料", "资源配置")),
        ("control", "进度跟踪、纠偏和保障", ("跟踪", "纠偏", "保证措施", "协调", "动态控制")),
        ("manual", "横道图和最终资源清单", ("需人工补充", "横道图", "网络图", "资源清单", "人工确认")),
    ],
}


def audit_document_organization(
    generated_markdown: str,
    *,
    source_markdown: str = "",
    human_markdown: str = "",
    pattern_keys: list[str] | None = None,
) -> OrganizationAuditReport:
    keys = pattern_keys or ["overview", "deployment", "craft", "quality", "safety", "environment", "schedule_resource"]
    context = "\n".join([generated_markdown or "", source_markdown or "", human_markdown or ""])
    audits = [
        audit_pattern_organization(
            generated_markdown,
            pattern_key=key,
            applicability_text=context,
        )
        for key in keys
    ]
    applicable = [item for item in audits if item.applicable]
    ratios = [item.coverage_ratio for item in applicable if item.coverage_ratio is not None]
    issues: list[str] = []
    for item in applicable:
        if item.coverage_ratio is not None and item.coverage_ratio < 0.5:
            issues.append(
                f"Pattern `{item.pattern_key}` organization coverage is {item.coverage_ratio}; missing: "
                + "；".join(item.missing_points[:6])
            )
    return OrganizationAuditReport(
        pattern_count=len(audits),
        applicable_pattern_count=len(applicable),
        average_coverage_ratio=round(sum(ratios) / len(ratios), 4) if ratios else None,
        audits=audits,
        issues=issues,
    )


def audit_pattern_organization(
    generated_markdown: str,
    *,
    pattern_key: str,
    applicability_text: str | None = None,
) -> OrganizationPatternAudit:
    groups = POINT_GROUPS.get(pattern_key, [])
    if not groups:
        return OrganizationPatternAudit(pattern_key=pattern_key, reason="No organization point group is registered.")
    generated_body = _extract_generated_body(generated_markdown)
    generated_norm = _normalize(generated_body)
    applicability_norm = _normalize(applicability_text if applicability_text is not None else generated_markdown)
    applicable = _pattern_applicable(pattern_key, applicability_norm)
    points: list[OrganizationPointAudit] = []
    for point_id, title, terms in groups:
        covered = any(_normalize(term) in generated_norm for term in terms if _normalize(term))
        points.append(OrganizationPointAudit(point_id=point_id, title=title, terms=list(terms), covered=covered))
    covered_points = [point.title for point in points if point.covered]
    missing_points = [point.title for point in points if not point.covered]
    ratio = round(len(covered_points) / len(points), 4) if points else None
    action = _suggest_action(pattern_key, applicable, ratio, covered_points)
    reason = _reason(pattern_key, applicable, ratio, missing_points)
    return OrganizationPatternAudit(
        pattern_key=pattern_key,
        applicable=applicable,
        coverage_ratio=ratio if applicable else None,
        covered_points=covered_points,
        missing_points=missing_points if applicable else [],
        points=points,
        suggested_action=action,
        reason=reason,
    )


def render_organization_audit_markdown(report: OrganizationAuditReport) -> str:
    lines = [
        "# Organization Pattern Audit",
        "",
        f"- applicable_pattern_count: {report.applicable_pattern_count}/{report.pattern_count}",
        f"- average_coverage_ratio: {report.average_coverage_ratio if report.average_coverage_ratio is not None else '-'}",
        "",
    ]
    if report.issues:
        lines.append("## Issues")
        lines.extend(f"- {item}" for item in report.issues)
        lines.append("")
    lines.append("## Patterns")
    for audit in report.audits:
        if not audit.applicable:
            continue
        lines.extend(
            [
                f"### {audit.pattern_key}",
                f"- coverage_ratio: {audit.coverage_ratio}",
                f"- suggested_action: {audit.suggested_action}",
                f"- reason: {audit.reason}",
                "- covered_points: " + ("；".join(audit.covered_points) if audit.covered_points else "-"),
                "- missing_points: " + ("；".join(audit.missing_points) if audit.missing_points else "-"),
                "",
            ]
        )
    return "\n".join(lines).strip() + "\n"


def _pattern_applicable(pattern_key: str, normalized_text: str) -> bool:
    if not normalized_text:
        return False
    library = load_writing_pattern_library()
    pattern = library.patterns.get(pattern_key)
    terms: list[str] = []
    if pattern is not None:
        terms.extend(pattern.aliases)
        terms.extend(pattern.source_topics)
        terms.extend(pattern.corpus_common_headings[:12])
    for _, title, group_terms in POINT_GROUPS.get(pattern_key, []):
        terms.append(title)
        terms.extend(group_terms[:4])
    return any(_normalize(term) in normalized_text for term in terms if _normalize(term))


def _suggest_action(
    pattern_key: str,
    applicable: bool,
    ratio: float | None,
    covered_points: list[str],
) -> OrganizationAction:
    if not applicable:
        return "accept"
    if ratio is None:
        return "accept"
    if ratio < 0.25:
        return "repair_outline_coverage"
    if pattern_key == "craft" and ratio < 0.65:
        return "expand_subsections"
    if ratio < 0.5:
        return "regenerate"
    if "缺失参数占位" in covered_points or "缺失项和人工确认" in covered_points:
        return "accept"
    return "accept"


def _reason(pattern_key: str, applicable: bool, ratio: float | None, missing_points: list[str]) -> str:
    if not applicable:
        return "Pattern is not indicated by source, human reference, or generated text."
    if ratio is not None and ratio < 0.5:
        return (
            f"Generated text indicates `{pattern_key}` content, but it does not cover enough reusable organization points: "
            + "；".join(missing_points[:6])
        )
    return "Organization points are sufficiently represented for this heuristic audit."


def _normalize(text: str) -> str:
    return re.sub(r"[\s#：:、，,。.．（）()《》\[\]【】\-—_/]+", "", text or "").lower()


def _extract_generated_body(markdown: str) -> str:
    """Audit organization only against generated正文, not source summaries."""

    text = markdown or ""
    matches = list(re.finditer(r"^##\s+生成正文\s*$", text, flags=re.M))
    if not matches:
        return text
    blocks: list[str] = []
    for index, match in enumerate(matches):
        start = match.end()
        next_heading = re.search(r"^##\s+", text[start:], flags=re.M)
        end = start + next_heading.start() if next_heading else len(text)
        blocks.append(text[start:end].strip())
    return "\n\n".join(blocks).strip() or text
