from __future__ import annotations

import argparse
import re
import xml.etree.ElementTree as ET
from pathlib import Path
from zipfile import ZipFile


W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
NS = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}


def convert_docx_to_markdown(input_path: Path) -> str:
    with ZipFile(input_path) as archive:
        document = ET.fromstring(archive.read("word/document.xml"))
        styles = ET.fromstring(archive.read("word/styles.xml"))
    style_names = _style_names(styles)
    parts: list[str] = []
    body = document.find("w:body", NS)
    if body is None:
        return ""
    for child in body:
        if child.tag == f"{W}p":
            markdown = _paragraph_to_markdown(child, style_names)
            if markdown:
                parts.append(markdown)
        elif child.tag == f"{W}tbl":
            markdown = _table_to_markdown(child)
            if markdown:
                parts.append(markdown)
    return _clean_markdown("\n\n".join(parts))


def _style_names(styles: ET.Element) -> dict[str, str]:
    output: dict[str, str] = {}
    for style in styles.findall(".//w:style", NS):
        style_id = style.get(f"{W}styleId")
        name = style.find("w:name", NS)
        if style_id and name is not None:
            output[style_id] = name.get(f"{W}val", "")
    return output


def _paragraph_to_markdown(paragraph: ET.Element, style_names: dict[str, str]) -> str:
    text = _paragraph_text(paragraph)
    if not text:
        return ""
    style_id = _paragraph_style_id(paragraph)
    style_name = style_names.get(style_id, "")
    heading_level = _heading_level(style_name, text)
    if heading_level:
        return f"{'#' * heading_level} {_strip_heading_prefix(text)}"
    return text


def _paragraph_text(paragraph: ET.Element) -> str:
    parts: list[str] = []
    for node in paragraph.iter():
        if node.tag == f"{W}t":
            parts.append(node.text or "")
        elif node.tag == f"{W}tab":
            parts.append(" ")
        elif node.tag == f"{W}br":
            parts.append("\n")
    text = "".join(parts)
    text = re.sub(r"[ \t]+", " ", text)
    return text.strip()


def _paragraph_style_id(paragraph: ET.Element) -> str:
    ppr = paragraph.find("w:pPr", NS)
    if ppr is None:
        return ""
    style = ppr.find("w:pStyle", NS)
    if style is None:
        return ""
    return style.get(f"{W}val", "")


def _heading_level(style_name: str, text: str) -> int | None:
    match = re.search(r"标题\s*([1-6])", style_name)
    if match:
        return int(match.group(1))
    if re.match(r"^第[一二三四五六七八九十百]+章\b", text):
        return 2
    if re.match(r"^第[一二三四五六七八九十百]+节\b", text):
        return 3
    if re.match(r"^\d+(?:\.\d+){0,4}\s+\S", text):
        depth = text.split()[0].count(".") + 2
        return min(depth, 6)
    return None


def _strip_heading_prefix(text: str) -> str:
    return text.strip()


def _table_to_markdown(table: ET.Element) -> str:
    rows: list[list[str]] = []
    for row in table.findall("w:tr", NS):
        cells: list[str] = []
        for cell in row.findall("w:tc", NS):
            cell_texts = [_paragraph_text(paragraph) for paragraph in cell.findall(".//w:p", NS)]
            text = "<br>".join(item for item in cell_texts if item)
            text = text.replace("|", "\\|")
            cells.append(text)
        if any(cells):
            rows.append(cells)
    if not rows:
        return ""
    width = max(len(row) for row in rows)
    normalized = [row + [""] * (width - len(row)) for row in rows]
    header = normalized[0]
    lines = [
        "| " + " | ".join(header) + " |",
        "| " + " | ".join("---" for _ in header) + " |",
    ]
    for row in normalized[1:]:
        lines.append("| " + " | ".join(row) + " |")
    return "\n".join(lines)


def _clean_markdown(markdown: str) -> str:
    markdown = markdown.replace("\ufeff", "")
    markdown = re.sub(r"[ \t]+$", "", markdown, flags=re.M)
    markdown = re.sub(r"\n{3,}", "\n\n", markdown)
    return markdown.strip() + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="Convert a DOCX file to Markdown using the document XML.")
    parser.add_argument("input", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    markdown = convert_docx_to_markdown(args.input)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(markdown, encoding="utf-8")
    print(f"wrote {args.output} ({len(markdown)} chars)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
