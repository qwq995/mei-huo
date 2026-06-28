from __future__ import annotations

import re

from coalplan.domain.generation import ChapterDraft
from coalplan.domain.templates import TemplateNode


def merge_chapter_markdowns(title: str, drafts: list[ChapterDraft]) -> str:
    parts = [f"# {title}", ""]
    for draft in drafts:
        body = draft.markdown.strip()
        if not body:
            continue
        if body.startswith("# "):
            body = body[2:].strip()
            first_line, _, rest = body.partition("\n")
            parts.append(f"## {first_line.strip()}")
            if rest.strip():
                parts.append(rest.strip())
        else:
            parts.append(body)
        parts.append("")
    return "\n".join(parts).strip() + "\n"


def merge_template_tree_markdowns(title: str, nodes: list[TemplateNode], drafts: list[ChapterDraft]) -> str:
    drafts_by_node = {draft.node_id: draft for draft in drafts}
    parts = [f"# {title}", ""]
    for node in nodes:
        _append_node(parts, node, drafts_by_node, depth=0)
    return "\n".join(parts).strip() + "\n"


def _append_node(parts: list[str], node: TemplateNode, drafts_by_node: dict[str, ChapterDraft], *, depth: int) -> None:
    # Render from the actual editable tree depth instead of template node.level.
    # Refined outlines can preserve deep template levels, which previously pushed
    # chapter bodies down to ###### and made the final document hard to read.
    heading_level = min(2 + depth, 5)
    parts.append(f"{'#' * heading_level} {node.title}")
    draft = drafts_by_node.get(node.id)
    if draft:
        body = _strip_first_heading(draft.markdown)
        body = _extract_final_document_body(body)
        body = _normalize_body_headings(body, parent_level=heading_level)
        if body.strip():
            parts.append(body.strip())
    parts.append("")
    for child in node.children:
        _append_node(parts, child, drafts_by_node, depth=depth + 1)


def _strip_first_heading(markdown: str) -> str:
    lines = markdown.strip().splitlines()
    if lines and lines[0].startswith("# "):
        return "\n".join(lines[1:]).strip()
    return markdown.strip()


def _normalize_body_headings(markdown: str, *, parent_level: int) -> str:
    output: list[str] = []
    for line in markdown.splitlines():
        stripped = line.lstrip()
        leading_spaces = line[: len(line) - len(stripped)]
        if stripped.startswith("#"):
            hashes, _, rest = stripped.partition(" ")
            if rest and set(hashes) == {"#"}:
                relative_level = max(1, len(hashes) - 1)
                level = min(parent_level + relative_level, 6)
                output.append(f"{leading_spaces}{'#' * level} {rest}")
                continue
        output.append(line)
    return "\n".join(output)


def _extract_final_document_body(markdown: str) -> str:
    """Keep the user-facing chapter prose out of the trace-oriented contract wrapper.

    Chapter versions intentionally keep trace modules such as source summary and manual
    placeholders for review. The final merged document should read like a clean
    construction organization design, so it uses only the `生成正文` section when present.
    """
    sections = _split_level_two_sections(markdown)
    generated = sections.get("生成正文")
    if generated and generated.strip():
        return generated.strip()
    return _drop_trace_sections(markdown).strip()


def _split_level_two_sections(markdown: str) -> dict[str, str]:
    sections: dict[str, list[str]] = {}
    current: str | None = None
    for line in markdown.splitlines():
        match = re.match(r"^##\s+(.+?)\s*$", line)
        if match:
            current = match.group(1).strip()
            sections.setdefault(current, [])
            continue
        if current is not None:
            sections[current].append(line)
    return {key: "\n".join(value).strip() for key, value in sections.items()}


def _drop_trace_sections(markdown: str) -> str:
    trace_headings = {"主要来源摘要", "人工补充需补充", "特殊备注"}
    output: list[str] = []
    skipping = False
    for line in markdown.splitlines():
        match = re.match(r"^##\s+(.+?)\s*$", line)
        if match:
            heading = match.group(1).strip()
            skipping = heading in trace_headings
            if heading == "生成正文":
                skipping = False
                continue
        if not skipping:
            output.append(line)
    return "\n".join(output)
