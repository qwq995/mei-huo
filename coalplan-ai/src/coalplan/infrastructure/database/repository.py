from __future__ import annotations

import json
import re
from datetime import datetime

from coalplan.application.serialization import dump_model
from coalplan.domain.documents import MarkdownSection
from coalplan.domain.generation import Project
from coalplan.domain.templates import TemplateNode

from .models import (
    AIChangeProposalRecord,
    ChapterAttachmentRecord,
    ChapterSupplementRecord,
    ChapterTaskRecord,
    ChapterVersionRecord,
    GenerationRunRecord,
    LLMTraceRecord,
    ProjectOutlineNodeRecord,
    ProjectRecord,
    SourceDocumentRecord,
    SourceSectionRecord,
)


class DatabaseProjectRepository:
    def __init__(self, session_factory) -> None:
        self.session_factory = session_factory

    def save(self, project: Project) -> Project:
        with self.session_factory() as session:
            record = session.get(ProjectRecord, project.id)
            state_json = json.dumps(dump_model(project), ensure_ascii=False, indent=2)
            if record is None:
                record = ProjectRecord(id=project.id, name=project.name, template_id=project.template_id, state_json=state_json)
                session.add(record)
            else:
                record.name = project.name
                record.template_id = project.template_id
                record.state_json = state_json
                record.updated_at = datetime.now()
                record.deleted_at = None
            _sync_source_documents(session, project)
            _sync_source_sections(session, project)
            _sync_outline_nodes(session, project)
            _sync_generation_runs(session, project)
            _sync_chapter_tasks(session, project)
            session.commit()
        return project

    def get(self, project_id: str) -> Project:
        with self.session_factory() as session:
            record = session.get(ProjectRecord, project_id)
            if record is None or record.deleted_at is not None:
                raise KeyError(f"Unknown project_id: {project_id}")
            return _load_project(json.loads(record.state_json))

    def list(self) -> list[Project]:
        with self.session_factory() as session:
            records = (
                session.query(ProjectRecord)
                .filter(ProjectRecord.deleted_at.is_(None))
                .order_by(ProjectRecord.updated_at.desc())
                .all()
            )
            return [_load_project(json.loads(record.state_json)) for record in records]

    def delete(self, project_id: str) -> None:
        with self.session_factory() as session:
            record = session.get(ProjectRecord, project_id)
            if record is None:
                raise KeyError(f"Unknown project_id: {project_id}")
            for model in (
                AIChangeProposalRecord,
                ChapterAttachmentRecord,
                ChapterSupplementRecord,
                ChapterVersionRecord,
                ChapterTaskRecord,
                GenerationRunRecord,
                LLMTraceRecord,
                ProjectOutlineNodeRecord,
                SourceDocumentRecord,
                SourceSectionRecord,
            ):
                session.query(model).filter_by(project_id=project_id).delete()
            session.delete(record)
            session.commit()


def _sync_source_documents(session, project: Project) -> None:
    session.query(SourceDocumentRecord).filter_by(project_id=project.id).delete()
    for document in project.source_documents:
        session.add(
            SourceDocumentRecord(
                id=document.id,
                project_id=project.id,
                file_name=document.file_name,
                role=document.role.value,
                status=document.status.value,
                raw_artifact_path=document.raw_artifact_path,
                normalized_artifact_path=document.normalized_artifact_path,
            )
        )


def _sync_source_sections(session, project: Project) -> None:
    if not project.sections:
        return
    session.query(SourceSectionRecord).filter_by(project_id=project.id).delete()
    for section in project.sections:
        session.add(
            SourceSectionRecord(
                id=f"{project.id}:{section.id}",
                project_id=project.id,
                section_id=section.id,
                title_path_json=_json(section.title_path),
                level=section.level,
                content=section.content,
                keywords_json=_json(section.keywords),
                source_file=section.source_file,
                start_line=section.start_line,
                end_line=section.end_line,
                char_count=len(section.content),
                snippet=_snippet(section.content),
            )
        )


def _sync_outline_nodes(session, project: Project) -> None:
    if project.template_tree is None:
        return
    existing = {row.node_id: row for row in session.query(ProjectOutlineNodeRecord).filter_by(project_id=project.id).all()}
    if existing:
        return
    order = 0
    for node, parent_id in _walk_nodes(project.template_tree.nodes):
        order += 1
        session.add(
            ProjectOutlineNodeRecord(
                id=f"{project.id}:{node.id}",
                project_id=project.id,
                node_id=node.id,
                parent_id=parent_id,
                title=node.title,
                level=node.level,
                sort_order=order,
                enabled=True,
                source_rules_json=_json(node.source_rules),
                auto_fill_json=_json(node.auto_fill),
                manual_fill_json=_json(node.manual_fill),
                special_notes_json=_json(node.special_notes),
            )
        )


def _sync_generation_runs(session, project: Project) -> None:
    session.query(GenerationRunRecord).filter_by(project_id=project.id).delete()
    for run in project.runs:
        session.add(
            GenerationRunRecord(
                id=run.id,
                project_id=project.id,
                project_name=run.project_name,
                template_id=run.template_id,
                status=run.status.value,
                final_artifact_path=run.final_artifact_path,
                logs_json=_json(run.logs),
                created_at=datetime.fromisoformat(run.created_at) if isinstance(run.created_at, str) else datetime.now(),
            )
        )


def _sync_chapter_tasks(session, project: Project) -> None:
    session.query(ChapterTaskRecord).filter_by(project_id=project.id).delete()
    for run in project.runs:
        for task in run.chapter_tasks:
            session.add(
                ChapterTaskRecord(
                    id=f"{project.id}:{run.id}:{task.node_id}",
                    project_id=project.id,
                    run_id=run.id,
                    node_id=task.node_id,
                    title=task.title,
                    status=task.status.value,
                    source_matches_json=_json([dump_model(match) for match in task.source_matches]),
                    draft_id=task.draft_id,
                    error_message=task.error_message,
                )
            )


def _walk_nodes(nodes: list[TemplateNode], parent_id: str | None = None):
    for node in nodes:
        yield node, parent_id
        yield from _walk_nodes(node.children, node.id)


def _json(value) -> str:
    return json.dumps(value, ensure_ascii=False)


def _snippet(text: str, limit: int = 220) -> str:
    compact = re.sub(r"\s+", " ", text).strip()
    return compact if len(compact) <= limit else compact[:limit].rstrip() + "..."


def _load_project(data: dict) -> Project:
    if hasattr(Project, "model_validate"):
        return Project.model_validate(data)
    return Project.parse_obj(data)
