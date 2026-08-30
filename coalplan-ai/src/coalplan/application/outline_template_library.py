from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from coalplan.application.local_corpus_patterns import (
    PATTERN_TOPIC_TERMS,
    classify_project_type,
    match_patterns,
)
from coalplan.infrastructure.markdown.parser import MarkdownDocumentParser
from coalplan.ports.llm import StructuredLLMClient


class OutlineTemplateNode(BaseModel):
    node_id: str
    title: str
    level: int
    parent_id: str | None = None
    order: int
    source_line: int
    source_path: list[str] = Field(default_factory=list)
    topic_keys: list[str] = Field(default_factory=list)
    is_leaf: bool = True


class OutlineTemplateDocument(BaseModel):
    template_id: str
    file_name: str
    source_path: str
    project_name: str
    project_type: str
    tags: list[str] = Field(default_factory=list)
    key_topics: list[str] = Field(default_factory=list)
    title_count: int = 0
    leaf_count: int = 0
    nodes: list[OutlineTemplateNode] = Field(default_factory=list)
    adjustment_log: list[dict[str, Any]] = Field(default_factory=list)
    guidance_version: str = "outline-guidance-v1"
    extracted_at: str = Field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))


class OutlineTemplateRecommendationQuery(BaseModel):
    project_name: str
    tags: list[str] = Field(default_factory=list)
    project_type: str = "auto"
    limit: int = Field(default=5, ge=1, le=10)


class OutlineTemplateRecommendation(BaseModel):
    template_id: str
    rank: int
    score: float
    match_reason: str
    recommended_use: str = ""
    risks: list[str] = Field(default_factory=list)


class OutlineTemplateRecommendationResponse(BaseModel):
    query: OutlineTemplateRecommendationQuery
    candidates: list[dict[str, Any]] = Field(default_factory=list)
    recommendations: list[OutlineTemplateRecommendation] = Field(default_factory=list)
    generated_by: str = "fallback"


def default_library_dir() -> Path:
    return Path(os.getenv("COALPLAN_OUTLINE_TEMPLATE_LIBRARY_DIR", ".coalplan-data/outline-template-library"))


