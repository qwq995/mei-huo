from __future__ import annotations

import re


TRACE_SECTION_TITLES = {"主要来源摘要", "人工补充需补充", "特殊备注"}


def editable_chapter_markdown(markdown: str, *, expected_title: str = "") -> str:
    """Convert the trace-oriented generation contract into editable prose."""

    source = (markdown or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    if not source:
        return f"# {expected_title}\n" if expected_title else ""

    title = expected_title.strip() or _first_level_title(source)
    generated = _level_two_section(source, "生成正文")
    body = generated if generated is not None else _drop_trace_sections(source)
    body = _strip_first_level_heading(body)
    body = _remove_internal_annotations(body).strip()

    if title:
        return f"# {title}\n\n{body}".rstrip() + "\n"
    return body.rstrip() + ("\n" if body else "")


def _first_level_title(markdown: str) -> str:
    match = re.search(r"^#\s+(.+?)\s*$", markdown, flags=re.M)
    return match.group(1).strip() if match else ""


def _level_two_section(markdown: str, title: str) -> str | None:
    match = re.search(
        rf"^##\s+{re.escape(title)}\s*$\n?(.*?)(?=^##\s+|\Z)",
        markdown,
        flags=re.M | re.S,
    )
    return match.group(1) if match else None


def _drop_trace_sections(markdown: str) -> str:
    output: list[str] = []
    skipping = False
    for line in markdown.splitlines():
        heading = re.match(r"^##\s+(.+?)\s*$", line.strip())
        if heading:
            section_title = heading.group(1).strip()
            if section_title == "生成正文":
                skipping = False
                continue
            skipping = section_title in TRACE_SECTION_TITLES
            if skipping:
                continue
        if not skipping:
            output.append(line)
    return "\n".join(output)


def _strip_first_level_heading(markdown: str) -> str:
    return re.sub(r"^#\s+.+?\s*$\n?", "", markdown, count=1, flags=re.M).strip()


def _remove_internal_annotations(markdown: str) -> str:
    cleaned: list[str] = []
    for line in markdown.splitlines():
        line = re.sub(
            r"\s*(?:[（(][^()（）]*\b(?:evidence_id|section_id|atom_id|fact_id)\s*[:=][^()（）]*[）)]|"
            r"\[[^\[\]]*\b(?:evidence_id|section_id|atom_id|fact_id)\s*[:=][^\[\]]*\])",
            "",
            line,
            flags=re.I,
        )
        line = re.sub(
            r"\b(?:evidence_id|section_id|atom_id|fact_id)\s*[:=]\s*[^\s，。；;，,]+",
            "",
            line,
            flags=re.I,
        )
        line = re.sub(r"【需人工补充：[^】]+】", "", line).rstrip()
        if re.match(r"^\s*[-*]\s*[。；;，,：:]?\s*$", line):
            continue
        cleaned.append(line)
    return "\n".join(cleaned)
