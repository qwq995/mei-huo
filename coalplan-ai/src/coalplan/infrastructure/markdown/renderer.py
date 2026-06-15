from __future__ import annotations

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
        _append_node(parts, node, drafts_by_node)
    return "\n".join(parts).strip() + "\n"


def _append_node(parts: list[str], node: TemplateNode, drafts_by_node: dict[str, ChapterDraft]) -> None:
    heading_level = min(node.level + 1, 6)
    parts.append(f"{'#' * heading_level} {node.title}")
    draft = drafts_by_node.get(node.id)
    if draft:
        body = _strip_first_heading(draft.markdown)
        body = _demote_headings(body, shift=max(1, node.level))
        if body.strip():
            parts.append(body.strip())
    parts.append("")
    for child in node.children:
        _append_node(parts, child, drafts_by_node)


def _strip_first_heading(markdown: str) -> str:
    lines = markdown.strip().splitlines()
    if lines and lines[0].startswith("# "):
        return "\n".join(lines[1:]).strip()
    return markdown.strip()


def _demote_headings(markdown: str, *, shift: int) -> str:
    output: list[str] = []
    for line in markdown.splitlines():
        stripped = line.lstrip()
        leading_spaces = line[: len(line) - len(stripped)]
        if stripped.startswith("#"):
            hashes, _, rest = stripped.partition(" ")
            if rest and set(hashes) == {"#"}:
                level = min(len(hashes) + shift, 6)
                output.append(f"{leading_spaces}{'#' * level} {rest}")
                continue
        output.append(line)
    return "\n".join(output)
