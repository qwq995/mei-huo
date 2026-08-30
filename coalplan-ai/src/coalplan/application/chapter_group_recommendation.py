"""AI-assisted recommendations for generating independent chapter groups."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from coalplan.application.serialization import to_json_text
from coalplan.domain.templates import TemplateNode
from coalplan.ports.llm import StructuredLLMClient


class ChapterGroup(BaseModel):
    group_id: str
    title: str
    node_ids: list[str] = Field(default_factory=list)
    node_titles: list[str] = Field(default_factory=list)
    reason: str = ""
    shared_inputs: list[str] = Field(default_factory=list)
    dependencies: list[str] = Field(default_factory=list)
    caution: str = ""


class ChapterGroupRecommendation(BaseModel):
    project_id: str
    groups: list[ChapterGroup] = Field(default_factory=list)
    ungrouped_node_ids: list[str] = Field(default_factory=list)
    rule: str = "仅将无强前后依赖、可共享输入和上下文的章节建议一起生成；存在数据或施工顺序依赖时分组。"
    generated_by: str = "fallback"


def build_chapter_group_prompt(*, project_id: str, nodes: list[TemplateNode]) -> str:
    items = []
    for node in nodes:
        items.append({
            "node_id": node.id,
            "title": node.title,
            "level": node.level,
            "parent_id": node.parent_id if hasattr(node, "parent_id") else None,
            "source_rules": node.source_rules,
            "auto_fill": node.auto_fill,
            "manual_fill": node.manual_fill,
            "summary": node.chapter_summary or {},
        })
    return "\n".join([
        "你是施工组织设计生成调度 agent。请根据章节任务和已有上下文，推荐哪些章节可以并行或批量生成。",
        "推荐依据：共享投标来源、共享用户补充、相近工艺或同一管理主题；如果存在必须先完成的事实、施工顺序、接口、目录或前置审批依赖，应拆开并说明。",
        "不要因为章节标题相邻就强行分组；不要把父容器节点与叶子正文节点混合生成。",
        "每个章节只能出现在一个 group 或 ungrouped_node_ids 中。只输出 JSON，不要输出正文。",
        "项目：" + project_id,
        "章节候选：" + to_json_text(items),
        '{"groups":[{"group_id":"group_1","title":"","node_ids":[],"node_titles":[],"reason":"","shared_inputs":[],"dependencies":[],"caution":""}],"ungrouped_node_ids":[],"rule":"","generated_by":"llm"}',
    ])


def fallback_chapter_groups(*, project_id: str, nodes: list[TemplateNode]) -> ChapterGroupRecommendation:
    leaves = [node for node in nodes if not node.children and getattr(node, "enabled", True)]
    buckets: dict[str, list[TemplateNode]] = {}
    for node in leaves:
        title = node.title
        key = "质量安全环保" if any(word in title for word in ("质量", "安全", "环保", "文明施工")) else "施工条件与组织" if any(word in title for word in ("概况", "施工条件", "部署", "资源", "进度")) else "专业施工方法" if any(word in title for word in ("施工", "开挖", "支护", "灌浆", "混凝土", "填筑", "安装")) else "其他独立章节"
        buckets.setdefault(key, []).append(node)
    groups: list[ChapterGroup] = []
    for index, (title, items) in enumerate(buckets.items(), start=1):
        if len(items) < 2:
            continue
        groups.append(ChapterGroup(
            group_id=f"group_{index}", title=title, node_ids=[item.id for item in items],
            node_titles=[item.title for item in items],
            reason="章节主题相近且可共享候选来源，但生成时仍分别建立章节事实边界。",
            shared_inputs=["相关投标来源", "项目级用户补充"],
            caution="各章节仍需独立校验范围、参数、风险和验收要求。",
        ))
    grouped = {node_id for group in groups for node_id in group.node_ids}
    return ChapterGroupRecommendation(
        project_id=project_id,
        groups=groups,
        ungrouped_node_ids=[node.id for node in leaves if node.id not in grouped],
    )


def recommend_chapter_groups(*, project_id: str, nodes: list[TemplateNode], llm: StructuredLLMClient) -> ChapterGroupRecommendation:
    fallback = fallback_chapter_groups(project_id=project_id, nodes=nodes)
    try:
        data: Any = llm.complete_json(build_chapter_group_prompt(project_id=project_id, nodes=nodes), schema_name="ChapterGroupRecommendation")
        candidate = ChapterGroupRecommendation.model_validate({**fallback.model_dump(), **(data or {}), "project_id": project_id, "generated_by": "llm"})
        allowed = {node.id for node in nodes if not node.children and getattr(node, "enabled", True)}
        seen: set[str] = set()
        clean_groups: list[ChapterGroup] = []
        for group in candidate.groups:
            ids = [node_id for node_id in group.node_ids if node_id in allowed and node_id not in seen]
            if len(ids) < 2:
                continue
            seen.update(ids)
            group.node_ids = ids
            group.node_titles = [node.title for node in nodes if node.id in ids]
            clean_groups.append(group)
        candidate.groups = clean_groups
        candidate.ungrouped_node_ids = [node_id for node_id in allowed if node_id not in seen]
        return candidate
    except Exception:
        return fallback
