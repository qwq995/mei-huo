from __future__ import annotations

import json
import hashlib
import re
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from coalplan.application.content_revision_plan import build_content_revision_plan, render_content_revision_plan_markdown
from coalplan.application.chapter_generation_plan import (
    ChapterGenerationPlan,
    render_chapter_plan_for_prompt,
    validate_saved_plan,
    with_plan_fingerprint,
)
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
    ProjectMemoryRecord,
    SupplementBatchRecord,
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

    def outline_overview(self, project_id: str) -> dict:
        """Return a compact, prompt-ready overview of the whole editable outline."""
        nodes = self.list_outline_nodes(project_id)
        by_id = {node["node_id"]: node for node in nodes}
        paths: dict[str, list[str]] = {}
        for node in nodes:
            chain: list[str] = []
            cursor = node
            seen: set[str] = set()
            while cursor and cursor.get("node_id") not in seen:
                node_id = cursor.get("node_id")
                if node_id:
                    seen.add(node_id)
                    chain.append(cursor.get("title") or node_id)
                cursor = by_id.get(cursor.get("parent_id")) if cursor else None
            paths[node["node_id"]] = list(reversed(chain))
        compact = []
        for node in nodes:
            summary = node.get("chapter_summary") or {}
            readiness, readiness_reasons = _outline_readiness(node)
            compact.append({
                "node_id": node["node_id"],
                "title": node.get("title", ""),
                "level": node.get("level"),
                "parent_id": node.get("parent_id"),
                "path": paths.get(node["node_id"], []),
                "enabled": node.get("enabled", True),
                "target_word_count": node.get("target_word_count"),
                "overview": summary.get("generated_overview") or summary.get("overview", ""),
                "scope": summary.get("scope", []),
                "key_points": summary.get("key_points", []),
                "source_basis": summary.get("source_basis", []) or node.get("source_rules", []),
                "missing_information": summary.get("missing_information", []),
                "unresolved_items": summary.get("unresolved_items", []),
                "auto_fill": node.get("auto_fill", []),
                "manual_fill": node.get("manual_fill", []),
                "generation_role": summary.get("generation_role", "leaf"),
                "coverage_status": summary.get("coverage_status", "unknown"),
                "readiness": readiness,
                "readiness_reasons": readiness_reasons,
            })
        return {
            "project_id": project_id,
            "node_count": len(compact),
            "summary_count": sum(bool(item["overview"]) for item in compact),
            "missing_information_count": sum(bool(item["missing_information"] or item["unresolved_items"] or item["manual_fill"]) for item in compact),
            "nodes": compact,
        }

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
                origin=payload.get("origin", "user"),
                template_anchor_id=payload.get("template_anchor_id"),
                source_hints_json=_json(payload.get("source_hints", [])),
                matched_skill_keys_json=_json(payload.get("matched_skill_keys", [])),
                chapter_summary_json=_json(payload.get("chapter_summary", {})),
            )
            session.add(row)
            session.commit()
            return _outline_dict(row)

    def update_outline_node(self, project_id: str, node_id: str, payload: dict) -> dict:
        with self.session_factory() as session:
            row = _get_outline(session, project_id, node_id)
            for key in [
                "title",
                "parent_id",
                "level",
                "sort_order",
                "enabled",
                "target_word_count",
                "origin",
                "template_anchor_id",
            ]:
                if key in payload:
                    setattr(row, key, payload[key])
            mapping = {
                "source_rules": "source_rules_json",
                "auto_fill": "auto_fill_json",
                "manual_fill": "manual_fill_json",
                "special_notes": "special_notes_json",
                "source_hints": "source_hints_json",
                "matched_skill_keys": "matched_skill_keys_json",
                "chapter_summary": "chapter_summary_json",
            }
            for key, column in mapping.items():
                if key in payload:
                    setattr(row, column, _json(payload[key]))
            row.updated_at = datetime.now()
            session.commit()
            return _outline_dict(row)

    def move_outline_node(self, project_id: str, node_id: str, direction: str) -> dict:
        if direction not in {"up", "down", "indent", "outdent"}:
            raise ValueError("Unsupported outline move direction")
        with self.session_factory() as session:
            row = _get_outline(session, project_id, node_id)
            siblings = session.query(ProjectOutlineNodeRecord).filter_by(project_id=project_id, parent_id=row.parent_id).order_by(ProjectOutlineNodeRecord.sort_order.asc()).all()
            index = next((i for i, item in enumerate(siblings) if item.node_id == node_id), -1)
            if direction in {"up", "down"}:
                target_index = index - 1 if direction == "up" else index + 1
                if target_index < 0 or target_index >= len(siblings):
                    return _outline_dict(row)
                other = siblings[target_index]
                row.sort_order, other.sort_order = other.sort_order, row.sort_order
            elif direction == "indent":
                if index <= 0:
                    return _outline_dict(row)
                parent = siblings[index - 1]
                row.parent_id = parent.node_id
                row.level = parent.level + 1
            elif row.parent_id:
                parent = _get_outline(session, project_id, row.parent_id)
                row.parent_id = parent.parent_id
                row.level = max(1, parent.level)
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

    def sync_outline_tree(self, project_id: str, nodes: list[TemplateNode]) -> list[dict]:
        desired = list(_walk_template_nodes(nodes))
        with self.session_factory() as session:
            existing = {
                row.node_id: row
                for row in session.query(ProjectOutlineNodeRecord).filter_by(project_id=project_id).all()
            }
            desired_ids: set[str] = set()
            for sort_order, (node, parent_id) in enumerate(desired, start=1):
                desired_ids.add(node.id)
                row = existing.get(node.id)
                if row is None:
                    row = ProjectOutlineNodeRecord(
                        id=f"{project_id}:{node.id}",
                        project_id=project_id,
                        node_id=node.id,
                    )
                    session.add(row)
                row.parent_id = parent_id
                row.title = node.title
                row.level = node.level
                row.sort_order = sort_order
                row.enabled = True
                row.source_rules_json = _json(node.source_rules)
                row.auto_fill_json = _json(node.auto_fill)
                row.manual_fill_json = _json(node.manual_fill)
                row.special_notes_json = _json(node.special_notes)
                row.target_word_count = node.target_word_count
                row.origin = node.origin
                row.template_anchor_id = node.template_anchor_id
                row.source_hints_json = _json(node.source_hints)
                row.matched_skill_keys_json = _json(node.matched_skill_keys)
                row.chapter_summary_json = _json(node.chapter_summary)
                row.updated_at = datetime.now()
            for node_id, row in existing.items():
                if node_id not in desired_ids and row.selected_version_id is None:
                    row.enabled = False
            session.commit()
        return self.list_outline_nodes(project_id)

    def delete_outline_node(self, project_id: str, node_id: str, *, delete_subtree: bool = True) -> None:
        with self.session_factory() as session:
            row = _get_outline(session, project_id, node_id)
            rows = session.query(ProjectOutlineNodeRecord).filter_by(project_id=project_id).all()
            children_by_parent: dict[str | None, list[ProjectOutlineNodeRecord]] = {}
            for item in rows:
                children_by_parent.setdefault(item.parent_id, []).append(item)
            if delete_subtree:
                to_delete: list[ProjectOutlineNodeRecord] = []
                queue = [row]
                while queue:
                    current = queue.pop()
                    to_delete.append(current)
                    queue.extend(children_by_parent.get(current.node_id, []))
                for item in to_delete:
                    session.delete(item)
            else:
                promoted = children_by_parent.get(row.node_id, [])
                for child in promoted:
                    child.parent_id = row.parent_id

                    def lower_descendant_levels(parent_id: str) -> None:
                        for descendant in children_by_parent.get(parent_id, []):
                            descendant.level = max(1, (descendant.level or 1) - 1)
                            lower_descendant_levels(descendant.node_id)

                    child.level = max(1, (child.level or 1) - 1)
                    lower_descendant_levels(child.node_id)
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
                        origin=row.get("origin", "template"),
                        template_anchor_id=row.get("template_anchor_id"),
                        source_hints=row.get("source_hints", []),
                        matched_skill_keys=row.get("matched_skill_keys", []),
                        chapter_summary=row.get("chapter_summary", {}),
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
                "generation_plan": _generation_plan_from_outline(outline),
                "supplements": [_supplement_dict(row) for row in supplements],
                "attachments": [_attachment_dict(row) for row in attachments],
                "versions": [self._version_dict_with_tree(row) for row in versions],
                "selected_version_id": outline.selected_version_id,
                "proposals": [_proposal_dict(row) for row in proposals],
            }

    def list_project_memories(self, project_id: str, *, status: str = "active") -> list[dict]:
        with self.session_factory() as session:
            query = session.query(ProjectMemoryRecord).filter_by(project_id=project_id)
            if status:
                query = query.filter_by(status=status)
            rows = query.order_by(ProjectMemoryRecord.updated_at.desc()).all()
            return [_memory_dict(row) for row in rows]

    def add_project_memory(self, project_id: str, payload: dict) -> dict:
        content = str(payload.get("content") or "").strip()
        if not content:
            raise ValueError("项目长期记忆内容不能为空")
        topic = str(payload.get("topic") or payload.get("title") or "项目补充信息").strip()
        tags = _unique_texts(payload.get("tags") or [])
        with self.session_factory() as session:
            duplicate = session.query(ProjectMemoryRecord).filter_by(project_id=project_id, content=content, status="active").first()
            if duplicate is not None:
                return _memory_dict(duplicate)
            row = ProjectMemoryRecord(
                id=new_id("memory"), project_id=project_id, topic=topic, content=content,
                source_node_id=payload.get("source_node_id"), tags_json=_json(tags), status="active",
            )
            session.add(row)
            session.commit()
            return _memory_dict(row)

    def update_project_memory(self, project_id: str, memory_id: str, payload: dict) -> dict:
        with self.session_factory() as session:
            row = session.get(ProjectMemoryRecord, memory_id)
            if row is None or row.project_id != project_id:
                raise KeyError(f"Unknown memory_id: {memory_id}")
            for key in ["topic", "content", "source_node_id", "status"]:
                if key in payload and payload[key] is not None:
                    setattr(row, key, payload[key])
            if "tags" in payload:
                row.tags_json = _json(_unique_texts(payload["tags"] or []))
            row.updated_at = datetime.now()
            session.commit()
            return _memory_dict(row)

    def match_project_memories(self, project_id: str, node: TemplateNode, *, limit: int = 12) -> list[dict]:
        memories = self.list_project_memories(project_id)
        query = " ".join([
            node.title, *node.source_rules, *node.auto_fill, *node.manual_fill, *node.special_notes,
            (node.chapter_summary or {}).get("overview", ""),
            " ".join((node.chapter_summary or {}).get("key_points", [])),
        ])
        ranked: list[tuple[int, dict]] = []
        for memory in memories:
            score, matched = _memory_relevance(query, memory)
            if score <= 0:
                continue
            item = dict(memory)
            item["match_score"] = score
            item["matched_terms"] = matched
            ranked.append((score, item))
        ranked.sort(key=lambda pair: (-pair[0], pair[1]["memory_id"]))
        return [item for _, item in ranked[:limit]]

    def create_supplement_batch(self, project_id: str) -> dict:
        nodes = self.list_outline_nodes(project_id)
        node_by_id = {node["node_id"]: node for node in nodes}
        version_needs: dict[str, list[str]] = {}
        with self.session_factory() as session:
            versions = session.query(ChapterVersionRecord).filter_by(project_id=project_id).all()
            for version in versions:
                version_needs.setdefault(version.node_id, []).extend(
                    re.findall(r"【需人工补充：?(.*?)】", version.markdown or "")
                )
        buckets: list[dict] = []
        for node in nodes:
            summary = node.get("chapter_summary") or {}
            candidates = [
                *node.get("manual_fill", []),
                *summary.get("missing_information", []),
                *summary.get("unresolved_items", []),
            ]
            for text in candidates:
                label = _clean_missing_item(text)
                if not label:
                    continue
                existing = next((item for item in buckets if _missing_related(item["label"], label)), None)
                if existing is None:
                    existing = {
                        "item_id": new_id("need"), "label": label, "description": label,
                        "node_ids": [], "node_titles": [], "source_items": [],
                        "value": "", "status": "pending", "allow_ai": True,
                    }
                    buckets.append(existing)
                if node["node_id"] not in existing["node_ids"]:
                    existing["node_ids"].append(node["node_id"])
                    existing["node_titles"].append(node.get("title", ""))
                existing["source_items"].append({"node_id": node["node_id"], "text": str(text)})
        for node_id, needs in version_needs.items():
            node = node_by_id.get(node_id)
            if node is None:
                continue
            for text in needs:
                label = _clean_missing_item(text)
                if not label:
                    continue
                existing = next((item for item in buckets if _missing_related(item["label"], label)), None)
                if existing is None:
                    existing = {
                        "item_id": new_id("need"), "label": label, "description": label,
                        "node_ids": [], "node_titles": [], "source_items": [],
                        "value": "", "status": "pending", "allow_ai": True,
                    }
                    buckets.append(existing)
                if node_id not in existing["node_ids"]:
                    existing["node_ids"].append(node_id)
                    existing["node_titles"].append(node.get("title", ""))
                existing["source_items"].append({"node_id": node_id, "text": label, "source": "generated_version"})
        payload = {
            "batch_id": new_id("suppbatch"), "project_id": project_id,
            "scope": "all_chapters", "items": buckets,
            "message": "已按语义相近的待补事项合并；填写后会回映到关联章节，是否重新生成由用户确认。",
        }
        with self.session_factory() as session:
            row = SupplementBatchRecord(id=payload["batch_id"], project_id=project_id, payload_json=_json(payload), status="draft")
            session.add(row)
            session.commit()
        return payload

    def get_supplement_batch(self, project_id: str, batch_id: str) -> dict:
        with self.session_factory() as session:
            row = session.get(SupplementBatchRecord, batch_id)
            if row is None or row.project_id != project_id:
                raise KeyError(f"Unknown supplement_batch_id: {batch_id}")
            return _loads(row.payload_json)

    def apply_supplement_batch(self, project_id: str, batch_id: str, values: dict[str, str], selected_item_ids: list[str] | None = None) -> dict:
        payload = self.get_supplement_batch(project_id, batch_id)
        selected = set(selected_item_ids) if selected_item_ids is not None else {item["item_id"] for item in payload.get("items", [])}
        updated: list[dict] = []
        affected: set[str] = set()
        with self.session_factory() as session:
            for item in payload.get("items", []):
                if item["item_id"] not in selected:
                    continue
                value = str(values.get(item["item_id"], item.get("value") or "")).strip()
                if not value:
                    continue
                item["value"] = value
                item["status"] = "filled"
                updated.append(item)
                for node_id in item.get("node_ids", []):
                    affected.add(node_id)
                    supplement = session.query(ChapterSupplementRecord).filter_by(
                        project_id=project_id, node_id=node_id, title=item["label"], content=value,
                    ).first()
                    if supplement is None:
                        supplement = ChapterSupplementRecord(
                            id=new_id("supp"), project_id=project_id, node_id=node_id,
                            kind="project_memory", title=item["label"], content=value,
                            must_include=True, sort_order=999,
                        )
                        session.add(supplement)
                    duplicate = session.query(ProjectMemoryRecord).filter_by(project_id=project_id, content=value, status="active").first()
                    if duplicate is None:
                        session.add(ProjectMemoryRecord(
                            id=new_id("memory"), project_id=project_id, topic=item["label"], content=value,
                            source_node_id=node_id, source_supplement_id=supplement.id,
                            tags_json=_json(item.get("node_titles", [])), status="active",
                        ))
            payload["updated_item_ids"] = [item["item_id"] for item in updated]
            payload["affected_node_ids"] = sorted(affected)
            payload["status"] = "applied"
            row = session.get(SupplementBatchRecord, batch_id)
            row.payload_json = _json(payload)
            row.status = "applied"
            row.updated_at = datetime.now()
            session.commit()
        return {"batch_id": batch_id, "status": "applied", "updated_items": updated, "affected_node_ids": sorted(affected), "needs_user_confirmation_to_regenerate": bool(affected)}

    def save_supplement_ai_suggestions(self, project_id: str, batch_id: str, suggestions: dict[str, str]) -> dict:
        payload = self.get_supplement_batch(project_id, batch_id)
        for item in payload.get("items", []):
            suggestion = str(suggestions.get(item["item_id"]) or "").strip()
            if suggestion:
                item["ai_suggestion"] = suggestion
        payload["ai_suggestion_status"] = "ready"
        with self.session_factory() as session:
            row = session.get(SupplementBatchRecord, batch_id)
            if row is None or row.project_id != project_id:
                raise KeyError(f"Unknown supplement_batch_id: {batch_id}")
            row.payload_json = _json(payload)
            row.updated_at = datetime.now()
            session.commit()
        return payload

    def render_chapter_context(self, project_id: str, node_id: str) -> str:
        workspace = self.get_workspace(project_id, node_id)
        lines = []
        plan_context = render_chapter_plan_for_prompt(workspace.get("generation_plan"))
        if plan_context:
            lines.extend([plan_context, ""])
        lines.append("## 用户补充材料")
        for item in workspace["supplements"]:
            if item.get("kind") == "ignored_manual_requirement":
                continue
            must = "必须写入正文" if item["must_include"] else "参考材料"
            lines.extend([f"### {item['title'] or item['kind']}（{must}）", item["content"], ""])
        for item in workspace["attachments"]:
            lines.extend([f"### 附件：{item['file_name']}", f"路径：{item['artifact_path']}", f"说明：{item['description'] or '【无】'}", ""])
        node = TemplateNode.model_validate(workspace["outline_node"])
        memories = self.match_project_memories(project_id, node)
        if memories:
            lines.extend([
                "## 项目长期记忆（按本章相关度匹配）",
                "以下内容来自用户补充或确认过的项目级信息，可供本章复用；如与当前投标资料冲突，以有效项目资料和用户最新确认为准。",
            ])
            for item in memories:
                terms = "、".join(item.get("matched_terms") or []) or "相关"
                lines.extend([f"### {item['topic'] or '项目补充信息'}（匹配：{terms}）", item["content"], ""])
        selected = next((item for item in workspace["versions"] if item["id"] == workspace["selected_version_id"]), None)
        if selected:
            lines.extend(["## 当前选中历史版本", selected["markdown"][:4000]])
        return "\n".join(lines).strip()

    def save_chapter_generation_plan(self, project_id: str, node_id: str, payload: dict) -> dict:
        with self.session_factory() as session:
            row = _get_outline(session, project_id, node_id)
            plan = validate_saved_plan(payload, node_id=node_id, title=row.title)
            summary = _loads(row.chapter_summary_json)
            summary["generation_plan"] = plan.model_dump()
            row.chapter_summary_json = _json(summary)
            row.updated_at = datetime.now()
            session.commit()
            return plan.model_dump()

    def create_chapter_plan_proposal(
        self,
        project_id: str,
        node_id: str,
        suggestion: str,
        plan: ChapterGenerationPlan,
        *,
        base_fingerprint: str,
    ) -> dict:
        preview = {
            "plan": plan.model_dump(),
            "base_fingerprint": base_fingerprint,
        }
        return self._create_proposal(
            project_id,
            "chapter_plan",
            node_id,
            suggestion,
            preview,
            reuse_pending=True,
        )

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
            # A non-ignored supplement becomes reusable project memory immediately.
            # The original chapter supplement remains the source record and can still be edited.
            content = str(payload.get("content") or "").strip()
            if content and payload.get("kind", "text") != "ignored_manual_requirement":
                duplicate = session.query(ProjectMemoryRecord).filter_by(
                    project_id=project_id, content=content, status="active"
                ).first()
                if duplicate is None:
                    session.add(ProjectMemoryRecord(
                        id=new_id("memory"), project_id=project_id,
                        topic=str(payload.get("title") or "项目补充信息").strip(),
                        content=content, source_node_id=node_id,
                        source_supplement_id=row.id,
                        tags_json=_json([str(payload.get("title") or ""), node_id]), status="active",
                    ))
            session.commit()
            return _supplement_dict(row)

    def update_supplement(self, project_id: str, node_id: str, supplement_id: str, payload: dict) -> dict:
        with self.session_factory() as session:
            row = _get_supplement(session, project_id, node_id, supplement_id)
            for key in ["kind", "title", "content", "must_include", "sort_order"]:
                if key in payload:
                    setattr(row, key, payload[key])
            row.updated_at = datetime.now()
            memory = session.query(ProjectMemoryRecord).filter_by(
                project_id=project_id, source_supplement_id=supplement_id, status="active"
            ).first()
            if memory is not None:
                memory.topic = row.title or memory.topic
                memory.content = row.content
                memory.updated_at = datetime.now()
                if row.kind == "ignored_manual_requirement" or not row.content.strip():
                    memory.status = "inactive"
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
            # Keep version history immutable and addressable. A chapter-level
            # draft path is accepted for compatibility but is never reused.
            if artifact_path:
                row.artifact_path = self.artifacts.write_text(
                    project_id,
                    f"chapters/{node_id}/versions/{row.id}.md",
                    markdown,
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

    def confirm_version_review(
        self,
        project_id: str,
        node_id: str,
        version_id: str,
        *,
        note: str = "",
    ) -> dict:
        version = self.get_version(project_id, node_id, version_id)
        metadata = version.get("generation_metadata")
        if not isinstance(metadata, dict):
            raise ValueError("该版本没有生成凭据，不能直接确认为通过。")
        organization_audit = audit_version_generation_metadata(version)
        if organization_audit.get("status") != "passed":
            issues = organization_audit.get("issues") or []
            raise ValueError("章节提纲仍有未覆盖内容：" + (str(issues[0]) if issues else "请继续修订后再确认。"))
        updated = json.loads(json.dumps(metadata, ensure_ascii=False))
        updated["quality_review"] = {
            "status": "passed",
            "advisory_only": False,
            "message": "用户已复核 AI 修订版本，并确认可作为当前章节使用。",
            "issues": [],
            "next_actions": [],
            "reviewed_by": "user",
            "review_note": note.strip(),
            "reviewed_at": datetime.now().isoformat(),
        }
        self._write_generation_metadata(project_id, node_id, version_id, updated)
        evidence_audit = version.get("evidence_audit")
        if isinstance(evidence_audit, dict):
            self._write_evidence_audit(
                project_id,
                node_id,
                version_id,
                _respect_confirmed_plan_in_evidence_audit(evidence_audit, updated),
            )
        return self.get_version(project_id, node_id, version_id)

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

    def propose_chapter_edit(
        self,
        project_id: str,
        node_id: str,
        suggestion: str,
        preview_markdown: str,
        *,
        display_markdown: str | None = None,
    ) -> dict:
        return self._create_proposal(
            project_id,
            "chapter",
            node_id,
            suggestion,
            {
                "markdown": preview_markdown,
                "display_markdown": display_markdown if display_markdown is not None else preview_markdown,
            },
        )

    def propose_outline_change(
        self, project_id: str, suggestion: str, preview_nodes: list[dict], *,
        scope_node_id: str | None = None, scope_mode: str = "subtree", preserve_top_level: bool = True,
        max_changes: int | None = None,
    ) -> dict:
        current = self.list_outline_nodes(project_id)
        fingerprint = _outline_fingerprint(current)
        strict_controls = scope_node_id is not None or max_changes is not None or scope_mode != "subtree"
        allowed = _outline_scope_ids(current, scope_node_id, include_descendants=scope_mode != "node")
        current_by_id = {item["node_id"]: item for item in current}
        filtered: list[dict] = []
        for node in preview_nodes:
            node_id = node.get("node_id")
            parent_id = node.get("parent_id")
            is_existing = node_id in {item["node_id"] for item in current}
            in_scope = node_id in allowed or (not is_existing and (parent_id in allowed if scope_node_id else True))
            if preserve_top_level and is_existing and int(current_by_id[node_id].get("level") or 0) == 1:
                in_scope = False
            if in_scope:
                filtered.append(node)
        changed = [node for node in filtered if node.get("__action", "change") != "keep"]
        if max_changes is not None and len(changed) > max_changes:
            raise ValueError(f"AI 方案包含 {len(changed)} 项变更，超过本次上限 {max_changes}，请缩小调整范围。")
        preview = {
            "nodes": filtered,
            "outline_fingerprint": fingerprint if strict_controls else None,
            "scope_node_id": scope_node_id,
            "scope_mode": scope_mode,
            "preserve_top_level": preserve_top_level,
            "max_changes": max_changes,
            "changed_node_ids": [node.get("node_id") for node in changed if node.get("node_id")],
            "change_summary": {"total": len(changed)},
        }
        return self._create_proposal(project_id, "outline", project_id, suggestion, preview, reuse_pending=True)

    def apply_proposal(
        self, project_id: str, proposal_id: str, *,
        include_node_ids: list[str] | None = None, exclude_node_ids: list[str] | None = None,
    ) -> dict:
        with self.session_factory() as session:
            proposal = session.get(AIChangeProposalRecord, proposal_id)
            if proposal is None or proposal.project_id != project_id:
                raise KeyError(f"Unknown proposal_id: {proposal_id}")
            data = json.loads(proposal.preview_json)
            if proposal.target_type == "chapter":
                node = _get_outline(session, project_id, proposal.target_id)
                selected = None
                selected_version_data = None
                if node.selected_version_id:
                    selected = session.get(ChapterVersionRecord, node.selected_version_id)
                fallback_tree = None
                if selected is not None:
                    selected_version_data = self._version_dict_with_tree(selected)
                    fallback_tree = selected_version_data.get("content_tree")
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
                    status="candidate",
                )
                version.artifact_path = self.artifacts.write_text(
                    project_id,
                    f"chapters/{proposal.target_id}/versions/{version.id}.md",
                    version.markdown,
                )
                session.add(version)
            elif proposal.target_type == "chapter_plan":
                node = _get_outline(session, project_id, proposal.target_id)
                current_plan = _generation_plan_from_outline(node)
                current_fingerprint = str((current_plan or {}).get("fingerprint") or "")
                expected = str(data.get("base_fingerprint") or "")
                if expected and expected != current_fingerprint:
                    raise ValueError("章节提纲在 AI 建议生成后已被修改，请重新生成建议。")
                plan = validate_saved_plan(
                    data.get("plan") or {},
                    node_id=proposal.target_id,
                    title=node.title,
                )
                plan.status = "draft"
                plan = with_plan_fingerprint(plan)
                summary = _loads(node.chapter_summary_json)
                summary["generation_plan"] = plan.model_dump()
                node.chapter_summary_json = _json(summary)
                node.updated_at = datetime.now()
            elif proposal.target_type == "outline":
                current = [_outline_dict(row) for row in session.query(ProjectOutlineNodeRecord).filter_by(project_id=project_id).all()]
                expected = data.get("outline_fingerprint")
                if expected and expected != _outline_fingerprint(current):
                    raise ValueError("目录在生成方案后已发生变化，请重新生成 AI 方案后再应用。")
                snapshot_id = new_id("outline_snapshot")
                self.artifacts.write_text(project_id, f"outline/snapshots/{snapshot_id}.json", _json({"snapshot_id": snapshot_id, "nodes": current}))
                excluded = set(exclude_node_ids or [])
                included = set(include_node_ids) if include_node_ids is not None else None
                for patch in data.get("nodes", []):
                    node_id = patch.get("node_id")
                    if not node_id or node_id in excluded or (included is not None and node_id not in included):
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
                            origin=patch.get("origin", "hybrid"),
                            template_anchor_id=patch.get("template_anchor_id"),
                            source_hints_json=_json(patch.get("source_hints", [])),
                            matched_skill_keys_json=_json(patch.get("matched_skill_keys", [])),
                            chapter_summary_json=_json(patch.get("chapter_summary", {})),
                        )
                        session.add(row)
                        continue
                    for key, value in patch.items():
                        if key in {
                            "title",
                            "level",
                            "sort_order",
                            "enabled",
                            "parent_id",
                            "target_word_count",
                            "origin",
                            "template_anchor_id",
                        }:
                            setattr(row, key, value)
                    json_fields = {
                        "source_rules": "source_rules_json",
                        "auto_fill": "auto_fill_json",
                        "manual_fill": "manual_fill_json",
                        "special_notes": "special_notes_json",
                        "source_hints": "source_hints_json",
                        "matched_skill_keys": "matched_skill_keys_json",
                        "chapter_summary": "chapter_summary_json",
                    }
                    for key, column in json_fields.items():
                        if key in patch:
                            setattr(row, column, _json(patch[key]))
                    row.updated_at = datetime.now()
            proposal.status = "applied"
            proposal.applied_at = datetime.now()
            if proposal.target_type == "outline":
                data["snapshot_id"] = snapshot_id
                data["applied_node_ids"] = [node.get("node_id") for node in data.get("nodes", []) if node.get("node_id") and node.get("node_id") not in (exclude_node_ids or []) and (include_node_ids is None or node.get("node_id") in include_node_ids)]
                proposal.preview_json = _json(data)
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
                previous_metadata = (selected_version_data or {}).get("generation_metadata")
                if isinstance(previous_metadata, dict):
                    edit_metadata = json.loads(json.dumps(previous_metadata, ensure_ascii=False))
                else:
                    edit_metadata = {}
                edit_metadata["ai_edit"] = {
                    "proposal_id": proposal.id,
                    "suggestion": proposal.suggestion,
                    "based_on_version_id": selected.id if selected is not None else None,
                }
                edit_metadata["quality_review"] = {
                    "status": "needs_repair",
                    "issues": ["AI 局部修订已应用，需复核提纲覆盖、项目事实和规范约束后再视为通过。"],
                    "next_actions": ["在章节正文与生成凭据中核对本次修改，确认后运行章节审查或继续修订。"],
                }
                self._write_generation_metadata(project_id, proposal.target_id, version.id, edit_metadata)
                previous_audit = (selected_version_data or {}).get("evidence_audit")
                if isinstance(previous_audit, dict):
                    refreshed_audit = _refresh_evidence_audit_for_markdown(previous_audit, version.markdown)
                    self._write_evidence_audit(
                        project_id,
                        proposal.target_id,
                        version.id,
                        _respect_confirmed_plan_in_evidence_audit(refreshed_audit, edit_metadata),
                    )
            return _proposal_dict(proposal)

    def restore_outline_snapshot(self, project_id: str, snapshot_id: str) -> dict:
        path = self.artifacts.root / project_id / "outline" / "snapshots" / f"{snapshot_id}.json"
        if not path.exists():
            raise KeyError(snapshot_id)
        snapshot = json.loads(path.read_text(encoding="utf-8"))
        with self.session_factory() as session:
            rows = session.query(ProjectOutlineNodeRecord).filter_by(project_id=project_id).all()
            for row in rows:
                session.delete(row)
            session.flush()
            for item in snapshot.get("nodes", []):
                values = dict(item)
                values.pop("children", None)
                session.add(ProjectOutlineNodeRecord(
                    id=f"{project_id}:{values['node_id']}", project_id=project_id,
                    node_id=values["node_id"], parent_id=values.get("parent_id"), title=values["title"],
                    level=int(values.get("level", 1)), sort_order=int(values.get("sort_order", 0)),
                    enabled=bool(values.get("enabled", True)), source_rules_json=_json(values.get("source_rules", [])),
                    auto_fill_json=_json(values.get("auto_fill", [])), manual_fill_json=_json(values.get("manual_fill", [])),
                    special_notes_json=_json(values.get("special_notes", [])), target_word_count=values.get("target_word_count"),
                    origin=values.get("origin", "snapshot"), template_anchor_id=values.get("template_anchor_id"),
                    source_hints_json=_json(values.get("source_hints", [])), matched_skill_keys_json=_json(values.get("matched_skill_keys", [])),
                    chapter_summary_json=_json(values.get("chapter_summary", {})),
                ))
            session.commit()
        return {"restored": True, "snapshot_id": snapshot_id, "node_count": len(snapshot.get("nodes", []))}

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
    payload = {
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
        "origin": row.origin,
        "template_anchor_id": row.template_anchor_id,
        "source_hints": _loads(row.source_hints_json),
        "matched_skill_keys": _loads(row.matched_skill_keys_json),
        "chapter_summary": _loads(row.chapter_summary_json),
        "selected_version_id": row.selected_version_id,
    }
    readiness, reasons = _outline_readiness(payload)
    payload["readiness"] = readiness
    payload["readiness_reasons"] = reasons
    return payload


