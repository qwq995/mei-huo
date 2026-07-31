from __future__ import annotations

import json

from coalplan.application.serialization import dump_model
from coalplan.domain.reference_library import (
    ChapterAtomUsage,
    ReferenceAtom,
    ReferenceChapter,
    ReferenceDocument,
    ReferenceFactVariable,
    ReferenceReviewStatus,
)

from .models import (
    ChapterAtomUsageRecord,
    ReferenceAtomRecord,
    ReferenceChapterRecord,
    ReferenceDocumentRecord,
)


class ReferenceLibraryRepository:
    def __init__(self, session_factory) -> None:
        self.session_factory = session_factory

    def save_document(self, document: ReferenceDocument) -> ReferenceDocument:
        with self.session_factory() as session:
            record = session.get(ReferenceDocumentRecord, document.id)
            values = dump_model(document)
            if record is None:
                record = ReferenceDocumentRecord(**values)
                session.add(record)
            else:
                for key, value in values.items():
                    setattr(record, key, value)
            session.commit()
        return document

    def get_document(self, document_id: str) -> ReferenceDocument:
        with self.session_factory() as session:
            record = session.get(ReferenceDocumentRecord, document_id)
            if record is None:
                raise KeyError(f"Unknown reference document: {document_id}")
            return _document(record)

    def list_documents(self) -> list[ReferenceDocument]:
        with self.session_factory() as session:
            records = session.query(ReferenceDocumentRecord).order_by(ReferenceDocumentRecord.file_name).all()
            return [_document(record) for record in records]

    def replace_document_content(
        self,
        document_id: str,
        *,
        chapters: list[ReferenceChapter],
        atoms: list[ReferenceAtom],
    ) -> None:
        with self.session_factory() as session:
            session.query(ReferenceChapterRecord).filter_by(document_id=document_id).delete()
            session.query(ReferenceAtomRecord).filter_by(document_id=document_id).delete()
            for chapter in chapters:
                session.add(
                    ReferenceChapterRecord(
                        id=chapter.id,
                        document_id=chapter.document_id,
                        title_path_json=_json(chapter.title_path),
                        start_line=chapter.start_line,
                        end_line=chapter.end_line,
                        sort_order=chapter.sort_order,
                    )
                )
            unique_atoms = {atom.id: atom for atom in atoms}
            for atom in unique_atoms.values():
                session.add(_atom_record(atom))
            session.commit()

    def list_atoms(
        self,
        *,
        status: ReferenceReviewStatus | None = None,
        excluded_projects: list[str] | None = None,
    ) -> list[ReferenceAtom]:
        with self.session_factory() as session:
            query = session.query(ReferenceAtomRecord)
            if status is not None:
                query = query.filter(ReferenceAtomRecord.status == status.value)
            if excluded_projects:
                query = query.filter(~ReferenceAtomRecord.project_name.in_(excluded_projects))
            return [_atom(record) for record in query.order_by(ReferenceAtomRecord.id).all()]

    def set_atom_status(self, atom_id: str, status: ReferenceReviewStatus) -> ReferenceAtom:
        with self.session_factory() as session:
            record = session.get(ReferenceAtomRecord, atom_id)
            if record is None:
                raise KeyError(f"Unknown reference atom: {atom_id}")
            record.status = status.value
            session.commit()
            return _atom(record)

    def save_usage(self, usage: ChapterAtomUsage, *, prompt_snapshot_path: str | None = None) -> None:
        with self.session_factory() as session:
            values = dump_model(usage)
            session.merge(ChapterAtomUsageRecord(**values, prompt_snapshot_path=prompt_snapshot_path))
            session.commit()

    def list_usage(self, project_id: str, node_id: str | None = None) -> list[dict]:
        with self.session_factory() as session:
            query = session.query(ChapterAtomUsageRecord).filter_by(project_id=project_id)
            if node_id:
                query = query.filter_by(node_id=node_id)
            return [
                {
                    "id": row.id,
                    "project_id": row.project_id,
                    "node_id": row.node_id,
                    "chapter_version_id": row.chapter_version_id,
                    "atom_id": row.atom_id,
                    "retrieval_score": row.retrieval_score,
                    "match_reason": row.match_reason,
                    "prompt_use": row.prompt_use,
                    "decision": row.decision,
                    "prompt_snapshot_path": row.prompt_snapshot_path,
                    "created_at": row.created_at.isoformat(),
                }
                for row in query.order_by(ChapterAtomUsageRecord.created_at).all()
            ]


def _document(record: ReferenceDocumentRecord) -> ReferenceDocument:
    return ReferenceDocument(
        id=record.id,
        content_hash=record.content_hash,
        source_path=record.source_path,
        file_name=record.file_name,
        project_name=record.project_name,
        project_type=record.project_type,
        document_kind=record.document_kind,
        status=record.status,
        version=record.version,
    )


def _atom_record(atom: ReferenceAtom) -> ReferenceAtomRecord:
    tags = {
        "engineering_object": atom.engineering_object,
        "specialty": atom.specialty,
        "work_item": atom.work_item,
        "process": atom.process,
        "process_stage": atom.process_stage,
        "chapter_type": atom.chapter_type,
        "content_functions": atom.content_functions,
    }
    return ReferenceAtomRecord(
        id=atom.id,
        document_id=atom.document_id,
        project_name=atom.project_name,
        project_type=atom.project_type,
        title_path_json=_json(atom.title_path),
        content=atom.content,
        source_block_ids_json=_json(atom.source_block_ids),
        start_line=atom.start_line,
        end_line=atom.end_line,
        tags_json=_json(tags),
        applicability_json=_json(atom.applicability),
        prohibited_scenarios_json=_json(atom.prohibited_scenarios),
        fact_variables_json=_json([dump_model(item) for item in atom.fact_variables]),
        quality_score=atom.quality_score,
        confidence=atom.confidence,
        status=atom.status.value,
        version=atom.version,
    )


def _atom(record: ReferenceAtomRecord) -> ReferenceAtom:
    tags = json.loads(record.tags_json)
    return ReferenceAtom(
        id=record.id,
        document_id=record.document_id,
        project_name=record.project_name,
        project_type=record.project_type,
        title_path=json.loads(record.title_path_json),
        content=record.content,
        source_block_ids=json.loads(record.source_block_ids_json),
        start_line=record.start_line,
        end_line=record.end_line,
        engineering_object=tags.get("engineering_object", ""),
        specialty=tags.get("specialty", ""),
        work_item=tags.get("work_item", ""),
        process=tags.get("process", ""),
        process_stage=tags.get("process_stage", ""),
        chapter_type=tags.get("chapter_type", ""),
        content_functions=tags.get("content_functions", []),
        applicability=json.loads(record.applicability_json),
        prohibited_scenarios=json.loads(record.prohibited_scenarios_json),
        fact_variables=[ReferenceFactVariable(**item) for item in json.loads(record.fact_variables_json)],
        quality_score=record.quality_score,
        confidence=record.confidence,
        status=record.status,
        version=record.version,
    )


def _json(value) -> str:
    return json.dumps(value, ensure_ascii=False)
