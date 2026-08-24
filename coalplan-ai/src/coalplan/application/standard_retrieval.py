from __future__ import annotations

import re

from coalplan.domain.standard_constraints import ConstraintAtom, StandardDocument


TOKEN_RE = re.compile(r"[\u4e00-\u9fff]{2,8}|[A-Za-z][A-Za-z0-9./_-]{1,}|\d+(?:\.\d+)?")


def retrieval_terms(text: str, *, limit: int = 96) -> list[str]:
    """Create stable lexical terms without assigning domain categories.

    AI-produced tags remain the source of domain meaning. This tokenizer only
    makes those tags and identifiers searchable in SQLite FTS5.
    """
    output: list[str] = []
    seen: set[str] = set()
    for value in TOKEN_RE.findall(text or ""):
        term = value.strip().lower()
        if len(term) < 2:
            continue
        candidates = [term]
        if re.fullmatch(r"[\u4e00-\u9fff]+", term):
            candidates.extend(term[index:index + 2] for index in range(len(term) - 1))
            candidates.extend(term[index:index + 3] for index in range(len(term) - 2))
        for candidate in candidates:
            if candidate in seen:
                continue
            seen.add(candidate)
            output.append(candidate)
            if len(output) >= limit:
                return output
    return output


def fts_query(text: str, *, limit: int = 64) -> str:
    terms = retrieval_terms(text, limit=limit)
    # Quoting keeps standard identifiers such as DL/T 5186 from becoming
    # FTS operators. Terms are generated locally, never accepted as raw SQL.
    return " OR ".join(f'"{term.replace(chr(34), "")}"' for term in terms)


def document_retrieval_text(document: StandardDocument, atoms: list[ConstraintAtom] = ()) -> str:
    parts = [
        document.standard_code,
        document.name,
        document.category,
        " ".join(document.disciplines),
        " ".join(document.project_types),
    ]
    for atom in atoms:
        parts.extend([
            " ".join(atom.title_path),
            atom.standard_name,
            atom.constraint_type,
            " ".join(atom.disciplines),
            " ".join(atom.project_types),
            " ".join(atom.chapter_scopes),
            " ".join(atom.keywords),
            " ".join(atom.applicability),
            atom.normalized_requirement,
        ])
    return " ".join(part for part in parts if part)


def constraint_retrieval_text(atom: ConstraintAtom) -> str:
    return " ".join(
        part for part in (
            atom.standard_code,
            atom.standard_name,
            atom.clause_no,
            " ".join(atom.title_path),
            atom.constraint_type,
            " ".join(atom.disciplines),
            " ".join(atom.project_types),
            " ".join(atom.chapter_scopes),
            " ".join(atom.keywords),
            " ".join(atom.applicability),
            " ".join(atom.exceptions),
            atom.normalized_requirement,
        )
        if part
    )