def _respect_confirmed_plan_in_evidence_audit(audit: dict, metadata: dict) -> dict:
    plan = metadata.get("generation_plan") if isinstance(metadata, dict) else None
    if not isinstance(plan, dict) or plan.get("status") != "confirmed":
        return audit
    payload = json.loads(json.dumps(audit, ensure_ascii=False))
    suppressed_codes = {"omitted_required_source_facts", "low_evidence_utilization"}
    suppressed = [
        item for item in payload.get("issues") or []
        if isinstance(item, dict) and item.get("code") in suppressed_codes
    ]
    payload["issues"] = [
        item for item in payload.get("issues") or []
        if not (isinstance(item, dict) and item.get("code") in suppressed_codes)
    ]
    payload["confirmed_plan_scope"] = {
        "controlled": True,
        "suppressed_issue_codes": sorted({str(item.get("code")) for item in suppressed}),
        "message": "未采用的映射事实仍保留追溯记录，但已确认提纲范围优先，不强制把范围外事实写入正文。",
    }
    return payload


def _outline_readiness(node: dict) -> tuple[str, list[str]]:
    if node.get("enabled") is False:
        return "disabled", ["节点已禁用"]
    summary = node.get("chapter_summary") or {}
    if summary.get("generation_role") == "container":
        return "container", ["父节点用于组织目录，正文通常在下级节点生成"]
    reasons: list[str] = []
    if summary.get("coverage_status") not in {"grounded"} and not node.get("source_hints"):
        reasons.append("尚未确认投标来源")
    if summary.get("missing_information"):
        reasons.append(f"待补资料 {len(summary['missing_information'])} 项")
    if summary.get("unresolved_items"):
        reasons.append(f"待确认事项 {len(summary['unresolved_items'])} 项")
    if node.get("manual_fill"):
        reasons.append(f"人工补充 {len(node['manual_fill'])} 项")
    return ("needs_confirmation" if reasons else "ready"), reasons


