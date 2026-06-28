from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from coalplan.application.content_revision_plan import build_content_revision_plan, render_content_revision_plan_markdown
from sqlalchemy import func

from coalplan.application.generation_metadata_audit import audit_version_generation_metadata
from coalplan.application.generated_content_tree import build_generated_content_tree, replace_content_node_markdown
from coalplan.application.serialization import dump_model, to_json_text
from coalplan.domain.outline import SourceMappingResult
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
                target_word_count=payload.get("target_word_count"),
            )
            session.add(row)
            session.commit()
            return _outline_dict(row)

    def update_outline_node(self, project_id: str, node_id: str, payload: dict) -> dict:
        with self.session_factory() as session:
            row = _get_outline(session, project_id, node_id)
            for key in ["title", "parent_id", "level", "sort_order", "enabled", "target_word_count"]:
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

    def update_outline_word_counts(self, project_id: str, word_counts: dict[str, int | None]) -> list[dict]:
        with self.session_factory() as session:
            rows = session.query(ProjectOutlineNodeRecord).filter_by(project_id=project_id).all()
            for row in rows:
                if row.node_id in word_counts:
                    row.target_word_count = word_counts[row.node_id]
                    row.updated_at = datetime.now()
            session.commit()
            return self.list_outline_nodes(project_id)

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
                        target_word_count=row.get("target_word_count"),
                        children=build(row["node_id"]),
                    )
                )
            return nodes

        return build(None)

    def list_proposals(self, project_id: str, *, target_type: str | None = None, status: str | None = None) -> list[dict]:
        with self.session_factory() as session:
            query = session.query(AIChangeProposalRecord).filter_by(project_id=project_id)
            if target_type is not None:
                query = query.filter_by(target_type=target_type)
            if status is not None:
                query = query.filter_by(status=status)
            rows = query.order_by(AIChangeProposalRecord.created_at.desc()).all()
            return [_proposal_dict(row) for row in rows]

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
                "versions": [self._version_dict_with_tree(row) for row in versions],
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
        source_mapping: SourceMappingResult | dict | None = None,
        fallback_content_tree: dict | None = None,
        generation_metadata: dict | None = None,
        evidence_audit: dict | None = None,
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
            if generation_metadata is not None:
                self._write_generation_metadata(project_id, node_id, row.id, generation_metadata)
            if evidence_audit is not None:
                self._write_evidence_audit(project_id, node_id, row.id, evidence_audit)
            version = self._version_dict_with_tree(row, source_mapping=source_mapping, fallback_content_tree=fallback_content_tree)
            return version

    def list_versions(self, project_id: str, node_id: str) -> list[dict]:
        with self.session_factory() as session:
            rows = session.query(ChapterVersionRecord).filter_by(project_id=project_id, node_id=node_id).order_by(ChapterVersionRecord.version_no.desc()).all()
            return [self._version_dict_with_tree(row) for row in rows]

    def get_version(self, project_id: str, node_id: str, version_id: str) -> dict:
        with self.session_factory() as session:
            row = session.get(ChapterVersionRecord, version_id)
            if row is None or row.project_id != project_id or row.node_id != node_id:
                raise KeyError(f"Unknown version_id: {version_id}")
            return self._version_dict_with_tree(row)

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
            return self._version_dict_with_tree(row)

    def get_version_content_tree(self, project_id: str, node_id: str, version_id: str) -> dict:
        version = self.get_version(project_id, node_id, version_id)
        return version["content_tree"]

    def get_version_content_revision_plan(self, project_id: str, node_id: str, version_id: str) -> dict:
        version = self.get_version(project_id, node_id, version_id)
        return version["content_revision_plan"]

    def get_version_generation_metadata(self, project_id: str, node_id: str, version_id: str) -> dict:
        version = self.get_version(project_id, node_id, version_id)
        metadata = version.get("generation_metadata")
        if not metadata:
            raise KeyError(f"Generation metadata is not available for version_id: {version_id}")
        payload = dict(metadata)
        payload["organization_audit"] = audit_version_generation_metadata(version)
        return payload

    def get_version_evidence_audit(self, project_id: str, node_id: str, version_id: str) -> dict:
        version = self.get_version(project_id, node_id, version_id)
        audit = version.get("evidence_audit")
        if not audit:
            raise KeyError(f"Evidence audit is not available for version_id: {version_id}")
        return audit

    def update_version_content_node(
        self,
        project_id: str,
        node_id: str,
        version_id: str,
        content_node_id: str,
        markdown: str,
        *,
        select: bool = True,
        generation_metadata: dict | None = None,
        evidence_audit: dict | None = None,
    ) -> dict:
        version = self.get_version(project_id, node_id, version_id)
        updated_markdown = replace_content_node_markdown(
            version["markdown"],
            node_id=node_id,
            content_node_id=content_node_id,
            replacement_markdown=markdown,
        )
        return self.create_chapter_version(
            project_id,
            node_id,
            title=version["title"],
            markdown=updated_markdown,
            artifact_path=None,
            source_type="subsection_edit",
            source_section_ids=version.get("source_section_ids", []),
            supplement_ids=version.get("supplement_ids", []),
            created_by="user",
            select=select,
            fallback_content_tree=version.get("content_tree"),
            generation_metadata=generation_metadata,
            evidence_audit=_refresh_evidence_audit_for_markdown(evidence_audit, updated_markdown) if evidence_audit else None,
        )

    def propose_chapter_edit(self, project_id: str, node_id: str, suggestion: str, preview_markdown: str) -> dict:
        return self._create_proposal(project_id, "chapter", node_id, suggestion, {"markdown": preview_markdown})

    def propose_outline_change(self, project_id: str, suggestion: str, preview_nodes: list[dict]) -> dict:
        return self._create_proposal(project_id, "outline", project_id, suggestion, {"nodes": preview_nodes}, reuse_pending=True)

    def apply_proposal(self, project_id: str, proposal_id: str) -> dict:
        with self.session_factory() as session:
            proposal = session.get(AIChangeProposalRecord, proposal_id)
            if proposal is None or proposal.project_id != project_id:
                raise KeyError(f"Unknown proposal_id: {proposal_id}")
            data = json.loads(proposal.preview_json)
            if proposal.target_type == "chapter":
                node = _get_outline(session, project_id, proposal.target_id)
                selected = None
                if node.selected_version_id:
                    selected = session.get(ChapterVersionRecord, node.selected_version_id)
                fallback_tree = None
                if selected is not None:
                    fallback_tree = self._version_dict_with_tree(selected).get("content_tree")
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
                    source_section_ids_json=selected.source_section_ids_json if selected is not None else "[]",
                    supplement_ids_json=selected.supplement_ids_json if selected is not None else "[]",
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
                    row = session.query(ProjectOutlineNodeRecord).filter_by(project_id=project_id, node_id=node_id).one_or_none()
                    if row is None:
                        sort_order = patch.get("sort_order")
                        if sort_order is None:
                            sort_order = (session.query(func.max(ProjectOutlineNodeRecord.sort_order)).filter_by(project_id=project_id).scalar() or 0) + 1
                        row = ProjectOutlineNodeRecord(
                            id=f"{project_id}:{node_id}",
                            project_id=project_id,
                            node_id=node_id,
                            parent_id=patch.get("parent_id"),
                            title=patch.get("title") or node_id,
                            level=int(patch.get("level", 1)),
                            sort_order=int(sort_order),
                            enabled=bool(patch.get("enabled", True)),
                            source_rules_json=_json(patch.get("source_rules", [])),
                            auto_fill_json=_json(patch.get("auto_fill", [])),
                            manual_fill_json=_json(patch.get("manual_fill", [])),
                            special_notes_json=_json(patch.get("special_notes", [])),
                            target_word_count=patch.get("target_word_count"),
                        )
                        session.add(row)
                        continue
                    for key, value in patch.items():
                        if key in {"title", "level", "sort_order", "enabled", "parent_id", "target_word_count"}:
                            setattr(row, key, value)
                    json_fields = {
                        "source_rules": "source_rules_json",
                        "auto_fill": "auto_fill_json",
                        "manual_fill": "manual_fill_json",
                        "special_notes": "special_notes_json",
                    }
                    for key, column in json_fields.items():
                        if key in patch:
                            setattr(row, column, _json(patch[key]))
                    row.updated_at = datetime.now()
            proposal.status = "applied"
            proposal.applied_at = datetime.now()
            session.commit()
            if proposal.target_type == "chapter":
                self._ensure_content_tree(
                    project_id=project_id,
                    node_id=proposal.target_id,
                    version_id=version.id,
                    title=version.title,
                    markdown=version.markdown,
                    fallback_content_tree=fallback_tree,
                )
            return _proposal_dict(proposal)

    def reject_proposal(
        self,
        project_id: str,
        proposal_id: str,
        *,
        target_type: str | None = None,
        target_id: str | None = None,
    ) -> dict:
        with self.session_factory() as session:
            proposal = session.get(AIChangeProposalRecord, proposal_id)
            if proposal is None or proposal.project_id != project_id:
                raise KeyError(f"Unknown proposal_id: {proposal_id}")
            if target_type is not None and proposal.target_type != target_type:
                raise KeyError(f"Unknown proposal_id for target_type: {proposal_id}")
            if target_id is not None and proposal.target_id != target_id:
                raise KeyError(f"Unknown proposal_id for target_id: {proposal_id}")
            if proposal.status == "applied":
                raise ValueError("Applied proposals cannot be rejected.")
            proposal.status = "rejected"
            session.commit()
            return _proposal_dict(proposal)

    def _create_proposal(
        self,
        project_id: str,
        target_type: str,
        target_id: str,
        suggestion: str,
        preview: dict,
        *,
        reuse_pending: bool = False,
    ) -> dict:
        with self.session_factory() as session:
            if reuse_pending:
                existing_rows = (
                    session.query(AIChangeProposalRecord)
                    .filter_by(
                        project_id=project_id,
                        target_type=target_type,
                        target_id=target_id,
                        suggestion=suggestion,
                        status="pending",
                    )
                    .order_by(AIChangeProposalRecord.created_at.desc())
                    .all()
                )
                if existing_rows:
                    existing = existing_rows[0]
                    existing.preview_json = _json(preview)
                    existing.created_at = datetime.now()
                    for duplicate in existing_rows[1:]:
                        duplicate.status = "superseded"
                    session.commit()
                    return _proposal_dict(existing)
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

    def _version_dict_with_tree(
        self,
        row: ChapterVersionRecord,
        source_mapping: SourceMappingResult | dict | None = None,
        fallback_content_tree: dict | None = None,
    ) -> dict:
        data = _version_dict(row)
        tree = self._ensure_content_tree(
            project_id=row.project_id,
            node_id=row.node_id,
            version_id=row.id,
            title=row.title,
            markdown=row.markdown,
            source_mapping=source_mapping,
            fallback_content_tree=fallback_content_tree,
        )
        data["content_tree"] = tree
        data["content_tree_path"] = tree.get("artifact_path")
        evidence_audit = self._load_evidence_audit(row.project_id, row.node_id, row.id)
        revision_plan = self._ensure_content_revision_plan(
            project_id=row.project_id,
            node_id=row.node_id,
            version_id=row.id,
            content_tree=tree,
            evidence_audit=evidence_audit,
        )
        data["content_revision_plan"] = revision_plan
        data["content_revision_plan_path"] = revision_plan.get("artifact_path")
        metadata = self._load_generation_metadata(row.project_id, row.node_id, row.id)
        data["generation_metadata"] = metadata
        data["generation_metadata_path"] = metadata.get("artifact_path") if metadata else None
        data["evidence_audit"] = evidence_audit
        data["evidence_audit_path"] = evidence_audit.get("artifact_path") if evidence_audit else None
        return data

    def _write_generation_metadata(self, project_id: str, node_id: str, version_id: str, metadata: dict) -> str:
        relative = _generation_metadata_relative_path(node_id, version_id)
        payload = dict(metadata)
        payload["version_id"] = version_id
        payload["node_id"] = node_id
        artifact_path = self.artifacts.write_text(project_id, relative, to_json_text(payload))
        payload["artifact_path"] = artifact_path
        Path(artifact_path).write_text(to_json_text(payload), encoding="utf-8")
        return artifact_path

    def _load_generation_metadata(self, project_id: str, node_id: str, version_id: str) -> dict | None:
        relative = _generation_metadata_relative_path(node_id, version_id)
        path = Path(self.artifacts.root) / project_id / relative
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8-sig"))
            data.setdefault("artifact_path", str(path))
            return data
        except Exception:
            return None

    def _write_evidence_audit(self, project_id: str, node_id: str, version_id: str, audit: dict) -> str:
        relative = _evidence_audit_relative_path(node_id, version_id)
        payload = dict(audit)
        payload["version_id"] = version_id
        payload["node_id"] = node_id
        artifact_path = self.artifacts.write_text(project_id, relative, to_json_text(payload))
        payload["artifact_path"] = artifact_path
        Path(artifact_path).write_text(to_json_text(payload), encoding="utf-8")
        self.artifacts.write_text(project_id, _evidence_audit_markdown_relative_path(node_id, version_id), _render_evidence_audit_markdown(payload))
        return artifact_path

    def _load_evidence_audit(self, project_id: str, node_id: str, version_id: str) -> dict | None:
        relative = _evidence_audit_relative_path(node_id, version_id)
        path = Path(self.artifacts.root) / project_id / relative
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8-sig"))
            data.setdefault("artifact_path", str(path))
            return data
        except Exception:
            return None

    def _ensure_content_tree(
        self,
        *,
        project_id: str,
        node_id: str,
        version_id: str,
        title: str,
        markdown: str,
        source_mapping: SourceMappingResult | dict | None = None,
        fallback_content_tree: dict | None = None,
    ) -> dict:
        relative = _content_tree_relative_path(node_id, version_id)
        path = Path(self.artifacts.root) / project_id / relative
        if path.exists() and source_mapping is None and fallback_content_tree is None:
            try:
                return json.loads(path.read_text(encoding="utf-8-sig"))
            except Exception:
                pass
        tree = build_generated_content_tree(
            node_id=node_id,
            title=title,
            markdown=markdown,
            version_id=version_id,
            source_mapping=source_mapping,
            fallback_tree=fallback_content_tree,
        )
        artifact_path = self.artifacts.write_text(project_id, relative, to_json_text(dump_model(tree)))
        data = dump_model(tree)
        data["artifact_path"] = artifact_path
        Path(artifact_path).write_text(to_json_text(data), encoding="utf-8")
        return data

    def _ensure_content_revision_plan(
        self,
        *,
        project_id: str,
        node_id: str,
        version_id: str,
        content_tree: dict,
        evidence_audit: dict | None = None,
    ) -> dict:
        relative = _content_revision_plan_relative_path(node_id, version_id)
        path = Path(self.artifacts.root) / project_id / relative
        if path.exists() and evidence_audit is None:
            try:
                return json.loads(path.read_text(encoding="utf-8-sig"))
            except Exception:
                pass
        plan = build_content_revision_plan(content_tree, evidence_audit=evidence_audit)
        artifact_path = self.artifacts.write_text(project_id, relative, to_json_text(dump_model(plan)))
        data = dump_model(plan)
        data["artifact_path"] = artifact_path
        Path(artifact_path).write_text(to_json_text(data), encoding="utf-8")
        self.artifacts.write_text(project_id, _content_revision_plan_markdown_relative_path(node_id, version_id), render_content_revision_plan_markdown(plan))
        return data


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


