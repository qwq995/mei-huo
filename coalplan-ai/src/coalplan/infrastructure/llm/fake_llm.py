from __future__ import annotations

import json
import re
from typing import Any


class FakeLLMClient:
    """Deterministic LLM stub for tests and local demos."""

    def complete(self, prompt: str) -> str:
        title = _extract(prompt, "当前小章节标题") or _extract(prompt, "章节标题") or "未命名章节"
        sources = _extract_block(prompt, "已匹配来源章节摘要") or _extract_block(prompt, "来源片段")
        manual = _extract_block(prompt, "人工补充项")
        special = _extract_block(prompt, "特殊备注")
        source_lines = [line.strip() for line in sources.splitlines() if line.strip().startswith("-")]
        if not source_lines:
            source_lines = ["- 未在投标文档中识别到强匹配章节。"]
        manual_items = [line.strip("- ").strip() for line in manual.splitlines() if line.strip().startswith("-")]
        if not manual_items:
            manual_items = ["现场核验资料、合同数据或审批信息"]
        special_items = [line.strip("- ").strip() for line in special.splitlines() if line.strip().startswith("-")]
        body = [
            f"# {title}",
            "",
            "## 主要来源摘要",
            *source_lines[:5],
            "",
            "## 生成正文",
            f"本节围绕“{title}”编写。当前为本地测试桩输出，仅用于验证接口、校验和落盘链路。",
            "真实生成请使用 deepseek/minimax 等真实 LLM provider 启动后端。",
            "",
            "## 人工补充需补充",
        ]
        body.extend(f"- 【需人工补充：{item}】" for item in manual_items[:8])
        if special_items:
            body.extend(["", "## 特殊备注"])
            body.extend(f"- {item}" for item in special_items[:6])
        return "\n".join(body).strip() + "\n"

    def complete_json(self, prompt: str, *, schema_name: str) -> dict[str, Any]:
        if schema_name == "ProjectProfile":
            return _fake_project_profile(prompt)
        if schema_name == "TemplateOutlinePlan":
            return _fake_outline(prompt)
        if schema_name == "SourceMappingResult":
            return _fake_mapping(prompt)
        return {}


def _extract(prompt: str, label: str) -> str:
    match = re.search(rf"{re.escape(label)}[:：]\s*(.+)", prompt)
    return match.group(1).strip() if match else ""


def _extract_block(prompt: str, label: str) -> str:
    match = re.search(rf"## {re.escape(label)}\n(.*?)(?=\n## |\Z)", prompt, re.S)
    return match.group(1).strip() if match else ""


def _fake_project_profile(prompt: str) -> dict[str, Any]:
    section_ids = _known_section_ids(prompt)[:8]
    return {
        "project_name": "示例项目",
        "project_type": "施工组织设计生成测试项目",
        "location": None,
        "construction_scope": ["依据投标文件生成施工组织设计正文"],
        "key_quantities": [],
        "main_methods": [],
        "schedule": [],
        "quality_safety_environment_targets": [],
        "risk_points": [],
        "missing_items": [],
        "source_section_ids": section_ids,
    }


def _fake_outline(prompt: str) -> dict[str, Any]:
    nodes: list[dict[str, Any]] = []
    for item in _json_array_after_marker(prompt, "目标模板树："):
        node_id = item.get("id") or item.get("node_id")
        if not node_id:
            continue
        if not any([item.get("source_rules"), item.get("auto_fill"), item.get("manual_fill"), item.get("special_notes")]):
            continue
        nodes.append(
            {
                "node_id": node_id,
                "title": item.get("title", ""),
                "level": item.get("level", 1),
                "enabled": True,
                "source_hints": _known_section_ids(prompt)[:4],
                "main_sources": item.get("source_rules", []),
                "auto_fill": item.get("auto_fill", []),
                "manual_fill": item.get("manual_fill", []),
                "special_notes": item.get("special_notes", []),
            }
        )
    return {"template_id": "fake", "nodes": nodes}


def _fake_mapping(prompt: str) -> dict[str, Any]:
    node_id = _extract_json_field(prompt, "id") or _extract_json_field(prompt, "node_id")
    ids = _known_section_ids(prompt)[:4]
    return {
        "node_id": node_id,
        "matches": [
            {
                "section_id": section_id,
                "title_path": [],
                "usage": "fact",
                "reason": "关键词与当前小章节主要来源要求匹配。",
                "confidence": 0.75,
            }
            for section_id in ids
        ],
        "missing_evidence": [] if ids else ["未识别到可靠来源章节。"],
    }


def _known_section_ids(text: str) -> list[str]:
    ordered: list[str] = []
    for section_id in re.findall(r"sec_[0-9a-f]{12}", text):
        if section_id not in ordered:
            ordered.append(section_id)
    return ordered


def _json_array_after_marker(prompt: str, marker: str) -> list[dict[str, Any]]:
    try:
        start = prompt.index(marker) + len(marker)
    except ValueError:
        return []
    text = prompt[start:].strip()
    array_start = text.find("[")
    if array_start < 0:
        return []
    try:
        data, _ = json.JSONDecoder().raw_decode(text[array_start:])
    except Exception:
        return []
    return data if isinstance(data, list) else []


def _extract_json_field(text: str, field: str) -> str:
    match = re.search(rf'"{re.escape(field)}"\s*:\s*"([^"]+)"', text)
    return match.group(1) if match else ""