def _walk_template_nodes(nodes: list[TemplateNode], parent_id: str | None = None):
    for node in nodes:
        yield node, parent_id
        yield from _walk_template_nodes(node.children, node.id)


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
    preview = _loads(row.preview_json)
    payload = {
        "id": row.id,
        "target_type": row.target_type,
        "target_id": row.target_id,
        "suggestion": row.suggestion,
        "preview": preview,
        "status": row.status,
        "created_at": row.created_at.isoformat(),
        "applied_at": row.applied_at.isoformat() if row.applied_at else None,
    }


def _memory_dict(row: ProjectMemoryRecord) -> dict:
    return {
        "memory_id": row.id,
        "project_id": row.project_id,
        "topic": row.topic,
        "content": row.content,
        "source_node_id": row.source_node_id,
        "source_supplement_id": row.source_supplement_id,
        "tags": _loads(row.tags_json),
        "status": row.status,
        "created_at": row.created_at.isoformat() if row.created_at else "",
        "updated_at": row.updated_at.isoformat() if row.updated_at else "",
    }


def _unique_texts(items) -> list[str]:
    output: list[str] = []
    seen: set[str] = set()
    for item in items:
        value = str(item).strip()
        key = re.sub(r"\s+", "", value).lower()
        if value and key not in seen:
            seen.add(key)
            output.append(value)
    return output[:30]