def _refresh_evidence_audit_for_markdown(audit: dict, markdown: str) -> dict:
    payload = dict(audit)
    normalized = _normalize_evidence_text(markdown)
    required_facts = [dict(item) for item in payload.get("required_source_facts") or [] if isinstance(item, dict)]
    omitted = [
        str(fact.get("fact_id"))
        for fact in required_facts
        if fact.get("fact_id") and not _required_fact_dict_used(normalized, fact)
    ]
    payload["omitted_required_fact_ids"] = omitted
    payload["used_evidence_ids"] = _dedupe_text(
        [
            *(payload.get("used_evidence_ids") or []),
            *[
                str(fact.get("evidence_id"))
                for fact in required_facts
                if fact.get("evidence_id") and str(fact.get("fact_id")) not in omitted
            ],
        ]
    )
    payload["issues"] = [
        issue
        for issue in payload.get("issues") or []
        if not (isinstance(issue, dict) and issue.get("code") == "omitted_required_source_facts")
    ]
    if omitted:
        omitted_facts = [fact for fact in required_facts if str(fact.get("fact_id")) in omitted]
        payload["issues"].append(
            {
                "code": "omitted_required_source_facts",
                "message": "Generated body omitted high-value facts that were present in mapped source evidence.",
                "severity": "warning",
                "evidence_ids": sorted({str(fact.get("evidence_id")) for fact in omitted_facts if fact.get("evidence_id")}),
                "terms": [str(fact.get("text")) for fact in omitted_facts[:12] if fact.get("text")],
                "suggested_action": "regenerate",
            }
        )
    if payload.get("evidence_count"):
        payload["coverage_ratio"] = round(len(payload.get("used_evidence_ids") or []) / max(1, int(payload.get("evidence_count") or 1)), 3)
    return payload


