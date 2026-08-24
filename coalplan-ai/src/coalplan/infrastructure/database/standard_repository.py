from __future__ import annotations

import json
from datetime import datetime
from uuid import uuid4

from coalplan.application.serialization import dump_model
from coalplan.application.standard_retrieval import (
    constraint_retrieval_text,
    document_retrieval_text,
    fts_query,
)
from coalplan.domain.standard_constraints import (
    ComplianceFinding,
    ComplianceReviewRun,
    ConstraintAtom,
    ConstraintMatch,
    ConstraintReviewStatus,
    FindingStatus,
    StandardDocument,
    StandardMatch,
)

from .models import (
    ComplianceConstraintMatchRecord,
    ComplianceFindingRecord,
    ComplianceReviewRunRecord,
    ConstraintAtomRecord,
    ProjectStandardMatchRecord,
    StandardDocumentRecord,
)
from sqlalchemy import text


class StandardConstraintRepository:
    def __init__(self, session_factory) -> None:
        self.session_factory = session_factory

    def save_document(self, document: StandardDocument) -> StandardDocument:
        with self.session_factory() as session:
            row = session.get(StandardDocumentRecord, document.id)
            values = _document_values(document)
            if row is None:
                row = StandardDocumentRecord(**values)
                session.add(row)
            else:
                for key, value in values.items():
                    setattr(row, key, value)
            session.commit()
            self._refresh_document_search(document.id)
        return document

    def get_document(self, document_id: str) -> StandardDocument:
        with self.session_factory() as session:
            row = session.get(StandardDocumentRecord, document_id)
            if row is None:
                raise KeyError(f"Unknown standard document: {document_id}")
            return _document(row)

    def list_documents(self, *, category: str | None = None) -> list[StandardDocument]:
        with self.session_factory() as session:
            query = session.query(StandardDocumentRecord)
            if category:
                query = query.filter_by(category=category)
            return [_document(row) for row in query.order_by(StandardDocumentRecord.standard_code, StandardDocumentRecord.name).all()]

    def set_document_status(self, document_id: str, status: str) -> StandardDocument:
        with self.session_factory() as session:
            row = session.get(StandardDocumentRecord, document_id)
            if row is None:
                raise KeyError(f"Unknown standard document: {document_id}")
            row.status = status
            session.commit()
            return _document(row)

    def replace_atoms(self, document_id: str, atoms: list[ConstraintAtom]) -> None:
        with self.session_factory() as session:
            session.query(ConstraintAtomRecord).filter_by(document_id=document_id).delete()
            for atom in {item.id: item for item in atoms}.values():
                session.add(_atom_record(atom))
            document = session.get(StandardDocumentRecord, document_id)
            if document is not None:
                document.atom_count = len(atoms)
            session.commit()
            self._refresh_document_search(document_id)

    def search_document_candidates(
        self,
        query_text: str,
        *,
        limit: int = 48,
        include_document_ids: set[str] | None = None,
    ) -> list[StandardDocument] | None:
        """Return local FTS candidates, or None when the index cannot answer."""
        query = fts_query(query_text)
        if not query:
            return None
        try:
            if self._search_index_empty("standard_document_search"):
                self.rebuild_search_index()
            with self.session_factory() as session:
                rows = session.execute(text(
                    "SELECT document_id FROM standard_document_search "
                    "WHERE standard_document_search MATCH :query "
                    "ORDER BY bm25(standard_document_search) LIMIT :limit"
                ), {"query": query, "limit": max(1, limit)}).all()
                ids = [str(row[0]) for row in rows]
                ids.extend(sorted((include_document_ids or set()) - set(ids)))
                if not ids:
                    return None
                documents = {
                    row.id: _document(row)
                    for row in session.query(StandardDocumentRecord).filter(StandardDocumentRecord.id.in_(ids)).all()
                    if row.status not in {"failed", "excluded"}
                }
                return [documents[item_id] for item_id in ids if item_id in documents]
        except Exception:
            return None

    def search_constraint_candidates(
        self,
        query_text: str,
        document_ids: set[str],
        *,
        limit: int = 180,
    ) -> list[ConstraintAtom] | None:
        """Search only published atoms belonging to already selected documents."""
        query = fts_query(query_text)
        if not query or not document_ids:
            return None
        try:
            if self._search_index_empty("constraint_atom_search"):
                self.rebuild_search_index()
            with self.session_factory() as session:
                placeholders = ", ".join(f":doc_{index}" for index in range(len(document_ids)))
                params = {f"doc_{index}": value for index, value in enumerate(sorted(document_ids))}
                params.update({"query": query, "limit": max(1, limit)})
                rows = session.execute(text(
                    "SELECT atom_id, document_id FROM constraint_atom_search "
                    "WHERE constraint_atom_search MATCH :query "
                    f"AND document_id IN ({placeholders}) "
                    "ORDER BY bm25(constraint_atom_search) LIMIT :limit"
                ), params).all()
                atom_ids = [str(row[0]) for row in rows]
                if not atom_ids:
                    return None
                atoms = {
                    row.id: _atom(row)
                    for row in session.query(ConstraintAtomRecord).filter(
                        ConstraintAtomRecord.id.in_(atom_ids),
                        ConstraintAtomRecord.status == ConstraintReviewStatus.published.value,
                    ).all()
                }
                return [atoms[item_id] for item_id in atom_ids if item_id in atoms]
        except Exception:
            return None

    def rebuild_search_index(self) -> None:
        """Backfill FTS rows for databases created before the search index."""
        try:
            documents = self.list_documents()
            for document in documents:
                self._refresh_document_search(document.id)
        except Exception:
            return

    def _search_index_empty(self, table_name: str) -> bool:
        if table_name not in {"standard_document_search", "constraint_atom_search"}:
            return True
        try:
            with self.session_factory() as session:
                return session.execute(text(f"SELECT 1 FROM {table_name} LIMIT 1")).first() is None
        except Exception:
            return False

    def _refresh_document_search(self, document_id: str) -> None:
        try:
            with self.session_factory() as session:
                document = session.get(StandardDocumentRecord, document_id)
                if document is None:
                    return
                atoms = session.query(ConstraintAtomRecord).filter_by(document_id=document_id).all()
                document_model = _document(document)
                atom_models = [_atom(item) for item in atoms]
                session.execute(text("DELETE FROM standard_document_search WHERE document_id = :document_id"), {"document_id": document_id})
                session.execute(text(
                    "INSERT INTO standard_document_search(document_id, search_text) VALUES (:document_id, :search_text)"
                ), {"document_id": document_id, "search_text": document_retrieval_text(document_model, atom_models)})
                session.execute(text("DELETE FROM constraint_atom_search WHERE document_id = :document_id"), {"document_id": document_id})
                for atom in atom_models:
                    session.execute(text(
                        "INSERT INTO constraint_atom_search(atom_id, document_id, search_text) "
                        "VALUES (:atom_id, :document_id, :search_text)"
                    ), {
                        "atom_id": atom.id,
                        "document_id": document_id,
                        "search_text": constraint_retrieval_text(atom),
                    })
                session.commit()
        except Exception:
            # Search is an optimization; persistence must remain usable without FTS5.
            return

    def list_atoms(
        self,
        *,
        document_id: str | None = None,
        status: ConstraintReviewStatus | None = None,
    ) -> list[ConstraintAtom]:
        with self.session_factory() as session:
            query = session.query(ConstraintAtomRecord)
            if document_id:
                query = query.filter_by(document_id=document_id)
            if status:
                query = query.filter_by(status=status.value)
            return [_atom(row) for row in query.order_by(ConstraintAtomRecord.document_id, ConstraintAtomRecord.start_line).all()]

    def get_atom(self, atom_id: str) -> ConstraintAtom:
        with self.session_factory() as session:
            row = session.get(ConstraintAtomRecord, atom_id)
            if row is None:
                raise KeyError(f"Unknown constraint atom: {atom_id}")
            return _atom(row)

    def set_atom_status(self, atom_id: str, status: ConstraintReviewStatus) -> ConstraintAtom:
        with self.session_factory() as session:
            row = session.get(ConstraintAtomRecord, atom_id)
            if row is None:
                raise KeyError(f"Unknown constraint atom: {atom_id}")
            row.status = status.value
            session.commit()
            return _atom(row)

    def replace_project_matches(self, project_id: str, matches: list[StandardMatch]) -> None:
        with self.session_factory() as session:
            session.query(ProjectStandardMatchRecord).filter_by(project_id=project_id).delete()
            for match in matches:
                session.add(
                    ProjectStandardMatchRecord(
                        id=f"stdmatch_{uuid4().hex[:12]}",
                        project_id=project_id,
                        **dump_model(match),
                    )
                )
            session.commit()

    def list_project_matches(self, project_id: str) -> list[StandardMatch]:
        with self.session_factory() as session:
            rows = session.query(ProjectStandardMatchRecord).filter_by(project_id=project_id).order_by(ProjectStandardMatchRecord.score.desc()).all()
            return [StandardMatch(document_id=row.document_id, score=row.score, match_reason=row.match_reason, decision=row.decision) for row in rows]

    def set_project_match_decision(self, project_id: str, document_id: str, decision: str) -> StandardMatch:
        with self.session_factory() as session:
            row = session.query(ProjectStandardMatchRecord).filter_by(project_id=project_id, document_id=document_id).one_or_none()
            if row is None:
                row = ProjectStandardMatchRecord(
                    id=f"stdmatch_{uuid4().hex[:12]}", project_id=project_id, document_id=document_id,
                    score=1.0, match_reason="用户手动选择", decision=decision,
                )
                session.add(row)
            else:
                row.decision = decision
            session.commit()
            return StandardMatch(document_id=row.document_id, score=row.score, match_reason=row.match_reason, decision=row.decision)

    def create_review_run(self, run: ComplianceReviewRun) -> ComplianceReviewRun:
        with self.session_factory() as session:
            session.add(ComplianceReviewRunRecord(
                id=run.id,
                project_id=run.project_id,
                status=run.status,
                chapter_count=run.chapter_count,
                matched_document_count=run.matched_document_count,
                candidate_constraint_count=run.candidate_constraint_count,
                finding_count=run.finding_count,
                warnings_json=_json(run.warnings),
                summary_json=_json(run.summary),
            ))
            session.commit()
        return run

    def complete_review_run(self, run_id: str, *, status: str, chapter_count: int, matched_document_count: int,
                            candidate_constraint_count: int, findings: list[ComplianceFinding], warnings: list[str], summary: dict) -> ComplianceReviewRun:
        with self.session_factory() as session:
            row = session.get(ComplianceReviewRunRecord, run_id)
            if row is None:
                raise KeyError(f"Unknown compliance review run: {run_id}")
            row.status = status
            row.chapter_count = chapter_count
            row.matched_document_count = matched_document_count
            row.candidate_constraint_count = candidate_constraint_count
            row.finding_count = len(findings)
            row.warnings_json = _json(warnings)
            row.summary_json = _json(summary)
            row.completed_at = datetime.now()
            for finding in findings:
                session.merge(ComplianceFindingRecord(**dump_model(finding)))
            session.commit()
            return _review_run(row)

    def list_review_runs(self, project_id: str, *, limit: int = 20) -> list[ComplianceReviewRun]:
        with self.session_factory() as session:
            rows = session.query(ComplianceReviewRunRecord).filter_by(project_id=project_id).order_by(
                ComplianceReviewRunRecord.created_at.desc()
            ).limit(limit).all()
            return [_review_run(row) for row in rows]

    def get_review_run(self, project_id: str, run_id: str) -> ComplianceReviewRun:
        with self.session_factory() as session:
            row = session.get(ComplianceReviewRunRecord, run_id)
            if row is None or row.project_id != project_id:
                raise KeyError(f"Unknown compliance review run: {run_id}")
            return _review_run(row)

    def save_constraint_matches(self, matches: list[ConstraintMatch], *, project_id: str, chapter_version_id: str) -> None:
        if not matches:
            return
        with self.session_factory() as session:
            for match in matches:
                session.merge(ComplianceConstraintMatchRecord(
                    id=f"constraintmatch_{match.run_id}_{chapter_version_id}_{match.atom_id}",
                    run_id=match.run_id,
                    project_id=project_id,
                    node_id=match.node_id,
                    chapter_version_id=chapter_version_id,
                    atom_id=match.atom_id,
                    document_id=match.document_id,
                    score=match.score,
                    match_reason=match.match_reason,
                ))
            session.commit()

    def list_constraint_matches(self, project_id: str, run_id: str, *, node_id: str | None = None) -> list[ConstraintMatch]:
        with self.session_factory() as session:
            query = session.query(ComplianceConstraintMatchRecord).filter_by(project_id=project_id, run_id=run_id)
            if node_id:
                query = query.filter_by(node_id=node_id)
            return [ConstraintMatch(
                run_id=row.run_id, atom_id=row.atom_id, document_id=row.document_id,
                node_id=row.node_id, score=row.score, match_reason=row.match_reason,
            ) for row in query.order_by(ComplianceConstraintMatchRecord.score.desc()).all()]

    def save_findings(self, findings: list[ComplianceFinding]) -> None:
        with self.session_factory() as session:
            for finding in findings:
                session.merge(ComplianceFindingRecord(**dump_model(finding)))
            session.commit()

    def replace_findings(self, project_id: str, findings: list[ComplianceFinding]) -> None:
        """Legacy helper retained for existing callers; review runs use save_findings instead."""
        with self.session_factory() as session:
            session.query(ComplianceFindingRecord).filter_by(project_id=project_id).delete()
            for finding in findings:
                session.add(ComplianceFindingRecord(**dump_model(finding)))
            session.commit()

    def list_findings(self, project_id: str, *, status: FindingStatus | None = None, run_id: str | None = None) -> list[ComplianceFinding]:
        with self.session_factory() as session:
            query = session.query(ComplianceFindingRecord).filter_by(project_id=project_id)
            if status:
                query = query.filter_by(status=status.value)
            if run_id:
                query = query.filter_by(run_id=run_id)
            return [_finding(row) for row in query.order_by(ComplianceFindingRecord.created_at.desc()).all()]

    def get_finding(self, project_id: str, finding_id: str) -> ComplianceFinding:
        with self.session_factory() as session:
            row = session.get(ComplianceFindingRecord, finding_id)
            if row is None or row.project_id != project_id:
                raise KeyError(f"Unknown compliance finding: {finding_id}")
            return _finding(row)

    def resolve_finding(
        self,
        project_id: str,
        finding_id: str,
        *,
        status: FindingStatus,
        note: str = "",
        resolved_version_id: str | None = None,
    ) -> ComplianceFinding:
        with self.session_factory() as session:
            row = session.get(ComplianceFindingRecord, finding_id)
            if row is None or row.project_id != project_id:
                raise KeyError(f"Unknown compliance finding: {finding_id}")
            row.status = status.value
            row.resolution_note = note
            row.resolved_version_id = resolved_version_id
            session.commit()
            return _finding(row)


