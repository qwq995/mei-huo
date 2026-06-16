from __future__ import annotations

import json
from datetime import datetime
from uuid import uuid4

from sqlalchemy import func

from coalplan.domain.templates import TemplateNode

from coalplan.infrastructure.database.models import (
    AIChangeProposalRecord,
    ChapterAttachmentRecord,
    ChapterSupplementRecord,
    ChapterVersionRecord,
    ProjectOutlineNodeRecord,
)


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex[:12]}"


class WorkspaceStore:
    def __init__(self, session_factory, artifacts) -> None:
        self.session_factory = session_factory
        self.artifacts = artifacts

    def list_outline_nodes(self, project_id: str) -> list[dict]:
        with self.session_factory() as session:
            rows = (
                session.query(ProjectOutlineNodeRecord)
                .filter_by(project_id=project_id)
                .order_by(ProjectOutlineNodeRecord.sort_order.asc())
                .all()
            )
            return [_outline_dict(row) for row in rows]

    def create_outline_node(self, project_id: str, payload: dict) -> dict:
        with self.session_factory() as session:
            sort_order = payload.get("sort_order")
            if sort_order is None:
                sort_order = (session.query(func.max(ProjectOutlineNodeRecord.sort_order)).filter_by(project_id=project_id).scalar() or 0) + 1
            node_id = payload.get("node_id") or new_id("usernode")
            row = ProjectOutlineNodeRecord(
                id=f"{project_id}:{node_id}",
                project_id=project_id,
                node_id=node_id,
                parent_id=payload.get("parent_id"),
                title=payload["title"],
                level=int(payload.get("level", 3)),
                sort_order=int(sort_order),
                enabled=bool(payload.get("enabled", True)),
                source_rules_json=_json(payload.get("source_rules", [])),
                auto_fill_json=_json(payload.get("auto_fill", [])),
                manual_fill_json=_json(payload.get("manual_fill", [])),
                special_notes_json=_json(payload.get("special_notes", [])),
            )
            session.add(row)
            session.commit()
            return _outline_dict(row)

    def update_outline_node(self, project_id: str, node_id: str, payload: dict) -> dict:
        with self.session_factory() as session:
            row = _get_outline(session, project_id, node_id)
            for key in ["title", "parent_id", "level", "sort_order", "enabled"]:
                if key in payload:
                    setattr(row, key, payload[key])
            mapping = {
                "source_rules": "source_rules_json",
                "auto_fill": "auto_fill_json",
                "manual_fill": "manual_fill_json",
                "special_notes": "special_notes_json",
            }
            for key, column in mapping.items():
                if key in payload:
                    setattr(row, column, _json(payload[key]))
            row.updated_at = datetime.now()
            session.commit()
            return _outline_dict(row)

    def delete_outline_node(self, project_id: str, node_id: str) -> None:
        with self.session_factory() as session:
            row = _get_outline(session, project_id, node_id)
            session.delete(row)
            session.commit()

    def outline_tree(self, project_id: str) -> list[TemplateNode]:
        rows = self.list_outline_nodes(project_id)
        by_parent: dict[str | None, list[dict]] = {}
        for row in rows:
            if not row["enabled"]:
                continue
            by_parent.setdefault(row["parent_id"], []).append(row)

        def build(parent_id: str | None) -> list[TemplateNode]:
            nodes = []
            for row in by_parent.get(parent_id, []):
                nodes.append(
                    TemplateNode(
                        id=row["node_id"],
                        title=row["title"],
                        level=row["level"],
                        source_rules=row["source_rules"],
                        auto_fill=row["auto_fill"],
                        manual_fill=row["manual_fill"],
                        special_notes=row["special_notes"],
                        children=build(row["node_id"]),
                    )
                )
            return nodes

        return build(None)

    def get_workspace(self, project_id: str, node_id: str) -> dict:
        with self.session_factory() as session:
            outline = _get_outline(session, project_id, node_id)
            supplements = (
                session.query(ChapterSupplementRecord)
                .filter_by(project_id=project_id, node_id=node_id)
                .order_by(ChapterSupplementRecord.sort_order.asc(), ChapterSupplementRecord.created_at.asc())
                .all()
            )
            attachments = session.query(ChapterAttachmentRecord).filter_by(project_id=project_id, node_id=node_id).order_by(ChapterAttachmentRecord.created_at.asc()).all()
            versions = session.query(ChapterVersionRecord).filter_by(project_id=project_id, node_id=node_id).order_by(ChapterVersionRecord.version_no.desc()).all()
            proposals = (
                session.query(AIChangeProposalRecord)
                .filter_by(project_id=project_id, target_id=node_id)
                .order_by(AIChangeProposalRecord.created_at.desc())
                .all()
            )
            return {
                "outline_node": _outline_dict(outline),
                "supplements": [_supplement_dict(row) for row in supplements],
                "attachments": [_attachment_dict(row) for row in attachments],
                "versions": [_version_dict(row) for row in versions],
                "selected_version_id": outline.selected_version_id,
                "proposals": [_proposal_dict(row) for row in proposals],
            }

    def render_chapter_context(self, project_id: str, node_id: str) -> str:
        workspace = self.get_workspace(project_id, node_id)
        lines = ["## 用户补充材料"]
        for item in workspace["supplements"]:
            must = "必须写入正文" if item["must_include"] else "参考材料"
            lines.extend([f"### {item['title'] or item['kind']}（{must}）", item["content"], ""])
        for item in workspace["attachments"]:
            lines.extend([f"### 附件：{item['file_name']}", f"路径：{item['artifact_path']}", f"说明：{item['description'] or '【无】'}", ""])
        selected = next((item for item in workspace["versions"] if item["id"] == workspace["selected_version_id"]), None)
        if selected:
            lines.extend(["## 当前选中历史版本", selected["markdown"][:4000]])
        return "\n".join(lines).strip()

    def add_supplement(self, project_id: str, node_id: str, payload: dict) -> dict:
        with self.session_factory() as session:
            sort_order = payload.get("sort_order")
            if sort_order is None:
                sort_order = (session.query(func.max(ChapterSupplementRecord.sort_order)).filter_by(project_id=project_id, node_id=node_id).scalar() or 0) + 1
            row = ChapterSupplementRecord(
                id=new_id("supp"),
                project_id=project_id,
                node_id=node_id,
                kind=payload.get("kind", "text"),
                title=payload.get("title", ""),
                content=payload.get("content", ""),
                must_include=bool(payload.get("must_include", False)),
                sort_order=int(sort_order),
            )
            session.add(row)
            session.commit()
            return _supplement_dict(row)

    def update_supplement(self, project_id: str, node_id: str, supplement_id: str, payload: dict) -> dict:
        with self.session_factory() as session:
            row = _get_supplement(session, project_id, node_id, supplement_id)
            for key in ["kind", "title", "content", "must_include", "sort_order"]:
                if key in payload:
                    setattr(row, key, payload[key])
            row.updated_at = datetime.now()
            session.commit()
            return _supplement_dict(row)

    def delete_supplement(self, project_id: str, node_id: str, supplement_id: str) -> None:
        with self.session_factory() as session:
            row = _get_supplement(session, project_id, node_id, supplement_id)
            session.delete(row)
            session.commit()

    def add_attachment(self, project_id: str, node_id: str, *, file_name: str, content_type: str, content: bytes, description: str) -> dict:
        relative_path = self.artifacts.unique_attachment_path(node_id, file_name)
        artifact_path = self.artifacts.write_bytes(project_id, relative_path, content)
        with self.session_factory() as session:
            row = ChapterAttachmentRecord(
                id=new_id("att"),
                project_id=project_id,
                node_id=node_id,
                file_name=file_name,
                content_type=content_type,
                artifact_path=artifact_path,
                description=description,
            )
            session.add(row)
            session.commit()
            return _attachment_dict(row)

    def delete_attachment(self, project_id: str, node_id: str, attachment_id: str) -> None:
        with self.session_factory() as session:
            row = session.get(ChapterAttachmentRecord, attachment_id)
            if row is None or row.project_id != project_id or row.node_id != node_id:
                raise KeyError(f"Unknown attachment_id: {attachment_id}")
            session.delete(row)
            session.commit()

    def create_chapter_version(
        self,
        project_id: str,
        node_id: str,
        *,
        title: str,
        markdown: str,
        source_type: str,
        artifact_path: str | None = None,
        source_section_ids: list[str] | None = None,
        supplement_ids: list[str] | None = None,
        created_by: str = "system",
        select: bool = True,
    ) -> dict:
        with self.session_factory() as session:
            version_no = (session.query(func.max(ChapterVersionRecord.version_no)).filter_by(project_id=project_id, node_id=node_id).scalar() or 0) + 1
            row = ChapterVersionRecord(
                id=new_id("ver"),
                project_id=project_id,
                node_id=node_id,
                version_no=version_no,
                source_type=source_type,
                title=title,
                markdown=markdown,
                artifact_path=artifact_path,
                source_section_ids_json=_json(source_section_ids or []),
                supplement_ids_json=_json(supplement_ids or []),
                created_by=created_by,
                status="selected" if select else "candidate",
            )
            session.add(row)
            if select:
                outline = _get_outline(session, project_id, node_id)
                _mark_versions_candidate(session, project_id, node_id)
                row.status = "selected"
                outline.selected_version_id = row.id
            session.commit()
            return _version_dict(row)

    def list_versions(self, project_id: str, node_id: str) -> list[dict]:
        with self.session_factory() as session:
            rows = session.query(ChapterVersionRecord).filter_by(project_id=project_id, node_id=node_id).order_by(ChapterVersionRecord.version_no.desc()).all()
            return [_version_dict(row) for row in rows]

    def get_version(self, project_id: str, node_id: str, version_id: str) -> dict:
        with self.session_factory() as session:
            row = session.get(ChapterVersionRecord, version_id)
            if row is None or row.project_id != project_id or row.node_id != node_id:
                raise KeyError(f"Unknown version_id: {version_id}")
            return _version_dict(row)

    def select_version(self, project_id: str, node_id: str, version_id: str) -> dict:
        with self.session_factory() as session:
            row = session.get(ChapterVersionRecord, version_id)
            if row is None or row.project_id != project_id or row.node_id != node_id:
                raise KeyError(f"Unknown version_id: {version_id}")
            outline = _get_outline(session, project_id, node_id)
            _mark_versions_candidate(session, project_id, node_id)
            row.status = "selected"
            outline.selected_version_id = row.id
            session.commit()
            return _version_dict(row)

    def propose_chapter_edit(self, project_id: str, node_id: str, suggestion: str, preview_markdown: str) -> dict:
        return self._create_proposal(project_id, "chapter", node_id, suggestion, {"markdown": preview_markdown})

    def propose_outline_change(self, project_id: str, suggestion: str, preview_nodes: list[dict]) -> dict:
        return self._create_proposal(project_id, "outline", project_id, suggestion, {"nodes": preview_nodes})

    def apply_proposal(self, project_id: str, proposal_id: str) -> dict:
        with self.session_factory() as session:
            proposal = session.get(AIChangeProposalRecord, proposal_id)
            if proposal is None or proposal.project_id != project_id:
                raise KeyError(f"Unknown proposal_id: {proposal_id}")
            data = json.loads(proposal.preview_json)
            if proposal.target_type == "chapter":
                node = _get_outline(session, project_id, proposal.target_id)
                version_no = (session.query(func.max(ChapterVersionRecord.version_no)).filter_by(project_id=project_id, node_id=proposal.target_id).scalar() or 0) + 1
                _mark_versions_candidate(session, project_id, proposal.target_id)
                version = ChapterVersionRecord(
                    id=new_id("ver"),
                    project_id=project_id,
                    node_id=proposal.target_id,
                    version_no=version_no,
                    source_type="ai_edit",
                    title=node.title,
                    markdown=data.get("markdown", ""),
                    source_section_ids_json="[]",
                    supplement_ids_json="[]",
                    created_by="ai",
                    status="selected",
                )
                session.add(version)
                node.selected_version_id = version.id
            elif proposal.target_type == "outline":
                for patch in data.get("nodes", []):
                    node_id = patch.get("node_id")
                    if not node_id:
                        continue
                    row = _get_outline(session, project_id, node_id)
                    for key, value in patch.items():
                        if key in {"title", "level", "sort_order", "enabled", "parent_id"}:
                            setattr(row, key, value)
            proposal.status = "applied"
            proposal.applied_at = datetime.now()
            session.commit()
            return _proposal_dict(proposal)

    def _create_proposal(self, project_id: str, target_type: str, target_id: str, suggestion: str, preview: dict) -> dict:
        with self.session_factory() as session:
            row = AIChangeProposalRecord(
                id=new_id("proposal"),
                project_id=project_id,
                target_type=target_type,
                target_id=target_id,
                suggestion=suggestion,
                preview_json=_json(preview),
            )
            session.add(row)
            session.commit()
            return _proposal_dict(row)