def _required_fact_dict_used(normalized_markdown: str, fact: dict) -> bool:
    tokens = [str(token) for token in fact.get("tokens") or [] if str(token).strip()]
    if not tokens and fact.get("text"):
        tokens = re.findall(r"[\u4e00-\u9fff]{2,12}|[A-Za-z0-9.%-]+", str(fact.get("text")))
    if not tokens:
        return False
    numeric_tokens = [token for token in tokens if any(char.isdigit() for char in token)]
    if numeric_tokens:
        return any(_normalize_evidence_text(token) in normalized_markdown for token in numeric_tokens)
    normalized_tokens = [_normalize_evidence_text(token) for token in tokens if _normalize_evidence_text(token)]
    return sum(1 for token in normalized_tokens if token in normalized_markdown) >= min(2, len(normalized_tokens))


def _normalize_evidence_text(text: str) -> str:
    return re.sub(r"\s+", "", str(text or "")).lower()


def _dedupe_text(items: list[str]) -> list[str]:
    output: list[str] = []
    for item in items:
        if item and item not in output:
            output.append(item)
    return output


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
        "target_word_count": row.target_word_count,
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


def _content_tree_relative_path(node_id: str, version_id: str) -> str:
    return f"chapters/{node_id}/versions/{version_id}.content_tree.json"