def _document_values(document: StandardDocument) -> dict:
    values = dump_model(document)
    values["disciplines_json"] = _json(values.pop("disciplines"))
    values["project_types_json"] = _json(values.pop("project_types"))
    return values


def _document(row: StandardDocumentRecord) -> StandardDocument:
    return StandardDocument(
        id=row.id, standard_code=row.standard_code, name=row.name, category=row.category,
        disciplines=json.loads(row.disciplines_json), project_types=json.loads(row.project_types_json),
        source_path=row.source_path, file_name=row.file_name, content_hash=row.content_hash,
        status=row.status, version=row.version, atom_count=row.atom_count, warning_count=row.warning_count,
    )


_ATOM_JSON_FIELDS = (
    "title_path", "disciplines", "project_types", "chapter_scopes", "keywords",
    "applicability", "exceptions", "evidence_required",
)


def _atom_record(atom: ConstraintAtom) -> ConstraintAtomRecord:
    values = dump_model(atom)
    for field in _ATOM_JSON_FIELDS:
        values[f"{field}_json"] = _json(values.pop(field))
    return ConstraintAtomRecord(**values)


def _atom(row: ConstraintAtomRecord) -> ConstraintAtom:
    values = {
        key: getattr(row, key)
        for key in (
            "id", "document_id", "standard_code", "standard_name", "clause_no", "source_text",
            "normalized_requirement", "constraint_type", "review_method", "severity",
            "ai_fixable", "repair_instruction", "start_line", "end_line", "confidence", "status",
        )
    }
    for field in _ATOM_JSON_FIELDS:
        values[field] = json.loads(getattr(row, f"{field}_json"))
    return ConstraintAtom(**values)


def _finding(row: ComplianceFindingRecord) -> ComplianceFinding:
    return ComplianceFinding(**{
        key: getattr(row, key)
        for key in ComplianceFinding.model_fields
    })


def _review_run(row: ComplianceReviewRunRecord) -> ComplianceReviewRun:
    return ComplianceReviewRun(
        id=row.id,
        project_id=row.project_id,
        status=row.status,
        chapter_count=row.chapter_count,
        matched_document_count=row.matched_document_count,
        candidate_constraint_count=row.candidate_constraint_count,
        finding_count=row.finding_count,
        warnings=json.loads(row.warnings_json),
        summary=json.loads(row.summary_json),
    )


def _json(value) -> str:
    return json.dumps(value, ensure_ascii=False)