def _get_outline(session, project_id: str, node_id: str) -> ProjectOutlineNodeRecord:
    row = session.query(ProjectOutlineNodeRecord).filter_by(project_id=project_id, node_id=node_id).one_or_none()
    if row is None:
        raise KeyError(f"Unknown node_id: {node_id}")
    return row


def _get_supplement(session, project_id: str, node_id: str, supplement_id: str) -> ChapterSupplementRecord:
    row = session.get(ChapterSupplementRecord, supplement_id)
    if row is None or row.project_id != project_id or row.node_id != node_id:
        raise KeyError(f"Unknown supplement_id: {supplement_id}")
    return row


def _mark_versions_candidate(session, project_id: str, node_id: str) -> None:
    for row in session.query(ChapterVersionRecord).filter_by(project_id=project_id, node_id=node_id).all():
        row.status = "candidate"


def _outline_dict(row: ProjectOutlineNodeRecord) -> dict:
    return {
        "id": row.node_id,
        "node_id": row.node_id,
        "parent_id": row.parent_id,
        "title": row.title,
        "level": row.level,
        "sort_order": row.sort_order,
        "enabled": row.enabled,
        "source_rules": _loads(row.source_rules_json),
        "auto_fill": _loads(row.auto_fill_json),
        "manual_fill": _loads(row.manual_fill_json),
        "special_notes": _loads(row.special_notes_json),
        "selected_version_id": row.selected_version_id,
    }


