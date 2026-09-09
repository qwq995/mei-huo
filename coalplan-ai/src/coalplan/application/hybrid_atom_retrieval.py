from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Protocol

from coalplan.domain.reference_library import AtomRetrievalQuery, ReferenceAtom, ReferenceReviewStatus


class AtomVectorIndex(Protocol):
    def search(self, query_text: str, *, limit: int, filters: dict[str, str | list[str]]) -> list[tuple[str, float]]: ...


@dataclass(frozen=True)
class HybridCandidate:
    atom: ReferenceAtom
    score: float
    lexical_rank: int | None
    vector_rank: int | None
    tag_score: float
    match_reasons: list[str]


def build_atom_search_text(atom: ReferenceAtom) -> str:
    return " ".join(
        value for value in [
            atom.project_type,
            *atom.title_path,
            atom.chapter_module,
            atom.engineering_system,
            atom.engineering_object,
            atom.specialty,
            atom.work_item,
            atom.process_family,
            atom.process_method,
            atom.process_stage,
            *atom.content_functions,
            *atom.applicability,
            atom.parameterized_template or atom.normalized_text or atom.content,
        ] if value
    )


def build_query_text(query: AtomRetrievalQuery) -> str:
    return " ".join(
        value for value in [
            query.project_type,
            *query.parent_titles,
            query.chapter_title,
            query.chapter_module,
            query.engineering_system,
            query.engineering_object,
            query.process_family,
            query.process_stage,
            *query.content_functions,
            *query.applicability,
            *query.writing_topics,
            query.evidence_summary,
        ] if value
    )


def hybrid_prefilter_atoms(
    atoms: list[ReferenceAtom],
    query: AtomRetrievalQuery,
    *,
    vector_index: AtomVectorIndex | None = None,
    vector_results: list[tuple[str, float]] | None = None,
    limit: int = 30,
    rrf_k: int = 60,
) -> list[HybridCandidate]:
    eligible = [
        atom for atom in atoms
        if atom.status == ReferenceReviewStatus.published
        and atom.schema_version == "v2"
        and not atom.publication_blockers
        and atom.project_name != query.project_name
        and atom.project_name not in query.excluded_project_names
        and _hard_compatible(atom, query)
    ]
    query_text = build_query_text(query)
    lexical = sorted(eligible, key=lambda atom: _lexical_score(query_text, build_atom_search_text(atom)), reverse=True)
    lexical = [atom for atom in lexical if _lexical_score(query_text, build_atom_search_text(atom)) > 0][:limit]
    lexical_rank = {atom.id: rank for rank, atom in enumerate(lexical, start=1)}

    if vector_results is None:
        vector_results = []
        if vector_index is not None:
            vector_results = vector_index.search(query_text, limit=limit, filters=query_filters(query))
    vector_rank = {atom_id: rank for rank, (atom_id, _) in enumerate(vector_results, start=1)}
    by_id = {atom.id: atom for atom in eligible}
    candidate_ids = set(lexical_rank) | set(vector_rank)
    results: list[HybridCandidate] = []
    for atom_id in candidate_ids:
        atom = by_id.get(atom_id)
        if atom is None:
            continue
        tag_score, reasons = _tag_score(atom, query)
        score = tag_score
        if atom_id in lexical_rank:
            score += 1.0 / (rrf_k + lexical_rank[atom_id])
            reasons.append("专业词与章节语义匹配")
        if atom_id in vector_rank:
            score += 1.0 / (rrf_k + vector_rank[atom_id])
            reasons.append("向量语义相近")
        score += atom.quality_score * 0.08
        results.append(HybridCandidate(atom, score, lexical_rank.get(atom_id), vector_rank.get(atom_id), tag_score, reasons))
    return sorted(results, key=lambda item: (item.score, item.atom.quality_score), reverse=True)[:limit]


def query_filters(query: AtomRetrievalQuery) -> dict[str, str | list[str]]:
    # Object/stage/function are intentionally soft signals. Exact payload filters
    # on those fields suppress useful neighbouring atoms such as drilling,
    # charging and perimeter-hole controls within the same blast chapter.
    return {
        key: value for key, value in {
            "chapter_module": query.chapter_module,
            "engineering_system": query.engineering_system,
            "process_family": query.process_family,
        }.items() if value
    }


def _hard_compatible(atom: ReferenceAtom, query: AtomRetrievalQuery) -> bool:
    for atom_value, query_value in (
        (atom.chapter_module, query.chapter_module),
        (atom.engineering_system, query.engineering_system),
        (atom.process_family, query.process_family),
    ):
        if query_value and atom_value != query_value:
            return False
    return True


def _tag_score(atom: ReferenceAtom, query: AtomRetrievalQuery) -> tuple[float, list[str]]:
    score = 0.0
    reasons: list[str] = []
    pairs = (
        (atom.chapter_module, query.chapter_module, 0.22, "文档模块一致"),
        (atom.engineering_system, query.engineering_system, 0.18, "工程系统一致"),
        (atom.engineering_object, query.engineering_object, 0.30, "工程对象一致"),
        (atom.process_family, query.process_family, 0.25, "工艺族一致"),
        (atom.process_stage, query.process_stage, 0.12, "工序阶段一致"),
    )
    for atom_value, query_value, weight, reason in pairs:
        if atom_value and query_value and atom_value == query_value:
            score += weight
            reasons.append(reason)
        elif reason == "工程对象一致" and atom_value and query_value:
            similarity = _lexical_score(atom_value, query_value)
            if similarity > 0:
                score += min(weight * 0.75, similarity * weight)
                reasons.append("工程对象语义相关")
    overlap = set(atom.content_functions) & set(query.content_functions)
    if overlap:
        score += min(0.15, 0.05 * len(overlap))
        reasons.append("内容功能覆盖：" + "、".join(sorted(overlap)))
    return score, reasons


def _lexical_score(left: str, right: str) -> float:
    left_terms = _terms(left)
    right_terms = _terms(right)
    if not left_terms or not right_terms:
        return 0.0
    overlap = left_terms & right_terms
    return len(overlap) / math.sqrt(len(left_terms) * len(right_terms))


def _terms(text: str) -> set[str]:
    compact = re.sub(r"\s+", "", text.lower())
    chinese = re.findall(r"[\u4e00-\u9fff]{2,}", compact)
    latin = re.findall(r"[a-z0-9][a-z0-9+./_-]*", compact)
    bigrams = {word[index:index + 2] for word in chinese for index in range(len(word) - 1)}
    return bigrams | set(latin)