def _memory_relevance(query: str, memory: dict) -> tuple[int, list[str]]:
    memory_topic = str(memory.get("topic") or "")
    memory_text = " ".join([memory_topic, str(memory.get("content") or ""), *[str(x) for x in memory.get("tags") or []]])
    query_terms = _memory_terms(query)
    memory_terms = set(_memory_terms(memory_text))
    matched = [term for term in query_terms if term in memory_terms]
    topic_terms = set(_memory_terms(memory_topic))
    score = sum(5 if term in topic_terms else 2 for term in matched)
    if memory.get("source_node_id") and memory.get("source_node_id") in query:
        score += 4
    return score, list(dict.fromkeys(matched))[:12]


def _memory_terms(value: str) -> list[str]:
    terms = re.findall(r"[\u4e00-\u9fff]{2,8}|[A-Za-z]{2,}|\d+(?:\.\d+)?", value or "")
    stop = {"项目", "工程", "施工", "信息", "内容", "本章", "补充", "用于", "相关"}
    return list(dict.fromkeys(term.lower() for term in terms if term not in stop))


def _clean_missing_item(value: str) -> str:
    text = re.sub(r"【?需人工补充：?", "", str(value or ""))
    text = text.replace("】", "").strip(" -*•；;，,。")
    return re.sub(r"\s+", " ", text)[:240]


