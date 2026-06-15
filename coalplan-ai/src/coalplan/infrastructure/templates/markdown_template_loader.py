from __future__ import annotations

import re
from pathlib import Path

from coalplan.domain.templates import TemplateNode, TemplateTree, make_node_id


MODULE_NAMES = {
    "[主要来源]": "source_rules",
    "[自动补充]": "auto_fill",
    "[人工补充需补充]": "manual_fill",
    "[特殊备注]": "special_notes",
    # Backward-compatible aliases for previously mojibake-saved templates.
    "[涓昏鏉ユ簮]": "source_rules",
    "[鑷姩琛ュ厖]": "auto_fill",
    "[浜哄伐琛ュ厖闇€琛ュ厖]": "manual_fill",
    "[鐗规畩澶囨敞]": "special_notes",
}


class MarkdownTemplateLoader:
    """Load a template tree from the standardized four-module markdown format."""

    def __init__(self, template_dir: Path) -> None:
        self.template_dir = template_dir

    def list_templates(self) -> list[dict[str, str]]:
        templates: list[dict[str, str]] = []
        for path in sorted(self.template_dir.glob("*_template.md")):
            template_id = path.name[: -len("_template.md")]
            try:
                tree = self.load(template_id)
                name = tree.name
            except Exception:
                name = path.stem
            templates.append({"template_id": template_id, "name": name, "path": str(path.resolve())})
        return templates

    def load(self, template_id: str) -> TemplateTree:
        path = self.template_dir / f"{template_id}_template.md"
        if not path.exists():
            raise FileNotFoundError(f"Template not found: {path}")
        return self.load_path(path, template_id=template_id)

    def load_path(self, path: Path, *, template_id: str) -> TemplateTree:
        text = path.read_text(encoding="utf-8-sig")
        text = _strip_frontmatter(text)
        lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
        name = path.stem
        root_nodes: list[TemplateNode] = []
        stack: list[TemplateNode] = []
        current: TemplateNode | None = None
        active_module: str | None = None

        for raw_line in lines:
            line = raw_line.strip()
            if not line:
                continue
            if line.startswith("# "):
                name = line[2:].strip()
                current = None
                active_module = None
                continue
            level = _heading_level(line)
            if level is not None and line not in MODULE_NAMES:
                title = _clean_heading_title(line)
                while stack and stack[-1].level >= level:
                    stack.pop()
                path_titles = [node.title for node in stack] + [title]
                node = TemplateNode(id=make_node_id(path_titles), title=title, level=level)
                if stack:
                    stack[-1].children.append(node)
                else:
                    root_nodes.append(node)
                stack.append(node)
                current = node
                active_module = None
                continue
            if line in MODULE_NAMES:
                active_module = MODULE_NAMES[line]
                continue
            if current is not None and active_module and line.startswith("-"):
                item = line.lstrip("-").strip()
                getattr(current, active_module).append(item)

        return TemplateTree(id=template_id, name=name, nodes=root_nodes)


def _strip_frontmatter(text: str) -> str:
    return re.sub(r"\A---\n.*?\n---\n", "", text, flags=re.S)


def _heading_level(line: str) -> int | None:
    if line.startswith("## "):
        return 1
    if line in {"前言", "总体判断", "附件", "鍓嶈█", "鎬讳綋鍒ゆ柇", "闄勪欢"}:
        return 1
    if re.match(r"^第\s*[一二三四五六七八九十百\d]+\s*章\b", line):
        return 1
    if re.match(r"^第\s*[一二三四五六七八九十百\d]+\s*节\b", line):
        return 2
    if re.match(r"^绗琜涓€浜屼笁鍥涗簲鍏竷鍏節鍗佺櫨]+绔燶b", line):
        return 1
    if re.match(r"^绗琜涓€浜屼笁鍥涗簲鍏竷鍏節鍗佺櫨]+鑺俓b", line):
        return 2
    if re.match(r"^\d+(?:\.\d+){1,4}\s+", line):
        return min(line.split()[0].count(".") + 2, 6)
    if re.match(r"^\d+\s*至\s*\d+\s+", line):
        return 1
    if re.match(r"^\d+\s+\S+", line):
        return 1
    if re.match(r"^后续.+章节$", line):
        return 1
    return None


def _clean_heading_title(line: str) -> str:
    if line.startswith("## "):
        return line[3:].strip()
    return line.strip()