def _content_revision_plan_relative_path(node_id: str, version_id: str) -> str:
    return f"chapters/{node_id}/versions/{version_id}.content_revision_plan.json"


def _content_revision_plan_markdown_relative_path(node_id: str, version_id: str) -> str:
    return f"chapters/{node_id}/versions/{version_id}.content_revision_plan.md"


def _generation_metadata_relative_path(node_id: str, version_id: str) -> str:
    return f"chapters/{node_id}/versions/{version_id}.generation_metadata.json"


def _evidence_audit_relative_path(node_id: str, version_id: str) -> str:
    return f"chapters/{node_id}/versions/{version_id}.evidence_audit.json"


def _evidence_audit_markdown_relative_path(node_id: str, version_id: str) -> str:
    return f"chapters/{node_id}/versions/{version_id}.evidence_audit.md"


def _render_evidence_audit_markdown(audit: dict) -> str:
    lines = [
        f"# Evidence Utilization Audit: {audit.get('title') or audit.get('node_id') or '-'}",
        "",
        f"- node_id: `{audit.get('node_id') or '-'}`",
        f"- version_id: `{audit.get('version_id') or '-'}`",
        f"- evidence_count: {audit.get('evidence_count', 0)}",
        f"- coverage_ratio: {audit.get('coverage_ratio') if audit.get('coverage_ratio') is not None else '-'}",
        f"- used_evidence_ids: {', '.join(audit.get('used_evidence_ids') or []) or '-'}",
        f"- unused_high_value_evidence_ids: {', '.join(audit.get('unused_high_value_evidence_ids') or []) or '-'}",
        f"- omitted_required_fact_ids: {', '.join(audit.get('omitted_required_fact_ids') or []) or '-'}",
        "",
        "## Issues",
    ]
    issues = audit.get("issues") or []
    if not issues:
        lines.append("- No evidence-utilization issue.")
    for issue in issues:
        lines.append(
            f"- {issue.get('code') or '-'} / {issue.get('severity') or '-'} / "
            f"{issue.get('suggested_action') or '-'}: {issue.get('message') or '-'}"
        )
        terms = issue.get("terms") or []
        if terms:
            lines.extend(f"  - {term}" for term in terms[:8])
    facts = audit.get("required_source_facts") or []
    if facts:
        lines.extend(["", "## Required Source Facts"])
        for fact in facts[:20]:
            lines.append(
                f"- `{fact.get('fact_id')}` [{fact.get('fact_type') or '-'}] "
                f"{fact.get('text') or '-'}"
            )
    manual_supported = audit.get("manual_items_with_source_support") or []
    if manual_supported:
        lines.extend(["", "## Manual Items With Source Support"])
        lines.extend(f"- {item}" for item in manual_supported)
    return "\n".join(lines).strip() + "\n"
