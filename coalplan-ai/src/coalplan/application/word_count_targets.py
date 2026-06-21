from __future__ import annotations

import re
from dataclasses import dataclass

from pydantic import BaseModel

from coalplan.domain.templates import TemplateNode


HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$")


class WordCountEstimate(BaseModel):
    node_id: str
    title: str
    target_word_count: int
    method: str
    matched_reference_title: str | None = None
    reference_word_count: int | None = None


def estimate_word_count_targets(nodes: list[TemplateNode], reference_markdown: str | None = None) -> list[WordCountEstimate]:
    reference_blocks = _reference_blocks(reference_markdown or "")
    raw_estimates: list[WordCountEstimate] = []
    for node in _walk(nodes):
        if not node.has_generation_contract:
            continue
        matched = _best_reference_match(node.title, reference_blocks)
        if matched:
            target = _round_target(matched.word_count)
            raw_estimates.append(
                WordCountEstimate(
                    node_id=node.id,
                    title=node.title,
                    target_word_count=target,
                    method="reference_title_match",
                    matched_reference_title=matched.title,
                    reference_word_count=matched.word_count,
                )
            )
        else:
            raw_estimates.append(
                WordCountEstimate(
                    node_id=node.id,
                    title=node.title,
                    target_word_count=_fallback_target(node),
                    method="fallback_by_level_and_title",
                )
            )
    return _smooth_estimates(raw_estimates)


def apply_word_count_estimates(nodes: list[TemplateNode], estimates: list[WordCountEstimate]) -> list[TemplateNode]:
    by_id = {estimate.node_id: estimate.target_word_count for estimate in estimates}
    return [_apply_node(node, by_id) for node in nodes]


@dataclass(frozen=True)
class _ReferenceBlock:
    title: str
    level: int
    content: str
    word_count: int


def _reference_blocks(markdown: str) -> list[_ReferenceBlock]:
    if not markdown.strip():
        return []
    lines = markdown.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    headings: list[tuple[int, int, str]] = []
    for index, line in enumerate(lines, start=1):
        match = HEADING_RE.match(line.strip())
        if match:
            headings.append((index, len(match.group(1)), match.group(2).strip()))
    blocks: list[_ReferenceBlock] = []
    for offset, (line_no, level, title) in enumerate(headings):
        next_line = len(lines) + 1
        for candidate_line_no, candidate_level, _ in headings[offset + 1:]:
            if candidate_level <= level:
                next_line = candidate_line_no
                break
        content = "\n".join(lines[line_no: next_line - 1]).strip()
        count = count_words(content)
        if count > 0:
            blocks.append(_ReferenceBlock(title=title, level=level, content=content, word_count=count))
    if not blocks:
        count = count_words(markdown)
        if count:
            blocks.append(_ReferenceBlock(title="全文", level=1, content=markdown, word_count=count))
    return blocks


def count_words(text: str) -> int:
    # For Chinese construction documents, a CJK character is the most useful length unit;
    # latin words and numbers are counted as one each.
    cjk = re.findall(r"[\u4e00-\u9fff]", text or "")
    latin = re.findall(r"[A-Za-z][A-Za-z0-9_/-]*|\d+(?:\.\d+)?%?", text or "")
    return len(cjk) + len(latin)


def _best_reference_match(title: str, blocks: list[_ReferenceBlock]) -> _ReferenceBlock | None:
    if not blocks:
        return None
    norm_title = _normalize_title(title)
    scored: list[tuple[float, _ReferenceBlock]] = []
    for block in blocks:
        norm_block = _normalize_title(block.title)
        if not norm_block:
            continue
        score = _similarity(norm_title, norm_block)
        if norm_title and (norm_title in norm_block or norm_block in norm_title):
            score += 0.4
        if score >= 0.42:
            scored.append((score, block))
    if not scored:
        return None
    scored.sort(key=lambda item: (item[0], item[1].word_count), reverse=True)
    return scored[0][1]


def _normalize_title(title: str) -> str:
    text = re.sub(r"^#+\s*", "", title or "")
    text = re.sub(r"第[一二三四五六七八九十百\d]+[章节篇]\s*", "", text)
    text = re.sub(r"^\d+(?:\.\d+)*\s*", "", text)
    text = re.sub(r"[^\u4e00-\u9fffA-Za-z0-9]+", "", text)
    return text.lower()


def _similarity(left: str, right: str) -> float:
    if not left or not right:
        return 0.0
    left_terms = set(_terms(left))
    right_terms = set(_terms(right))
    if not left_terms or not right_terms:
        return 0.0
    overlap = len(left_terms & right_terms)
    return overlap / max(len(left_terms), len(right_terms))


def _terms(text: str) -> list[str]:
    terms = re.findall(r"[\u4e00-\u9fff]{2,6}|[A-Za-z][A-Za-z0-9]{1,20}|\d+(?:\.\d+)?", text or "")
    if not terms and text:
        terms = [text]
    return terms


def _fallback_target(node: TemplateNode) -> int:
    title = node.title
    if "工程概况" in title or "施工方案" in title or "施工总体" in title:
        return 1200
    if "重点" in title or "难点" in title or "安全" in title or "质量" in title or "进度" in title:
        return 1000
    if node.level <= 1:
        return 900
    if node.level == 2:
        return 800
    return 650


def _round_target(count: int) -> int:
    count = max(350, min(6000, count))
    return int(round(count / 50) * 50)


def _smooth_estimates(estimates: list[WordCountEstimate]) -> list[WordCountEstimate]:
    if not estimates:
        return estimates
    counts = [estimate.target_word_count for estimate in estimates]
    average = sum(counts) / len(counts)
    smoothed: list[WordCountEstimate] = []
    for estimate in estimates:
        target = estimate.target_word_count
        if estimate.method.startswith("fallback") and average:
            target = int(round(((target + average) / 2) / 50) * 50)
        smoothed.append(
            WordCountEstimate(
                node_id=estimate.node_id,
                title=estimate.title,
                target_word_count=max(300, min(6000, target)),
                method=estimate.method,
                matched_reference_title=estimate.matched_reference_title,
                reference_word_count=estimate.reference_word_count,
            )
        )
    return smoothed


def _apply_node(node: TemplateNode, by_id: dict[str, int]) -> TemplateNode:
    return TemplateNode(
        id=node.id,
        title=node.title,
        level=node.level,
        source_rules=node.source_rules,
        auto_fill=node.auto_fill,
        manual_fill=node.manual_fill,
        special_notes=node.special_notes,
        target_word_count=by_id.get(node.id, node.target_word_count),
        children=[_apply_node(child, by_id) for child in node.children],
    )


def _walk(nodes: list[TemplateNode]):
    for node in nodes:
        yield node
        yield from _walk(node.children)