def _missing_related(left: str, right: str) -> bool:
    a = set(_memory_terms(left))
    b = set(_memory_terms(right))
    if not a or not b:
        return re.sub(r"\s+", "", left) == re.sub(r"\s+", "", right)
    return left == right or len(a & b) >= max(1, min(len(a), len(b)) // 2)
    if row.target_type == "outline" and isinstance(preview, dict):
        payload["snapshot_id"] = preview.get("snapshot_id")
    return payload


def _generation_plan_from_outline(row: ProjectOutlineNodeRecord) -> dict | None:
    summary = _loads(row.chapter_summary_json)
    plan = summary.get("generation_plan") if isinstance(summary, dict) else None
    return plan if isinstance(plan, dict) else None


def _outline_fingerprint(nodes: list[dict]) -> str:
    normalized = [{key: node.get(key) for key in ("node_id", "parent_id", "title", "level", "sort_order", "enabled", "target_word_count", "source_rules", "auto_fill", "manual_fill", "special_notes")} for node in nodes]
    normalized.sort(key=lambda item: (item.get("sort_order") or 0, item.get("node_id") or ""))
    return hashlib.sha256(json.dumps(normalized, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()


def _outline_scope_ids(nodes: list[dict], scope_node_id: str | None, *, include_descendants: bool = True) -> set[str]:
    if not scope_node_id:
        return {node["node_id"] for node in nodes}
    children: dict[str | None, list[str]] = {}
    for node in nodes:
        children.setdefault(node.get("parent_id"), []).append(node["node_id"])
    result: set[str] = set()
    pending = [scope_node_id]
    while pending:
        node_id = pending.pop()
        if node_id in result:
            continue
        result.add(node_id)
        if include_descendants:
            pending.extend(children.get(node_id, []))
    return result


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
