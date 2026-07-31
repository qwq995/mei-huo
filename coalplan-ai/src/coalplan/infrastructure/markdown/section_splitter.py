from __future__ import annotations

import re

from coalplan.domain.documents import MarkdownSection, stable_id


KEYWORD_CANDIDATES = [
    "工程概况",
    "火区",
    "交通",
    "自然地理",
    "勘查",
    "注水",
    "钻孔",
    "灌浆",
    "注浆",
    "覆盖封堵",
    "质量",
    "安全",
    "环境保护",
    "文明施工",
    "应急",
    "灭火效果",
    "监测",
    "工期",
    "进度",
    "机械",
    "劳动力",
    "供水",
    "供电",
]


class MarkdownSectionSplitter:
    atx_heading_re = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
    numbered_heading_re = re.compile(r"^(\d+(?:\.\d+){0,4})\s+(.+?)\s*$")
    chinese_chapter_re = re.compile(r"^(第[一二三四五六七八九十百]+[章节])\s*(.+?)?\s*$")

    def split_sections(self, text: str, *, source_file: str) -> list[MarkdownSection]:
        lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
        heading_events = self._collect_heading_events(lines)
        if not heading_events:
            body = text.strip()
            return [
                MarkdownSection(
                    id=stable_id("sec", source_file, "root"),
                    title_path=[source_file],
                    level=0,
                    content=body,
                    keywords=extract_keywords(f"{source_file}\n{body}"),
                    source_file=source_file,
                    start_line=1,
                    end_line=len(lines),
                )
            ] if body else []

        stack: list[tuple[int, str]] = []
        sections: list[MarkdownSection] = []
        for index, (line_no, level, title) in enumerate(heading_events):
            next_line = heading_events[index + 1][0] if index + 1 < len(heading_events) else len(lines)
            body = "\n".join(lines[line_no + 1:next_line]).strip()
            while stack and stack[-1][0] >= level:
                stack.pop()
            stack.append((level, title))
            path = [item[1] for item in stack]
            sections.append(
                MarkdownSection(
                    # Repeated volume/chapter headings are common in large tender files.
                    # The source line keeps ids unique while remaining deterministic for
                    # the same normalized document.
                    id=stable_id("sec", source_file, str(line_no + 1), *path),
                    title_path=path,
                    level=level,
                    content=body,
                    keywords=extract_keywords(title + "\n" + body),
                    source_file=source_file,
                    start_line=line_no + 1,
                    end_line=next_line,
                )
            )
        return sections

    def _collect_heading_events(self, lines: list[str]) -> list[tuple[int, int, str]]:
        events: list[tuple[int, int, str]] = []
        for index, line in enumerate(lines):
            stripped = line.strip()
            if not stripped or stripped.startswith(("-", "*", "|", ">")):
                continue
            atx = self.atx_heading_re.match(stripped)
            if atx:
                title = atx.group(2).strip()
                if title and not _is_quantity_row(title):
                    events.append((index, len(atx.group(1)), title))
                continue
            chapter = self.chinese_chapter_re.match(stripped)
            if chapter:
                title = stripped
                level = 1 if chapter.group(1).endswith("章") else 2
                events.append((index, level, title))
                continue
            numbered = self.numbered_heading_re.match(stripped)
            if numbered and len(stripped) <= 120:
                # Tender quantity lists commonly start with forms such as
                # "8 线：110kV..." or "3 台：变压器...". They are data rows,
                # not outline headings, and must not become parents of the
                # numbered clauses that follow.
                if "." not in numbered.group(1) and _is_quantity_row(
                    f"{numbered.group(1)}{numbered.group(2).strip()}"
                ):
                    continue
                depth = numbered.group(1).count(".") + 1
                title = f"{numbered.group(1)} {numbered.group(2).strip()}"
                events.append((index, min(depth + 1, 6), title))
                continue
            if stripped in {"前言", "附件", "总体判断"}:
                events.append((index, 1, stripped))
        return events


def _is_quantity_row(value: str) -> bool:
    return bool(
        re.match(
            r"^\d+(?:\s*[-~～至]\s*\d+)?\s*"
            r"(?:线|项|台|套|座|处|人|天|年|月|根|孔|组|个|辆|部|标段)\s*[：:]",
            value.strip(),
        )
    )


def extract_keywords(text: str) -> list[str]:
    keywords: list[str] = []
    for candidate in KEYWORD_CANDIDATES:
        if candidate in text and candidate not in keywords:
            keywords.append(candidate)
    for match in re.findall(r"\d+(?:\.\d+)?\s*(?:m³|m3|m|km|kV|%|天|月|年|套|台|项)", text, re.I):
        if match not in keywords:
            keywords.append(match)
    return keywords[:30]