def _supplement_dict(row: ChapterSupplementRecord) -> dict:
    return {
        "id": row.id,
        "kind": row.kind,
        "title": row.title,
        "content": row.content,
        "must_include": row.must_include,
        "sort_order": row.sort_order,
        "created_at": row.created_at.isoformat(),
        "updated_at": row.updated_at.isoformat(),
    }


def _attachment_dict(row: ChapterAttachmentRecord) -> dict:
    return {
        "id": row.id,
        "file_name": row.file_name,
        "content_type": row.content_type,
        "artifact_path": row.artifact_path,
        "description": row.description,
        "created_at": row.created_at.isoformat(),
    }


def _version_dict(row: ChapterVersionRecord) -> dict:
    return {
        "id": row.id,
        "node_id": row.node_id,
        "version_no": row.version_no,
        "source_type": row.source_type,
        "title": row.title,
        "markdown": row.markdown,
        "artifact_path": row.artifact_path,
        "prompt_trace_id": row.prompt_trace_id,
        "source_section_ids": _loads(row.source_section_ids_json),
        "supplement_ids": _loads(row.supplement_ids_json),
        "created_by": row.created_by,
        "status": row.status,
        "created_at": row.created_at.isoformat(),
    }


def _proposal_dict(row: AIChangeProposalRecord) -> dict:
    return {
        "id": row.id,
        "target_type": row.target_type,
        "target_id": row.target_id,
        "suggestion": row.suggestion,
        "preview": _loads(row.preview_json),
        "status": row.status,
        "created_at": row.created_at.isoformat(),
        "applied_at": row.applied_at.isoformat() if row.applied_at else None,
    }


def _json(value) -> str:
    return json.dumps(value, ensure_ascii=False)


def _loads(value: str):
    return json.loads(value) if value else None
