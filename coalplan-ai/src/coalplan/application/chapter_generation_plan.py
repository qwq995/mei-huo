from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from coalplan.domain.generation_context import WritingUnitSpec
from coalplan.domain.templates import TemplateNode


class ChapterPlanItem(BaseModel):
    item_id: str
    title: str
    purpose: str = ""
    key_points: list[str] = Field(default_factory=list)
    evidence_requirement: str = ""
    output_form: str = "形成可直接入稿的小节"
    target_word_count: int | None = Field(default=None, ge=200, le=2000)
    enabled: bool = True
    sort_order: int = 0

    @field_validator("title")
    @classmethod
    def title_not_empty(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("提纲要点标题不能为空")
        return value


class ChapterGenerationPlan(BaseModel):
    version: int = 1
    node_id: str
    title: str
    status: Literal["draft", "confirmed"] = "draft"
    scope_statement: str
    items: list[ChapterPlanItem] = Field(default_factory=list)
    out_of_scope: list[str] = Field(default_factory=list)
    fact_boundaries: list[str] = Field(default_factory=list)
    manual_inputs: list[str] = Field(default_factory=list)
    user_notes: str = ""
    source: Literal["system", "ai", "user"] = "system"
    updated_at: str = ""
    fingerprint: str = ""

    @field_validator("scope_statement")
    @classmethod
    def scope_not_empty(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("章节范围说明不能为空")
        return value


def default_chapter_generation_plan(
    *,
    node: TemplateNode,
    writing_units: list[WritingUnitSpec],
) -> ChapterGenerationPlan:
    items = [
        ChapterPlanItem(
            item_id=unit.unit_id,
            title=unit.title,
            purpose=unit.objective,
            key_points=[topic for topic in unit.writing_topics if _topic_within_chapter(node.title, topic)],
            evidence_requirement="项目事实、参数和管理要求必须有投标 evidence_id、用户补充或人工确认。",
            output_form="；".join(unit.content_functions) or "形成可直接入稿的小节",
            target_word_count=unit.target_word_count,
            sort_order=index,
        )
        for index, unit in enumerate(writing_units, start=1)
    ]
    items = [item for item in items if item.key_points or _topic_within_chapter(node.title, item.title)]
    if any(term in _plain_title(node.title) for term in ("水文", "气象", "气候")):
        items = _fallback_scope_items(node)
    elif not items:
        items = _fallback_scope_items(node)
    plan = ChapterGenerationPlan(
        node_id=node.id,
        title=node.title,
        scope_statement=_default_scope(node),
        items=items,
        out_of_scope=_default_exclusions(node.title),
        fact_boundaries=[
            "项目名称、范围、工程量、日期、规范和技术参数只能来自当前项目投标证据或用户确认。",
            "优秀施组原子只用于工艺展开和控制闭环，不迁移异项目数值、地名、设备数量和责任主体。",
            "缺少依据的监测频次、预警阈值、人员配置和审批结论保留为人工补充项。",
        ],
        manual_inputs=list(node.manual_fill),
    )
    return with_plan_fingerprint(plan)


def validate_saved_plan(
    payload: dict,
    *,
    node_id: str,
    title: str,
) -> ChapterGenerationPlan:
    data = dict(payload)
    data["node_id"] = node_id
    data["title"] = title
    data["source"] = "user" if data.get("source") != "ai" else "ai"
    data["updated_at"] = datetime.now().isoformat()
    items = list(data.get("items") or [])
    if len(items) > 8:
        raise ValueError("单章最多保留 8 个生成要点，请先合并相近内容。")
    data["items"] = [
        {
            **item,
            "item_id": str(item.get("item_id") or _stable_item_id(node_id, str(item.get("title") or ""), index)),
            "sort_order": index,
        }
        for index, item in enumerate(items, start=1)
    ]
    plan = ChapterGenerationPlan.model_validate(data)
    if plan.status == "confirmed" and not any(item.enabled for item in plan.items):
        raise ValueError("确认提纲前至少保留一个启用的生成要点。")
    return with_plan_fingerprint(plan)


def with_plan_fingerprint(plan: ChapterGenerationPlan) -> ChapterGenerationPlan:
    payload = plan.model_dump(exclude={"fingerprint", "updated_at"})
    plan.fingerprint = hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()
    return plan


def render_chapter_plan_for_prompt(plan: dict | ChapterGenerationPlan | None) -> str:
    if not plan:
        return ""
    value = plan if isinstance(plan, ChapterGenerationPlan) else ChapterGenerationPlan.model_validate(plan)
    enabled = sorted((item for item in value.items if item.enabled), key=lambda item: item.sort_order)
    lines = [
        "## 用户确认的章节结构化提纲（生成范围硬约束）",
        f"- 章节范围：{value.scope_statement}",
        f"- 提纲状态：{value.status}",
        "- 只允许覆盖以下要点：",
    ]
    for index, item in enumerate(enabled, start=1):
        lines.append(
            f"  {index}. {item.title}；目的：{item.purpose or '-'}；要点：{'、'.join(item.key_points) or '-'}；证据要求：{item.evidence_requirement or '-'}"
        )
    if value.out_of_scope:
        lines.extend(["- 明确排除：", *[f"  - {item}" for item in value.out_of_scope]])
    if value.fact_boundaries:
        lines.extend(["- 事实边界：", *[f"  - {item}" for item in value.fact_boundaries]])
    # Manual inputs are collected separately and only enter generation after the user saves them.
    if value.user_notes:
        lines.append(f"- 用户备注：{value.user_notes}")
    lines.append("不得新增提纲之外的独立三级或四级主题；确需扩展时保留人工建议，不写入本次正文。")
    return "\n".join(lines)


def generation_plan_prompt(*, plan: ChapterGenerationPlan, suggestion: str, source_candidates: list[dict]) -> str:
    return "\n".join(
        [
            "你是施工组织设计章节提纲优化助手。请修改结构化提纲，不生成正文。",
            f"用户修改意图：{suggestion.strip()}",
            "规则：",
            "1. 章节标题不可改变，最多 8 个要点。",
            "2. 只调整本章职责范围，不把安全体系、质量体系、施工部署等其他独立章节塞入本章。",
            "3. 投标候选来源只证明可能相关，不能据此虚构数值、结论、责任主体或审批要求。",
            "4. 缺少的参数、频次、阈值、人员设备和批复结论放入 manual_inputs。",
            "5. out_of_scope 必须明确列出容易越界但本章不写的主题。",
            "当前提纲 JSON：",
            json.dumps(plan.model_dump(), ensure_ascii=False),
            "投标候选来源摘要：",
            json.dumps(source_candidates[:8], ensure_ascii=False),
            "严格返回 JSON：",
            '{"scope_statement":"","items":[{"item_id":"","title":"","purpose":"","key_points":[],"evidence_requirement":"","output_form":"","target_word_count":500,"enabled":true,"sort_order":1}],"out_of_scope":[],"fact_boundaries":[],"manual_inputs":[],"user_notes":""}',
        ]
    )


def _default_scope(node: TemplateNode) -> str:
    title = _plain_title(node.title)
    if any(term in title for term in ("水文", "气象", "气候")):
        return "说明工程区水文、气象和季节性条件及其对本工程施工安排的直接影响；不在本章展开完整施工方法或管理体系。"
    if any(term in title for term in ("地质", "地形", "地貌")):
        return "说明工程区地形地貌、工程地质与不良地质条件，以及这些条件对施工对象和风险控制的直接影响。"
    if "工程概况" in title or title.endswith("概况"):
        return "准确交代项目位置、建设范围、主要施工对象、工程量及合同目标，仅纳入投标文件可核实的项目事实。"
    overview = str((node.chapter_summary or {}).get("overview") or "").strip()
    return overview or f"仅围绕“{title}”说明与本项目直接相关的对象、条件、实施要点和检查闭环，不承担其他独立章节职责。"


def _default_exclusions(title: str) -> list[str]:
    exclusions = ["与本章无直接关系的项目管理制度和通用口号"]
    if "安全" not in title:
        exclusions.append("完整安全组织体系、全项目危险源清单和通用安全目标")
    if "质量" not in title:
        exclusions.append("完整质量保证体系和跨专业验收制度")
    if not any(term in title for term in ("施工", "工艺", "方法", "开挖", "支护", "混凝土", "灌浆")):
        exclusions.append("其他专业施工方法的完整展开")
    if any(term in title for term in ("水文", "气象", "气候", "地质", "地形", "地貌")):
        exclusions.append("只属于后续施工方案的具体工序、设备配置和成套控制参数")
    return exclusions


def _stable_item_id(node_id: str, title: str, index: int) -> str:
    compact = re.sub(r"\s+", "", title)
    digest = hashlib.sha1(f"{node_id}:{index}:{compact}".encode("utf-8")).hexdigest()[:12]
    return f"planitem_{digest}"


def _plain_title(value: str) -> str:
    value = re.sub(r"\*+", "", value or "")
    return re.sub(r"^\s*\d+(?:\.\d+)*\s*", "", value).strip()


def _topic_within_chapter(chapter_title: str, topic: str) -> bool:
    title = _plain_title(chapter_title)
    value = _plain_title(topic)
    cross_chapter_groups = (
        ("安全", ("安全目标", "安全组织", "岗位职责", "危险源", "专项安全措施")),
        ("质量", ("质量目标", "质量体系", "质量组织", "质量职责")),
        ("进度", ("进度计划", "工期保证", "关键线路")),
        ("环保", ("环境保护体系", "水土保持体系", "文明施工体系")),
    )
    for owner_term, topics in cross_chapter_groups:
        if owner_term not in title and any(term in value for term in topics):
            return False
    if any(term in title for term in ("水文", "气象", "气候")):
        return any(term in value for term in ("水文", "气象", "气候", "降水", "雨季", "洪水", "水位", "流量", "温度", "风", "蒸发", "季节", "冰冻"))
    return True


def _fallback_scope_items(node: TemplateNode) -> list[ChapterPlanItem]:
    title = _plain_title(node.title)
    if any(term in title for term in ("水文", "气象", "气候")):
        definitions = [
            ("水文与气象基础资料", "提取投标文件已有的气候分区、降水、温度、水位、流量等可核实条件。", ["气象资料及代表性", "降水与季节分布", "河流水文及地下水条件"]),
            ("季节变化及施工影响", "只说明自然条件对施工时段、作业面和风险的直接影响，为其他施工章节提供条件输入。", ["雨季和枯水期特征", "低温、强降雨等不利条件", "对路基、边坡、隧洞或混凝土作业的直接影响"]),
            ("资料缺口与采用原则", "列明需补充的实测资料和采用边界，不自行设定监测频次、预警阈值或管理责任。", ["实测资料缺口", "施工期动态复核事项", "需人工确认的参数与结论"]),
        ]
    else:
        definitions = [(title, f"围绕“{title}”形成职责清晰、证据可核验的章节内容。", [title])]
    return [
        ChapterPlanItem(
            item_id=_stable_item_id(node.id, item_title, index),
            title=item_title,
            purpose=purpose,
            key_points=points,
            evidence_requirement="项目事实必须来自当前投标证据或用户确认；缺失项明确占位。",
            target_word_count=max(250, int((node.target_word_count or 900) / len(definitions))),
            sort_order=index,
        )
        for index, (item_title, purpose, points) in enumerate(definitions, start=1)
    ]