def build_outline_template_library(corpus_dir: str | Path, output_dir: str | Path | None = None) -> dict[str, Any]:
    root = Path(corpus_dir).expanduser().resolve()
    if not root.is_dir():
        raise ValueError(f"目录模板样本目录不存在：{root}")
    out = Path(output_dir).expanduser() if output_dir else default_library_dir()
    out.mkdir(parents=True, exist_ok=True)
    (out / "templates").mkdir(exist_ok=True)
    documents: list[OutlineTemplateDocument] = []
    failures: list[dict[str, str]] = []
    skipped: list[dict[str, str]] = []
    parser = MarkdownDocumentParser()
    for source in sorted(root.rglob("*.md")):
        accepted, reason = _is_template_candidate(source)
        if not accepted:
            skipped.append({"source_path": str(source), "reason": reason})
            continue
        try:
            text = source.read_text(encoding="utf-8", errors="ignore")
            sections = parser.split_sections(text, source_file=str(source))
            document = _document_from_sections(source, sections, root)
            documents.append(document)
            (out / "templates" / f"{document.template_id}.json").write_text(
                json.dumps(document.model_dump(), ensure_ascii=False, indent=2), encoding="utf-8"
            )
            (out / "templates" / f"{document.template_id}.md").write_text(
                render_outline_template_markdown(document), encoding="utf-8"
            )
        except Exception as exc:
            failures.append({"source_path": str(source), "error": str(exc)})
    index = {
        "version": "outline-template-library-v1",
        "corpus_dir": str(root),
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "document_count": len(documents),
        "failed_count": len(failures),
        "skipped_count": len(skipped),
        "skipped": skipped,
        "templates": [template_summary(item) for item in documents],
        "failures": failures,
    }
    (out / "index.json").write_text(json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8")
    (out / "index.md").write_text(render_library_markdown(index), encoding="utf-8")
    return {"library_dir": str(out.resolve()), **index}


def _is_template_candidate(source: Path) -> tuple[bool, str]:
    text = source.stem.lower()
    include_terms = ("施工组织设计", "施工方案", "专项施工方案", "施工组织", "施组")
    exclude_terms = (
        "编写指南", "审查记录", "批复", "报审", "投标", "招标", "合同", "图纸", "报价", "清单",
        "规范", "标准", "通知", "目录", "说明", "记录", "交底", "汇总", "审批", "关于报送", "关于重新报送",
        "请示", "函", "会审", "签字单", "封面",
    )
    if not any(term in text for term in include_terms):
        return False, "未命中施工组织设计或施工方案名称"
    for term in exclude_terms:
        if term in text or (term in {"审查记录", "方案审查"} and term in str(source.parent).lower()):
            return False, f"命中排除词：{term}"
    return True, ""


def _document_from_sections(source: Path, sections: list[Any], root: Path) -> OutlineTemplateDocument:
    source_rel = str(source.relative_to(root))
    template_id = "outline_tpl_" + hashlib.sha1(str(source).encode("utf-8")).hexdigest()[:12]
    nodes: list[OutlineTemplateNode] = []
    stack: list[tuple[int, str, list[str]]] = []
    adjustment_log: list[dict[str, Any]] = []
    seen: set[tuple[str, int]] = set()
    for order, section in enumerate(sections):
        title = _clean_title(section.title_path[-1] if section.title_path else source.stem)
        raw_level = max(1, min(int(section.level or 1), 6))
        level = raw_level
        if stack and level > stack[-1][0] + 1:
            level = stack[-1][0] + 1
            adjustment_log.append({"kind": "level_repaired", "title": title, "from": raw_level, "to": level})
        key = (_normalize(title), level)
        if key in seen and nodes and nodes[-1].title == title and nodes[-1].level == level:
            adjustment_log.append({"kind": "duplicate_heading_skipped", "title": title, "line": section.start_line})
            continue
        seen.add(key)
        while stack and stack[-1][0] >= level:
            stack.pop()
        parent_id = stack[-1][1] if stack else None
        path = [item[2][0] for item in stack] + [title]
        node_id = "tn_" + hashlib.sha1(f"{source_rel}:{section.start_line}:{title}".encode("utf-8")).hexdigest()[:12]
        topics = sorted(match_patterns([title, *section.title_path]))
        nodes.append(OutlineTemplateNode(
            node_id=node_id, title=title, level=level, parent_id=parent_id,
            order=order, source_line=section.start_line, source_path=path, topic_keys=topics,
        ))
        stack.append((level, node_id, [title]))
    child_ids = {node.parent_id for node in nodes if node.parent_id}
    for node in nodes:
        node.is_leaf = node.node_id not in child_ids
    key_topics = sorted({topic for node in nodes for topic in node.topic_keys})
    project_type = classify_project_type(source.name)
    tags = _tags_from_text(source.stem + " " + " ".join(key_topics))
    return OutlineTemplateDocument(
        template_id=template_id, file_name=source.name, source_path=str(source),
        project_name=source.stem, project_type=project_type, tags=tags,
        key_topics=key_topics, title_count=len(nodes), leaf_count=sum(n.is_leaf for n in nodes),
        nodes=nodes, adjustment_log=adjustment_log,
    )


def _clean_title(value: str) -> str:
    value = re.sub(r"^#+\s*", "", value or "").strip()
    value = re.sub(r"^第[一二三四五六七八九十百零〇]+[章节]\s*", "", value).strip()
    value = re.sub(r"^(?:\d+(?:\.\d+)*|[一二三四五六七八九十百]+)[、.．）)]?\s*", "", value).strip()
    return re.sub(r"[*_`]+", "", value).strip() or "未命名章节"


def _normalize(value: str) -> str:
    return re.sub(r"[\s\W_]+", "", value).lower()


def _tags_from_text(value: str) -> list[str]:
    known = ["水电", "抽水蓄能", "隧洞", "大坝", "边坡", "爆破", "灌浆", "混凝土", "导流", "交通洞", "施工组织设计", "专项施工方案"]
    return [tag for tag in known if tag in value][:8]


def template_summary(item: OutlineTemplateDocument) -> dict[str, Any]:
    return {
        "template_id": item.template_id, "file_name": item.file_name, "source_path": item.source_path,
        "project_name": item.project_name, "project_type": item.project_type, "tags": item.tags,
        "key_topics": item.key_topics, "title_count": item.title_count, "leaf_count": item.leaf_count,
        "adjustment_count": len(item.adjustment_log),
        "top_headings": [node.title for node in item.nodes if node.level <= 2][:12],
    }


def load_outline_template_index(library_dir: str | Path | None = None) -> dict[str, Any]:
    path = (Path(library_dir) if library_dir else default_library_dir()) / "index.json"
    if not path.exists():
        return {"templates": [], "document_count": 0, "library_dir": str(path.parent.resolve())}
    return json.loads(path.read_text(encoding="utf-8"))


def load_outline_template(template_id: str, library_dir: str | Path | None = None) -> OutlineTemplateDocument | None:
    path = (Path(library_dir) if library_dir else default_library_dir()) / "templates" / f"{template_id}.json"
    if not path.exists():
        return None
    return OutlineTemplateDocument(**json.loads(path.read_text(encoding="utf-8")))


def recommend_outline_templates(query: OutlineTemplateRecommendationQuery, *, llm: StructuredLLMClient | None = None, library_dir: str | Path | None = None) -> OutlineTemplateRecommendationResponse:
    index = load_outline_template_index(library_dir)
    candidates = _recall_candidates(query, index.get("templates", []))
    recommendations = _fallback_recommendations(query, candidates)
    generated_by = "fallback"
    if llm and candidates:
        try:
            payload = llm.complete_json(_recommendation_prompt(query, candidates), schema_name="OutlineTemplateRecommendation")
            parsed = [OutlineTemplateRecommendation(**item) for item in payload.get("recommendations", [])]
            allowed = {item["template_id"] for item in candidates}
            parsed = [item for item in parsed if item.template_id in allowed]
            if parsed:
                recommendations = [item.model_copy(update={"rank": index + 1}) for index, item in enumerate(parsed[: query.limit])]
                generated_by = "llm"
        except Exception:
            pass
    return OutlineTemplateRecommendationResponse(query=query, candidates=candidates, recommendations=recommendations[: query.limit], generated_by=generated_by)


def _recall_candidates(query: OutlineTemplateRecommendationQuery, summaries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    terms = set(_tokenize(query.project_name + " " + " ".join(query.tags)))
    scored = []
    for item in summaries:
        haystack = " ".join([item.get("file_name", ""), item.get("project_name", ""), item.get("project_type", ""), *item.get("tags", []), *item.get("key_topics", []), *item.get("top_headings", [])])
        overlap = len(terms & set(_tokenize(haystack)))
        type_hit = query.project_type != "auto" and query.project_type == item.get("project_type")
        score = overlap + (2 if type_hit else 0) + min(item.get("title_count", 0) / 1000, 0.5)
        scored.append((score, item))
    return [item for _, item in sorted(scored, key=lambda value: (-value[0], value[1].get("file_name", "")))[:8]]


def _tokenize(value: str) -> list[str]:
    return [part for part in re.split(r"[\s,，、;；/（）()：:]+", value.lower()) if len(part) >= 2] + [value[i:i+2] for i in range(max(0, len(value)-1))]


def _fallback_recommendations(query: OutlineTemplateRecommendationQuery, candidates: list[dict[str, Any]]) -> list[OutlineTemplateRecommendation]:
    return [OutlineTemplateRecommendation(template_id=item["template_id"], rank=index + 1, score=max(0.1, 1 - index * 0.1), match_reason=f"与项目名称/标签匹配，覆盖{ '、'.join(item.get('key_topics', [])[:4]) or '通用施组目录'}。", recommended_use="作为目录结构参考，项目事实需回到投标资料核验。") for index, item in enumerate(candidates)]


def _recommendation_prompt(query: OutlineTemplateRecommendationQuery, candidates: list[dict[str, Any]]) -> str:
    return "\n".join(["你是施工组织设计目录模板推荐助手。根据项目名称和用户标签，从候选目录模板中排序，不能编造项目事实。", f"项目名称：{query.project_name}", f"用户标签：{query.tags}", "候选模板：", json.dumps(candidates, ensure_ascii=False), '只输出JSON：{"recommendations":[{"template_id":"候选id","rank":1,"score":0.0,"match_reason":"","recommended_use":"","risks":[]}]}', "score为0到1；优先考虑项目类型、工程对象和施工工艺；推荐理由只说明目录结构相关性。"])


def render_outline_template_markdown(document: OutlineTemplateDocument) -> str:
    lines = [f"# {document.project_name}", f"- template_id: `{document.template_id}`", f"- project_type: `{document.project_type}`", f"- source: `{document.source_path}`", "", "## 调整记录"]
    lines += [f"- {item['kind']}: {item.get('title', '')}" for item in document.adjustment_log] or ["- 无"]
    lines += ["", "## 目录结构"]
    for node in document.nodes:
        lines.append(f"{'  ' * (node.level - 1)}- {node.title}  (`{node.node_id}`, line {node.source_line})")
    return "\n".join(lines) + "\n"


def render_library_markdown(index: dict[str, Any]) -> str:
    lines = ["# 目录模板库", f"- 样本数：{index.get('document_count', 0)}", f"- 失败数：{index.get('failed_count', 0)}", f"- 筛除数：{index.get('skipped_count', 0)}", ""]
    for item in index.get("templates", []):
        lines.append(f"- `{item['template_id']}` {item['file_name']}：{item['project_type']}，{item['title_count']}个标题")
    return "\n".join(lines) + "\n"
