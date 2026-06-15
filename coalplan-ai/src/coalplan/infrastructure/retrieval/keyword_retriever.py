from __future__ import annotations

import re

from coalplan.domain.documents import MarkdownSection
from coalplan.domain.generation import SourceMatch
from coalplan.domain.templates import TemplateNode


class KeywordSourceRetriever:
    def retrieve(self, node: TemplateNode, sections: list[MarkdownSection], *, limit: int = 3) -> list[SourceMatch]:
        query_terms = _query_terms(node)
        matches: list[SourceMatch] = []
        for section in sections:
            if not section.content.strip():
                continue
            haystack = f"{section.path_text}\n{section.content}"
            score = 0.0
            for term in query_terms:
                if not term:
                    continue
                count = haystack.count(term)
                if count:
                    score += min(count, 5)
                    if term in section.path_text:
                        score += 3
            for keyword in section.keywords:
                if keyword in query_terms:
                    score += 1.5
            if score > 0:
                matches.append(
                    SourceMatch(
                        section_id=section.id,
                        title_path=section.title_path,
                        snippet=_snippet(section.content, query_terms),
                        score=round(score, 3),
                    )
                )
        matches.sort(key=lambda item: item.score, reverse=True)
        return matches[:limit]


def _query_terms(node: TemplateNode) -> list[str]:
    terms = [node.title]
    terms.extend(_extract_terms(node.title))
    for field in [node.source_rules, node.auto_fill, node.manual_fill, node.special_notes]:
        for item in field:
            terms.extend(_extract_terms(item))
    ordered: list[str] = []
    for term in terms:
        term = term.strip("“”‘’：:，,。；;（）() ")
        if len(term) >= 2 and term not in ordered:
            ordered.append(term)
    return ordered[:40]


def _extract_terms(text: str) -> list[str]:
    candidates = re.findall(r"[\u4e00-\u9fff]{2,12}", text)
    stop = {"主要来源", "自动补充", "人工补充", "用于本节模板编写", "可参考该来源中的"}
    return [item for item in candidates if item not in stop]


def _snippet(text: str, terms: list[str]) -> str:
    compact = re.sub(r"\s+", " ", text).strip()
    if not compact:
        return ""
    positions = [compact.find(term) for term in terms if term and compact.find(term) >= 0]
    start = max(0, min(positions) - 80) if positions else 0
    return compact[start:start + 360]
