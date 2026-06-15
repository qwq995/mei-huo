from __future__ import annotations

import re

from coalplan.application.serialization import dump_model, to_json_text
from coalplan.domain.documents import MarkdownSection, SourceToc, SourceTocItem
from coalplan.ports.repository import ArtifactRepository


def persist_source_index(project_id: str, sections: list[MarkdownSection], artifacts: ArtifactRepository) -> SourceToc:
    items = [_toc_item(section) for section in sections]
    for section in sections:
        artifacts.write_text(project_id, f"inputs/sections/{section.id}.md", _section_markdown(section))
    sections_json = [dump_model(section) for section in sections]
    artifacts.write_text(project_id, "inputs/sections.json", to_json_text(sections_json))
    toc = SourceToc(items=items)
    toc.artifact_json_path = artifacts.write_text(project_id, "inputs/toc.json", to_json_text([dump_model(item) for item in items]))
    toc.artifact_markdown_path = artifacts.write_text(project_id, "inputs/toc.md", render_toc_markdown(items))
    return toc


def render_toc_markdown(items: list[SourceTocItem]) -> str:
    lines = ["# 投标文档目录", ""]
    for item in items:
        indent = "  " * max(0, item.level - 1)
        title = " > ".join(item.title_path)
        lines.append(f"{indent}- `{item.section_id}` {title} ({item.char_count} 字)")
    return "\n".join(lines).strip() + "\n"


def _toc_item(section: MarkdownSection) -> SourceTocItem:
    return SourceTocItem(
        section_id=section.id,
        title_path=section.title_path,
        level=section.level,
        start_line=section.start_line,
        end_line=section.end_line,
        keywords=section.keywords,
        char_count=len(section.content),
        snippet=_snippet(section.content),
    )


def _section_markdown(section: MarkdownSection) -> str:
    heading = "#" * min(max(section.level, 1), 6)
    return f"{heading} {section.title}\n\n{section.content.strip()}\n"


def _snippet(text: str, limit: int = 220) -> str:
    compact = re.sub(r"\s+", " ", text).strip()
    return compact if len(compact) <= limit else compact[:limit].rstrip() + "..."
