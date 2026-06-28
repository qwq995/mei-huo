from __future__ import annotations

import re
from dataclasses import dataclass

from coalplan.domain.documents import MarkdownSection, stable_id
from coalplan.domain.outline import SourceEvidenceSpan, SourceMappingMatch
from coalplan.domain.templates import TemplateNode


MAX_QUOTE_CHARS = 900
MAX_SUMMARY_CHARS = 180


def build_source_evidence(
    *,
    node: TemplateNode,
    matches: list[SourceMappingMatch],
    sections: list[MarkdownSection],
    max_total: int = 14,
    max_per_section: int = 4,
    extra_terms: list[str] | None = None,
) -> list[SourceEvidenceSpan]:
    section_by_id = {section.id: section for section in sections}
    terms_by_module = _terms_by_module(node)
    policy_terms = _ordered_terms(extra_terms or [])
    if policy_terms:
        terms_by_module["policy_context"] = policy_terms
    fallback_terms = _merge_ordered(
        _ordered_terms([node.title, *node.source_rules, *node.auto_fill, *node.manual_fill, *node.special_notes]),
        policy_terms,
    )
    output: list[SourceEvidenceSpan] = []
    seen_quotes: set[str] = set()

    for match in matches:
        section = section_by_id.get(match.section_id)
        if section is None:
            continue
        chunks = _paragraph_chunks(section)
        scored = [_score_chunk(chunk, terms_by_module, fallback_terms, match) for chunk in chunks]
        scored.sort(key=lambda item: item.score, reverse=True)
        selected = [item for item in scored if item.score > 0][:max_per_section]
        if not selected and scored:
            selected = scored[:1]
        for item in selected:
            quote_key = _compact(item.chunk.text)[:240]
            if quote_key in seen_quotes:
                continue
            seen_quotes.add(quote_key)
            output.append(_to_evidence_span(node=node, match=match, section=section, item=item))
            if len(output) >= max_total:
                return output

    return output


def attach_evidence_ids(matches: list[SourceMappingMatch], evidence: list[SourceEvidenceSpan]) -> None:
    by_section: dict[str, list[str]] = {}
    for span in evidence:
        by_section.setdefault(span.section_id, []).append(span.evidence_id)
    for match in matches:
        match.evidence_ids = by_section.get(match.section_id, [])


@dataclass(frozen=True)
class _Chunk:
    text: str
    start_line: int | None
    end_line: int | None


@dataclass(frozen=True)
class _ScoredChunk:
    chunk: _Chunk
    score: float
    template_module: str
    matched_terms: list[str]
    reason: str


def _paragraph_chunks(section: MarkdownSection) -> list[_Chunk]:
    lines = section.content.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    content_start = (section.start_line or 1) + (1 if section.level > 0 else 0)
    chunks: list[_Chunk] = []
    current: list[tuple[int, str]] = []

    def flush() -> None:
        if not current:
            return
        text = "\n".join(line for _, line in current).strip()
        if text:
            chunks.extend(_split_long_chunk(text, content_start + current[0][0], content_start + current[-1][0]))
        current.clear()

    for index, line in enumerate(lines):
        stripped = line.strip()
        if not stripped:
            flush()
            continue
        if current and _line_kind(current[-1][1]) != _line_kind(line):
            flush()
        current.append((index, line))
    flush()

    if not chunks and section.content.strip():
        chunks.append(_Chunk(section.content.strip(), section.start_line, section.end_line))
    return chunks


def _split_long_chunk(text: str, start_line: int, end_line: int) -> list[_Chunk]:
    if len(text) <= MAX_QUOTE_CHARS:
        return [_Chunk(text=text, start_line=start_line, end_line=end_line)]
    parts = re.split(r"(?<=[。；;.!?？])\s*", text)
    chunks: list[_Chunk] = []
    buffer = ""
    for part in parts:
        if not part:
            continue
        if buffer and len(buffer) + len(part) > MAX_QUOTE_CHARS:
            chunks.append(_Chunk(text=buffer.strip(), start_line=start_line, end_line=end_line))
            buffer = ""
        buffer += part
    if buffer.strip():
        chunks.append(_Chunk(text=buffer.strip(), start_line=start_line, end_line=end_line))
    return chunks or [_Chunk(text=text[:MAX_QUOTE_CHARS].rstrip(), start_line=start_line, end_line=end_line)]


def _line_kind(line: str) -> str:
    stripped = line.strip()
    if stripped.startswith("|"):
        return "table"
    if re.match(r"^[-*+]\s+", stripped):
        return "list"
    return "paragraph"


