from __future__ import annotations

import json
import re
from typing import Any


class FakeLLMClient:
    """Deterministic LLM stub for tests and local demos."""

    def complete(self, prompt: str) -> str:
        if "CONTENT_SUBSECTION_REVISION_PROMPT" in prompt:
            return _fake_content_subsection_revision(prompt)
        title = _extract(prompt, "当前小章节标题") or _extract(prompt, "章节标题") or "未命名章节"
        sources = _extract_block(prompt, "已匹配来源章节摘要") or _extract_block(prompt, "来源片段")
        manual = _extract_block(prompt, "人工补充项")
        special = _extract_block(prompt, "特殊备注")
        required_facts = _extract_required_facts(prompt)
        feedback_required_facts = _extract_feedback_required_facts(prompt)
        pattern_moves = _extract_pattern_requirements(prompt)
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
            "本节测试正文吸收以下已映射来源摘要：",
            *source_lines[:5],
            *(_render_pattern_moves_body(pattern_moves) if pattern_moves else []),
            *(_render_required_fact_body(required_facts) if required_facts else []),
            *(_render_feedback_required_fact_body(feedback_required_facts) if feedback_required_facts else []),
            "",
            "## 人工补充需补充",
        ]
        body.append("- 本地测试桩不判断现场、合同、审批和实测资料缺失情况；真实生成时由模型依据来源证据保留必要占位。")
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


def _extract_required_facts(prompt: str) -> list[str]:
    block = _extract_block(prompt, "required_source_facts（必须优先写入生成正文的原文事实）")
    if not block or block.strip() == "无。":
        return []
    facts: list[str] = []
    for line in block.splitlines():
        text = line.strip("- ").strip()
        if not text:
            continue
        fact_match = re.search(r"fact:\s*(.*?)(?:；要求:|$)", text)
        token_match = re.search(r"tokens:\s*(.*?)(?:；fact:|$)", text)
        fact_text = fact_match.group(1).strip() if fact_match else text
        token_text = token_match.group(1).strip() if token_match else ""
        facts.append(f"{fact_text}（关键值：{token_text}）" if token_text and token_text != "-" else fact_text)
    return facts


def _extract_feedback_required_facts(prompt: str) -> list[str]:
    block = _extract_block(prompt, "quality_feedback_required_facts（质量审计要求本次必须承接的事实）")
    if not block or block.strip() == "无。":
        return []
    return [line.strip("- ").strip() for line in block.splitlines() if line.strip().startswith("-")]


def _extract_pattern_requirements(prompt: str) -> list[str]:
    requirements: list[str] = []
    active_label = ""
    for line in prompt.splitlines():
        stripped = line.strip()
        if stripped in {"generation_moves:", "detail_design_rules:"}:
            active_label = stripped
            continue
        if active_label and re.match(
            r"^(human_only_items|revision_checks|corpus_basis|organization_policy|source_mapping_requirements|detail_design_rules):$",
            stripped,
        ):
            active_label = "detail_design_rules:" if stripped == "detail_design_rules:" else ""
            continue
        if active_label and stripped.startswith("- "):
            value = stripped[2:].strip()
            if value and value not in requirements:
                requirements.append(value)
        if len(requirements) >= 12:
            break
    return requirements


def _fake_content_subsection_revision(prompt: str) -> str:
    first_line = _extract(prompt, "第一行必须是")
    if not first_line:
        first_line = "### 修订小节"
    section_ids = _known_section_ids(prompt)[:3]
    source_text = "、".join(section_ids) if section_ids else "【需人工补充：可靠来源章节】"
    required_facts = _extract_content_revision_required_facts(prompt)
    lines = [
        first_line,
        f"本小节已按小节级修订动作重新组织，依据 {source_text} 对原小节进行补充。",
    ]
    if required_facts:
        lines.append("本小节已承接 content_revision_required_facts 中要求补写的来源事实：")
        lines.extend(f"- {fact}" for fact in required_facts[:8])
    lines.append("后续真实模型应结合来源章节全文展开施工对象、工艺流程、资源条件、质量安全控制和记录要求；本地 fake 输出仅用于验证小节级版本更新链路。")
    return "\n".join(lines).strip() + "\n"


def _extract_content_revision_required_facts(prompt: str) -> list[str]:
    block = _extract_block(prompt, "content_revision_required_facts")
    if not block or block.strip().lower() == "none":
        return []
    facts: list[str] = []
    for line in block.splitlines():
        text = line.strip("- ").strip()
        if not text:
            continue
        match = re.search(r"fact:\s*(.*)$", text)
        facts.append(match.group(1).strip() if match else text)
    return facts


def _render_required_fact_body(required_facts: list[str]) -> list[str]:
    return ["", "本节已吸收原文证据中的关键事实：", *[f"- {item}" for item in required_facts[:8]]]


def _render_feedback_required_fact_body(required_facts: list[str]) -> list[str]:
    return ["", "本节已按质量反馈补写以下来源事实：", *[f"- {item}" for item in required_facts[:8]]]


def _render_pattern_moves_body(pattern_moves: list[str]) -> list[str]:
    return ["", "本节已按本地施组写作模式组织以下要点：", *[f"- {item}" for item in pattern_moves[:8]]]


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
