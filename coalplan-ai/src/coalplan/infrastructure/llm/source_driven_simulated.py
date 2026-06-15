from __future__ import annotations

import re
from typing import Any

from .fake_llm import FakeLLMClient


class SourceDrivenSimulatedLLMClient:
    """Local deterministic simulator that drafts chapters from retrieved source snippets."""

    def complete(self, prompt: str) -> str:
        title = _extract_line(prompt, "当前小章节标题") or "未命名章节"
        source_lines = _extract_bullets(_extract_block(prompt, "已匹配来源章节摘要"))
        manual_items = _extract_bullets(_extract_block(prompt, "人工补充项"))
        auto_items = _extract_bullets(_extract_block(prompt, "模板自动补充"))
        special_items = _extract_bullets(_extract_block(prompt, "特殊备注"))
        if not source_lines:
            source_lines = ["未在投标文档中识别到强匹配章节。"]
        if not manual_items:
            manual_items = ["现场核验资料、合同数据或审批信息"]

        facts = [_clean_source_fact(item) for item in source_lines]
        facts = [item for item in facts if item]
        body = [
            f"# {title}",
            "",
            "## 主要来源摘要",
            *[f"- {line}" for line in source_lines[:6]],
            "",
            "## 生成正文",
            _opening_sentence(title, bool(facts)),
        ]
        if facts:
            body.append("结合投标技术文件，可形成以下实施性内容：")
            body.extend(f"- {fact}" for fact in facts[:8])
        if auto_items:
            body.append("")
            body.append("编制时可按模板要求进一步组织为施工部署、工艺流程、质量安全控制和资料归档要求。")
            body.extend(f"- {item}" for item in auto_items[:4])
        body.extend(
            [
                "",
                "对投标文件已明确的信息，可转写为施工组织设计正文；对孔位、参数、审批、监测和验收等实施阶段数据，应保留人工确认占位。",
                "",
                "## 人工补充需补充",
            ]
        )
        body.extend(f"- 【需人工补充：{_strip_bullet(item)}】" for item in manual_items[:10])
        if special_items:
            body.extend(["", "## 特殊备注"])
            body.extend(f"- {item}" for item in special_items[:6])
        return "\n".join(body).strip() + "\n"

    def complete_json(self, prompt: str, *, schema_name: str) -> dict[str, Any]:
        return FakeLLMClient().complete_json(prompt, schema_name=schema_name)


def _extract_line(prompt: str, label: str) -> str:
    match = re.search(rf"{re.escape(label)}[:：]\s*(.+)", prompt)
    return match.group(1).strip() if match else ""


def _extract_block(prompt: str, label: str) -> str:
    match = re.search(rf"## {re.escape(label)}\n(.*?)(?=\n## |\Z)", prompt, re.S)
    return match.group(1).strip() if match else ""


def _extract_bullets(block: str) -> list[str]:
    items: list[str] = []
    for line in block.splitlines():
        line = line.strip()
        if line.startswith("-"):
            item = line.lstrip("-").strip()
            if item:
                items.append(item)
    return items


def _clean_source_fact(source_line: str) -> str:
    text = _strip_bullet(source_line)
    if "；摘要：" in text:
        path, summary = text.split("；摘要：", 1)
        path = path.replace("section_id:", "来源").strip()
        return f"{path} 显示：{_shorten(summary.strip(), 220)}"
    if "未在投标文档中识别到" in text:
        return ""
    return _shorten(text, 220)


def _opening_sentence(title: str, has_sources: bool) -> str:
    if has_sources:
        return f"本节围绕“{title}”编写，优先采用投标技术文件中可追溯的工程信息、工艺内容和控制要求。"
    return f"本节围绕“{title}”编写，当前未识别到强匹配来源，仅形成结构性草稿并保留人工补充项。"


def _strip_bullet(text: str) -> str:
    return text.strip().strip("。；; ")


def _shorten(text: str, limit: int) -> str:
    compact = re.sub(r"\s+", " ", text).strip()
    return compact if len(compact) <= limit else compact[:limit].rstrip() + "..."