def _score_chunk(
    chunk: _Chunk,
    terms_by_module: dict[str, list[str]],
    fallback_terms: list[str],
    match: SourceMappingMatch,
) -> _ScoredChunk:
    text = _compact(chunk.text)
    module_scores: dict[str, float] = {}
    module_terms: dict[str, list[str]] = {}
    for module, terms in terms_by_module.items():
        score, matched = _term_score(text, terms)
        module_scores[module] = score
        module_terms[module] = matched
    best_module = max(module_scores, key=module_scores.get) if module_scores else "main_sources"
    best_score = module_scores.get(best_module, 0.0)
    matched_terms = module_terms.get(best_module, [])
    fallback_score, fallback_matched = _term_score(text, fallback_terms)
    if fallback_score > best_score:
        best_score = fallback_score
        matched_terms = fallback_matched
    if re.search(r"\d", text):
        best_score += 0.8
    if match.usage and match.usage in {"quantity", "schedule", "quality", "safety", "environment", "acceptance"}:
        best_score += 0.5
    confidence = min(1.0, 0.25 + best_score / 12)
    reason = "匹配模板关键词" if matched_terms else "作为已匹配章节的代表性原文段落"
    return _ScoredChunk(
        chunk=chunk,
        score=best_score + match.confidence,
        template_module=best_module,
        matched_terms=matched_terms[:8],
        reason=reason,
    )


def _term_score(text: str, terms: list[str]) -> tuple[float, list[str]]:
    score = 0.0
    matched: list[str] = []
    for term in terms:
        if not term:
            continue
        count = text.count(term)
        if not count:
            continue
        matched.append(term)
        score += min(count, 4) * (1.0 + min(len(term), 8) / 12)
    return score, matched


def _to_evidence_span(
    *,
    node: TemplateNode,
    match: SourceMappingMatch,
    section: MarkdownSection,
    item: _ScoredChunk,
) -> SourceEvidenceSpan:
    quote = item.chunk.text.strip()
    if len(quote) > MAX_QUOTE_CHARS:
        quote = quote[:MAX_QUOTE_CHARS].rstrip() + "..."
    evidence_id = stable_id("ev", node.id, section.id, item.chunk.start_line, item.chunk.end_line, quote[:80])
    confidence = min(1.0, max(0.0, 0.35 + item.score / 14))
    return SourceEvidenceSpan(
        evidence_id=evidence_id,
        section_id=section.id,
        title_path=section.title_path,
        start_line=item.chunk.start_line,
        end_line=item.chunk.end_line,
        usage=match.usage,
        template_module=item.template_module,
        matched_terms=item.matched_terms,
        quote=quote,
        summary=_summary(quote),
        reason=_join_reason(match.reason, item.reason),
        confidence=round(confidence, 3),
    )


def _terms_by_module(node: TemplateNode) -> dict[str, list[str]]:
    return {
        "title": _ordered_terms([node.title]),
        "main_sources": _ordered_terms(node.source_rules),
        "auto_fill": _ordered_terms(node.auto_fill),
        "manual_fill": _ordered_terms(node.manual_fill),
        "special_notes": _ordered_terms(node.special_notes),
    }


def _ordered_terms(texts: list[str]) -> list[str]:
    ordered: list[str] = []
    for text in texts:
        for term in _extract_terms(text):
            if term not in ordered:
                ordered.append(term)
    return ordered[:80]


def _merge_ordered(*groups: list[str]) -> list[str]:
    merged: list[str] = []
    for group in groups:
        for item in group:
            if item not in merged:
                merged.append(item)
    return merged[:100]


def _extract_terms(text: str) -> list[str]:
    terms: list[str] = []
    for token in re.findall(r"[\u4e00-\u9fff]{2,12}|[A-Za-z][A-Za-z0-9_-]{1,30}|\d+(?:\.\d+)?[A-Za-z%]*", text or ""):
        cleaned = token.strip("，。；;：:、（）()[]【】")
        if len(cleaned) >= 2 and cleaned not in _STOP_TERMS:
            terms.append(cleaned)
    return terms


def _summary(text: str) -> str:
    compact = _compact(text)
    if len(compact) <= MAX_SUMMARY_CHARS:
        return compact
    sentence = re.split(r"(?<=[。；;.!?？])", compact, maxsplit=1)[0].strip()
    if 30 <= len(sentence) <= MAX_SUMMARY_CHARS:
        return sentence
    return compact[:MAX_SUMMARY_CHARS].rstrip() + "..."


def _compact(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _join_reason(mapping_reason: str, evidence_reason: str) -> str:
    parts = [part for part in [mapping_reason.strip(), evidence_reason.strip()] if part]
    return "；".join(parts)


_STOP_TERMS = {
    "主要来源",
    "自动补充",
    "人工补充",
    "特殊备注",
    "施工组织",
    "设计",
    "章节",
    "内容",
    "需要",
    "补充",
    "确认",
}
