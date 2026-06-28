from __future__ import annotations

import json
import re
from pathlib import Path
from uuid import uuid4

from coalplan.application.content_revision_plan import build_content_revision_plan, render_content_revision_plan_markdown
from coalplan.application.current_execution_window import build_current_execution_window, render_current_execution_window_markdown
from coalplan.application.generate_chapter import generate_chapter
from coalplan.application.generate_project_profile import generate_project_profile
from coalplan.application.generation_metadata_audit import audit_version_generation_metadata
from coalplan.application.generation_readiness import build_generation_readiness_report, render_generation_readiness_markdown
from coalplan.application.generation_control_plan import (
    build_generation_control_plan,
    build_outline_repair_proposal_nodes,
    build_project_subsection_proposal_nodes,
    build_subsection_proposal_nodes,
    render_generation_control_plan,
)
from coalplan.application.ingest_bid_markdown import ingest_bid_markdown
from coalplan.application.iteration_plan import build_iteration_plan, render_iteration_plan_markdown
from coalplan.application.load_template_tree import load_template_tree
from coalplan.application.map_chapter_sources import map_chapter_sources
from coalplan.application.map_sources_to_template import build_chapter_tasks
from coalplan.application.merge_chapters import merge_chapters
from coalplan.application.persist_source_index import persist_source_index
from coalplan.application.plan_template_outline import (
    apply_outline_to_template_tree,
    build_outline_generation_steps,
    build_template_outline_plan,
    plan_template_outline,
    render_outline_markdown,
)
from coalplan.application.pipeline_action_plan import build_pipeline_action_plan
from coalplan.application.pipeline_stage_gates import build_pipeline_gate_report
from coalplan.application.pre_generation_outline_refine import build_pre_generation_outline_refine
from coalplan.application.quality_audit import QualityAuditInput, audit_generation_quality, render_quality_audit_markdown
from coalplan.application.quality_audit_targets import (
    build_quality_audit_revision_targets,
    render_quality_audit_revision_targets,
)
from coalplan.application.quality_feedback import (
    apply_quality_feedback_to_generation_plan,
    build_quality_feedback_plan,
    build_quality_outline_repair_proposal_nodes,
    quality_feedback_required_fact_hints,
    render_quality_feedback_mapping_context,
    render_quality_feedback_prompt_context,
    render_quality_feedback_plan,
)
from coalplan.application.quality_iteration_learning import (
    build_quality_iteration_learning_report,
    render_quality_iteration_learning_report,
)
from coalplan.application.revision_decision import build_revision_decisions, render_revision_decisions
from coalplan.application.serialization import dump_model, to_json_text
from coalplan.application.pattern_card_usage_audit import audit_pattern_card_usage
from coalplan.application.targeted_revision_plan import build_targeted_revision_plan, render_targeted_revision_plan
from coalplan.application.word_count_targets import estimate_word_count_targets
from coalplan.domain.documents import stable_id
from coalplan.domain.enums import RunStatus, TaskStatus
from coalplan.domain.generation_control import ChapterRevisionDecision, GenerationControlPlan, QualityFeedbackPlan
from coalplan.domain.generation import ChapterDraft, ChapterTask, GenerationRun, Project
from coalplan.domain.templates import TemplateNode, TemplateTree, iter_template_nodes
from coalplan.infrastructure.markdown.renderer import merge_template_tree_markdowns
from coalplan.domain.validation import ValidationIssue
from coalplan.ports.llm import LLMClient, StructuredLLMClient
from coalplan.ports.markdown_parser import MarkdownParser
from coalplan.ports.repository import ArtifactRepository, ProjectRepository
from coalplan.ports.retriever import SourceRetriever
from coalplan.ports.template_loader import TemplateLoader


class GenerationPipeline:
    def __init__(
        self,
        *,
        projects: ProjectRepository,
        artifacts: ArtifactRepository,
        parser: MarkdownParser,
        templates: TemplateLoader,
        retriever: SourceRetriever,
        llm: LLMClient,
        structured_llm: StructuredLLMClient | None = None,
        workspace_store=None,
    ) -> None:
        self.projects = projects
        self.artifacts = artifacts
        self.parser = parser
        self.templates = templates
        self.retriever = retriever
        self.llm = llm
        self.structured_llm = structured_llm
        self.workspace_store = workspace_store
        self._drafts: dict[str, list[ChapterDraft]] = {}

    def create_project(self, name: str, template_id: str = "coal_fire") -> Project:
        project = Project(name=name, template_id=template_id)
        project = load_template_tree(project, template_id=template_id, loader=self.templates)
        return self.projects.save(project)

    def ingest_bid_markdown(self, project_id: str, *, file_name: str, content: str) -> Project:
        project = self.projects.get(project_id)
        project = ingest_bid_markdown(project, file_name=file_name, content=content, parser=self.parser, artifacts=self.artifacts)
        return self.projects.save(project)

    def set_template(self, project_id: str, template_id: str) -> Project:
        project = self.projects.get(project_id)
        if project.runs:
            raise ValueError("Template cannot be changed after generation runs have been created.")
        project.template_id = template_id
        project.template_tree = None
        project.outline_plan = None
        project = load_template_tree(project, template_id=template_id, loader=self.templates)
        return self.projects.save(project)

    def prepare_directory(self, project_id: str) -> Project:
        project = self.projects.get(project_id)
        project = self._ensure_base_context(project)
        if project.outline_plan is None and project.template_tree is not None and project.project_profile is not None and project.source_toc is not None:
            project.outline_plan = build_template_outline_plan(
                profile=project.project_profile,
                toc_items=project.source_toc.items,
                template_tree=project.template_tree,
            )
            project.outline_plan.artifact_json_path = self.artifacts.write_text(
                project.id,
                "outline/generated_outline.json",
                to_json_text(dump_model(project.outline_plan)),
            )
            project.outline_plan.artifact_markdown_path = self.artifacts.write_text(
                project.id,
                "outline/generated_outline.md",
                render_outline_markdown(project.outline_plan),
            )
        project = self.projects.save(project)
        project.template_tree = self._effective_template_tree(project)
        if project.runs:
            self._sync_run_tasks(project, project.runs[-1])
            project = self.projects.save(project)
        else:
            run = GenerationRun(project_name=project.name, template_id=project.template_id)
            if project.template_tree is None:
                raise ValueError("Project template tree is not loaded.")
            self._sync_run_tasks(project, run)
            project.runs.append(run)
            project = self.projects.save(project)
        return project

    def repair_project_profile(self, project_id: str) -> Project:
        project = self.projects.get(project_id)
        if not project.sections:
            raise ValueError("No bid markdown sections are available. Upload and normalize a bid markdown file before repairing project profile.")
        if project.source_toc is None:
            project.source_toc = persist_source_index(project.id, project.sections, self.artifacts)
        project.project_profile = generate_project_profile(
            project_id=project.id,
            toc_items=project.source_toc.items,
            sections=project.sections,
            llm=self._structured_llm(),
            artifacts=self.artifacts,
        )
        project.outline_plan = None
        return self.projects.save(project)

    def estimate_outline_word_counts(self, project_id: str, reference_markdown: str | None = None) -> dict:
        if self.workspace_store is None:
            raise ValueError("Workspace store is not configured.")
        project = self.prepare_directory(project_id)
        project.template_tree = self._effective_template_tree(project)
        if project.template_tree is None:
            raise ValueError("Project template tree is not loaded.")
        estimates = estimate_word_count_targets(project.template_tree.nodes, reference_markdown)
        nodes = self.workspace_store.update_outline_word_counts(
            project.id,
            {estimate.node_id: estimate.target_word_count for estimate in estimates},
        )
        payload = {
            "project_id": project.id,
            "reference_supplied": bool(reference_markdown and reference_markdown.strip()),
            "estimates": [dump_model(estimate) for estimate in estimates],
            "nodes": nodes,
        }
        self.artifacts.write_text(project.id, "outline/word_count_targets.json", to_json_text(payload))
        self.artifacts.write_text(project.id, "outline/word_count_targets.md", _render_word_count_targets(estimates))
        return payload

    def propose_ai_outline(self, project_id: str, suggestion: str = "") -> dict:
        if self.workspace_store is None:
            raise ValueError("Workspace store is not configured.")
        project = self.projects.get(project_id)
        project = self._ensure_base_context(project)
        if project.template_tree is None or project.project_profile is None or project.source_toc is None:
            raise ValueError("Project directory context is incomplete.")
        outline = plan_template_outline(
            project_id=project.id,
            profile=project.project_profile,
            toc_items=project.source_toc.items,
            template_tree=project.template_tree,
            llm=self._structured_llm(),
            artifacts=self.artifacts,
        )
        preview_nodes = [
            {
                "node_id": node.node_id,
                "title": node.title,
                "level": node.level,
                "enabled": node.enabled,
                "source_rules": node.main_sources,
                "auto_fill": node.auto_fill,
                "manual_fill": node.manual_fill,
                "special_notes": node.special_notes,
            }
            for node in outline.nodes
        ]
        text = suggestion or "AI 基于项目概况、投标目录和模板四模块生成目录优化建议。"
        return self.workspace_store.propose_outline_change(project.id, text, preview_nodes)

    def generation_control_plan(self, project_id: str) -> GenerationControlPlan:
        project = self.projects.get(project_id)
        project = self._ensure_base_context(project)
        project.template_tree = self._effective_template_tree(project)
        if project.template_tree is None or project.source_toc is None:
            raise ValueError("Project generation control context is incomplete.")
        return self._generation_control_plan(project)

    def quality_feedback_plan(self, project_id: str) -> QualityFeedbackPlan | None:
        return self._load_quality_feedback(project_id)

    def pipeline_gate_report(self, project_id: str) -> dict:
        project = self.projects.get(project_id)
        template_tree = self._effective_template_tree(project)
        control_plan = None
        feedback = self._load_quality_feedback(project.id)
        if template_tree is not None and project.source_toc is not None:
            try:
                control_plan = build_generation_control_plan(
                    project_id=project.id,
                    template_tree=template_tree,
                    toc_items=project.source_toc.items,
                )
                if feedback:
                    control_plan = apply_quality_feedback_to_generation_plan(control_plan, feedback)
            except Exception:
                control_plan = None
        report = build_pipeline_gate_report(
            project=project,
            template_tree=template_tree,
            control_plan=control_plan,
            revision_decisions=self._load_revision_decisions(project.id),
            quality_feedback=dump_model(feedback) if feedback else None,
            workspace_store=self.workspace_store,
            artifacts_root=getattr(self.artifacts, "root", None),
        )
        return dump_model(report)

    def pipeline_action_plan(self, project_id: str) -> dict:
        gate_report = self.pipeline_gate_report(project_id)
        revisions = self._load_revision_decisions(project_id)
        plan = build_pipeline_action_plan(
            project_id=project_id,
            gate_report=gate_report,
            revision_decisions=revisions,
            version_content_targets=self._version_content_revision_targets(project_id),
            version_metadata_targets=self._version_generation_metadata_targets(project_id),
            version_evidence_targets=self._version_evidence_utilization_targets(project_id),
            outline_step_targets=self._outline_step_action_targets(project_id),
            child_generation_targets=self._child_generation_action_targets(project_id),
        )
        return dump_model(plan)

    def generation_readiness(self, project_id: str) -> dict:
        project = self.projects.get(project_id)
        template_tree = self._effective_template_tree(project)
        control_plan = None
        if template_tree is not None and project.source_toc is not None:
            try:
                project.template_tree = template_tree
                control_plan = self._generation_control_plan(project)
            except Exception:
                control_plan = None
        report = build_generation_readiness_report(
            project=project,
            template_tree=template_tree,
            control_plan=control_plan,
            revision_decisions=self._load_revision_decisions(project.id),
            generation_metadata_targets=self._version_generation_metadata_targets(project.id),
            workspace_store=self.workspace_store,
        )
        payload = dump_model(report)
        payload["artifact_json_path"] = self.artifacts.write_text(
            project_id,
            "control/generation_readiness.json",
            to_json_text(payload),
        )
        payload["artifact_markdown_path"] = self.artifacts.write_text(
            project_id,
            "control/generation_readiness.md",
            render_generation_readiness_markdown(report),
        )
        return payload

    def execute_generation_readiness_batch(
        self,
        project_id: str,
        *,
        group_id: str | None = None,
        include_user_confirmation: bool = False,
        limit: int = 10,
        respect_execution_window: bool = True,
    ) -> dict:
        readiness = self.generation_readiness(project_id)
        window = self.current_execution_window(project_id) if respect_execution_window else None
        window_warning = None
        if respect_execution_window and not _readiness_execution_allowed_by_window(window):
            window_warning = {
                "kind": "advisory_execution_window",
                "message": "Current execution window recommends handling these actions first, but execution is not blocked.",
                "current_phase_id": (window or {}).get("current_phase_id"),
                "allowed_action_ids": [item.get("action_id") for item in ((window or {}).get("allowed_actions") or [])],
            }
        batches = readiness.get("batches") or []
        selected_batches = [
            batch
            for batch in batches
            if (group_id and batch.get("group_id") == group_id)
            or (not group_id and batch.get("execution_mode") == "auto")
        ]
        executed: list[dict] = []
        skipped: list[dict] = []
        failed: list[dict] = []
        touched_nodes: set[str] = set()
        remaining = max(0, int(limit))
        if group_id and not selected_batches:
            skipped.append({"group_id": group_id, "reason": "Readiness batch group was not found or has no items."})
        for batch in selected_batches:
            batch_mode = str(batch.get("execution_mode") or "manual_review")
            for item in batch.get("items") or []:
                if remaining <= 0:
                    skipped.append({"batch": batch.get("group_id"), "item": item, "reason": "Execution limit reached."})
                    continue
                node_id = str(item.get("node_id") or "")
                action = str(item.get("next_action") or "")
                if not node_id or not action:
                    skipped.append({"batch": batch.get("group_id"), "item": item, "reason": "Missing node_id or next_action."})
                    continue
                if node_id in touched_nodes:
                    skipped.append({"batch": batch.get("group_id"), "item": item, "reason": "Node was already handled by an earlier readiness batch item."})
                    continue
                if batch_mode != "auto" and not include_user_confirmation:
                    skipped.append({"batch": batch.get("group_id"), "item": item, "reason": "Batch requires user confirmation or manual review."})
                    continue
                if item.get("requires_user_confirmation") and not include_user_confirmation:
                    skipped.append({"batch": batch.get("group_id"), "item": item, "reason": "Item requires user confirmation."})
                    continue
                try:
                    result = self._execute_readiness_item(project_id, node_id, action)
                    touched_nodes.add(node_id)
                    for generated in result.get("generated") or []:
                        generated_id = generated.get("node_id")
                        if generated_id:
                            touched_nodes.add(str(generated_id))
                    executed.append(_readiness_execution_entry(batch.get("group_id"), item, result))
                    remaining -= 1
                except Exception as exc:
                    failed.append({"batch": batch.get("group_id"), "item": item, "error": str(exc)})
                    remaining -= 1
        next_readiness = self.generation_readiness(project_id)
        payload = {
            "project_id": project_id,
            "status": "failed" if failed and not executed else ("partial_failed" if failed else "completed"),
            "group_id": group_id,
            "include_user_confirmation": include_user_confirmation,
            "limit": limit,
            "respect_execution_window": respect_execution_window,
            "executed": executed,
            "skipped": skipped,
            "failed": failed,
            "source_readiness": readiness,
            "next_readiness": next_readiness,
            "execution_window": window,
            "execution_window_warning": window_warning,
        }
        payload["artifact_json_path"] = self.artifacts.write_text(
            project_id,
            "control/generation_readiness_batch_execution.json",
            to_json_text(payload),
        )
        payload["artifact_markdown_path"] = self.artifacts.write_text(
            project_id,
            "control/generation_readiness_batch_execution.md",
            _render_generation_readiness_batch_execution(payload),
        )
        return payload

    def _execute_readiness_item(self, project_id: str, node_id: str, action: str) -> dict:
        if action in {"generate_chapter", "map_sources_then_generate"}:
            draft = self.generate_one(project_id, node_id)
            return {
                "kind": "chapter_generation",
                "node_id": node_id,
                "action": action,
                "draft_id": draft.id,
                "status": draft.validation_status.value,
                "artifact_path": draft.artifact_path,
            }
        if action == "generate_child_chapters":
            result = self.generate_child_chapters(project_id, node_id, only_pending=True)
            return {"kind": "child_branch_generation", "node_id": node_id, "action": action, **result}
        if action in {"regenerate", "remap_sources", "repair_format", "expand_subsections", "request_human_input", "disable_node"}:
            response = self.execute_revision_action(project_id, node_id, action)
            return {"kind": "revision_action", "node_id": node_id, "action": action, "response": response}
        raise ValueError(f"Unsupported readiness action for batch execution: {action}")

    def targeted_revision_plan(self, project_id: str) -> dict:
        project = self.projects.get(project_id)
        summary = self._targeted_revision_summary(project)
        plan = build_targeted_revision_plan(summary)
        payload = dict(plan)
        payload["artifact_json_path"] = self.artifacts.write_text(
            project_id,
            "control/targeted_revision_plan.json",
            to_json_text(plan),
        )
        payload["artifact_markdown_path"] = self.artifacts.write_text(
            project_id,
            "control/targeted_revision_plan.md",
            render_targeted_revision_plan(plan),
        )
        return payload

    def outline_generation_step_progress(self, project_id: str) -> dict:
        project = self.projects.get(project_id)
        outline = project.outline_plan
        if outline is None:
            payload = {
                "project_id": project_id,
                "status": "not_prepared",
                "steps": [],
                "summary": "Directory outline has not been prepared.",
            }
            payload["artifact_json_path"] = self.artifacts.write_text(
                project_id,
                "control/outline_generation_step_progress.json",
                to_json_text(payload),
            )
            return payload

        template_tree = self._effective_template_tree(project)
        if not outline.generation_steps and template_tree is not None:
            outline.generation_steps = build_outline_generation_steps(outline, template_tree)
        run = project.runs[-1] if project.runs else None
        task_by_node = {task.node_id: task for task in (run.chapter_tasks if run else [])}
        workspace_by_node = self._workspace_summary_by_node(project_id)
        steps: list[dict] = []
        for step in outline.generation_steps:
            nodes = []
            for node_id in step.node_ids:
                task = task_by_node.get(node_id)
                workspace = workspace_by_node.get(node_id, {})
                selected = workspace.get("selected_version") or {}
                content_actions = _content_revision_action_count(selected.get("content_revision_plan"))
                metadata_audit = audit_version_generation_metadata(selected) if selected else None
                nodes.append(
                    {
                        "node_id": node_id,
                        "title": workspace.get("title") or _outline_node_title(outline, node_id) or node_id,
                        "task_status": task.status.value if task else "not_in_run",
                        "source_section_ids": _task_source_section_ids(task),
                        "selected_version_id": workspace.get("selected_version_id"),
                        "content_revision_action_count": content_actions,
                        "generation_metadata_status": (metadata_audit or {}).get("status"),
                        "generation_metadata_action_count": ((metadata_audit or {}).get("metrics") or {}).get("actionable_count", 0),
                    }
                )
            step_payload = {
                "step_id": step.step_id,
                "level": step.level,
                "parent_node_id": step.parent_node_id,
                "node_ids": step.node_ids,
                "source_section_ids": step.source_section_ids,
                "description": step.description,
                "status": _outline_step_status(nodes),
                "nodes": nodes,
            }
            steps.append(step_payload)
        status = _outline_progress_status(steps)
        payload = {
            "project_id": project_id,
            "status": status,
            "summary": _outline_progress_summary(steps),
            "steps": steps,
        }
        payload["artifact_json_path"] = self.artifacts.write_text(
            project_id,
            "control/outline_generation_step_progress.json",
            to_json_text(payload),
        )
        return payload

    def generate_outline_step(self, project_id: str, step_id: str) -> dict:
        project = self.prepare_directory(project_id)
        project = self.projects.get(project_id)
        outline = project.outline_plan
        if outline is None:
            raise ValueError("Project outline has not been prepared.")
        template_tree = self._effective_template_tree(project)
        if not outline.generation_steps and template_tree is not None:
            outline.generation_steps = build_outline_generation_steps(outline, template_tree)
        step = next((item for item in outline.generation_steps if item.step_id == step_id), None)
        if step is None:
            raise KeyError(f"Unknown outline generation step: {step_id}")

        run = self.sync_generation_tasks(project_id)
        project = self.projects.get(project_id)
        run = project.runs[-1] if project.runs else run
        task_node_ids = {task.node_id for task in (run.chapter_tasks if run else [])}
        generated: list[dict] = []
        skipped: list[dict] = []
        failed: list[dict] = []
        for node_id in step.node_ids:
            if node_id not in task_node_ids:
                skipped.append({"node_id": node_id, "reason": "Node has no generation contract or is not in the current run."})
                continue
            try:
                draft = self.generate_one(project_id, node_id)
                generated.append(
                    {
                        "node_id": node_id,
                        "draft_id": draft.id,
                        "status": draft.validation_status.value,
                        "artifact_path": draft.artifact_path,
                    }
                )
            except Exception as exc:
                failed.append({"node_id": node_id, "error": str(exc)})
        progress = self.outline_generation_step_progress(project_id)
        payload = {
            "project_id": project_id,
            "step_id": step_id,
            "status": "failed" if failed and not generated else ("partial_failed" if failed else "completed"),
            "generated": generated,
            "skipped": skipped,
            "failed": failed,
            "progress": progress,
        }
        payload["artifact_json_path"] = self.artifacts.write_text(
            project_id,
            f"control/outline_generation_step_{_safe_artifact_name(step_id)}.json",
            to_json_text(payload),
        )
        return payload

    def iteration_plan(self, project_id: str) -> dict:
        gate_report = self.pipeline_gate_report(project_id)
        revisions = self._load_revision_decisions(project_id)
        action_plan = build_pipeline_action_plan(
            project_id=project_id,
            gate_report=gate_report,
            revision_decisions=revisions,
            version_content_targets=self._version_content_revision_targets(project_id),
            version_metadata_targets=self._version_generation_metadata_targets(project_id),
            version_evidence_targets=self._version_evidence_utilization_targets(project_id),
            outline_step_targets=self._outline_step_action_targets(project_id),
            child_generation_targets=self._child_generation_action_targets(project_id),
        )
        feedback = self._load_quality_feedback(project_id)
        plan = build_iteration_plan(
            project_id=project_id,
            action_plan=action_plan,
            quality_feedback=dump_model(feedback) if feedback else None,
            revision_decisions=revisions,
        )
        json_path = self.artifacts.write_text(project_id, "control/iteration_plan.json", to_json_text(dump_model(plan)))
        md_path = self.artifacts.write_text(project_id, "control/iteration_plan.md", render_iteration_plan_markdown(plan))
        payload = dump_model(plan)
        payload["artifact_json_path"] = json_path
        payload["artifact_markdown_path"] = md_path
        return payload

    def current_execution_window(self, project_id: str) -> dict:
        iteration = self.iteration_plan(project_id)
        pending_proposals = []
        if self.workspace_store is not None and hasattr(self.workspace_store, "list_proposals"):
            try:
                pending_proposals = self.workspace_store.list_proposals(project_id, status="pending")
            except Exception:
                pending_proposals = []
        window = build_current_execution_window(iteration, pending_proposals=pending_proposals)
        payload = dump_model(window)
        payload["artifact_json_path"] = self.artifacts.write_text(
            project_id,
            "control/current_execution_window.json",
            to_json_text(payload),
        )
        payload["artifact_markdown_path"] = self.artifacts.write_text(
            project_id,
            "control/current_execution_window.md",
            render_current_execution_window_markdown(window),
        )
        return payload

    def apply_quality_feedback_report(self, project_id: str, report: dict, *, trace_diagnostics: dict | None = None) -> dict:
        project = self.projects.get(project_id)
        project = self._ensure_base_context(project)
        project.template_tree = self._effective_template_tree(project)
        if project.template_tree is None or project.source_toc is None:
            raise ValueError("Project generation control context is incomplete.")
        base_plan = build_generation_control_plan(
            project_id=project.id,
            template_tree=project.template_tree,
            toc_items=project.source_toc.items,
        )
        feedback = build_quality_feedback_plan(report, current_plan=base_plan, trace_diagnostics=trace_diagnostics)
        next_plan = apply_quality_feedback_to_generation_plan(base_plan, feedback)
        paths = self._persist_quality_feedback(project.id, feedback, next_plan=next_plan, base_plan=base_plan)
        if self.workspace_store is not None:
            self.workspace_store.update_outline_word_counts(
                project.id,
                {
                    policy.node_id: policy.target_word_count
                    for policy in next_plan.chapter_policies
                    if policy.target_word_count is not None
                },
            )
        return {
            "project_id": project.id,
            "feedback": dump_model(feedback),
            "generation_control": dump_model(next_plan),
            "artifact_paths": paths,
        }

    def run_quality_audit(
        self,
        project_id: str,
        *,
        source_markdown: str | None = None,
        human_reference_markdown: str | None = None,
        apply_feedback: bool = False,
    ) -> dict:
        project = self.projects.get(project_id)
        project.template_tree = self._effective_template_tree(project)
        generated_markdown = self._current_generated_markdown(project)
        if not generated_markdown.strip():
            raise ValueError("No generated markdown is available. Generate at least one chapter or merge the project first.")
        source_text = source_markdown if source_markdown is not None else self._project_source_markdown(project)
        report = audit_generation_quality(
            QualityAuditInput(
                project_key=project.id,
                generated_markdown=generated_markdown,
                source_markdown=source_text,
                human_markdown=human_reference_markdown or "",
            )
        )
        artifact_paths = {
            "quality_audit_json": self.artifacts.write_text(project.id, "control/quality_audit_report.json", to_json_text(report)),
            "quality_audit_md": self.artifacts.write_text(project.id, "control/quality_audit_report.md", render_quality_audit_markdown(report)),
        }
        revision_targets = self.quality_audit_revision_targets(project.id, report=report)
        payload: dict = {
            "project_id": project.id,
            "report": report,
            "artifact_paths": artifact_paths,
            "revision_targets": revision_targets,
            "feedback": None,
        }
        if apply_feedback:
            payload["feedback"] = self.apply_quality_feedback_report(project.id, report)
        return payload

    def quality_audit_revision_targets(self, project_id: str, *, report: dict | None = None) -> dict:
        project = self.projects.get(project_id)
        report = report or self._load_quality_audit_report(project.id)
        if not report:
            raise ValueError("No quality audit report is available. Run /quality-audit first.")
        outline_nodes = self._quality_audit_outline_nodes(project)
        workspaces = self._quality_audit_workspaces(project.id, outline_nodes)
        source_items = project.source_toc.items if project.source_toc else []
        plan = build_quality_audit_revision_targets(
            project_id=project.id,
            report=report,
            outline_nodes=outline_nodes,
            workspaces=workspaces,
            source_toc_items=source_items,
        )
        payload = dump_model(plan)
        payload["artifact_json_path"] = self.artifacts.write_text(
            project.id,
            "control/quality_audit_revision_targets.json",
            to_json_text(payload),
        )
        payload["artifact_markdown_path"] = self.artifacts.write_text(
            project.id,
            "control/quality_audit_revision_targets.md",
            render_quality_audit_revision_targets(plan),
        )
        return payload

    def execute_quality_audit_revision_target(
        self,
        project_id: str,
        target_index: int,
        *,
        action: str | None = None,
    ) -> dict:
        plan = self.quality_audit_revision_targets(project_id)
        targets = plan.get("targets") or []
        if target_index < 0 or target_index >= len(targets):
            raise KeyError(f"Unknown quality audit revision target index: {target_index}")
        target = targets[target_index]
        return self._execute_quality_audit_target(project_id, target, target_index=target_index, action=action)

    def execute_quality_audit_revision_targets(
        self,
        project_id: str,
        *,
        include_user_confirmation: bool = False,
        limit: int = 10,
    ) -> dict:
        plan = self.quality_audit_revision_targets(project_id)
        results: list[dict] = []
        skipped: list[dict] = []
        failures: list[dict] = []
        for index, target in enumerate((plan.get("targets") or [])[: max(0, limit)]):
            if target.get("requires_user_confirmation") and not include_user_confirmation:
                skipped.append(
                    {
                        "target_index": index,
                        "target": target,
                        "reason": "Target requires user confirmation.",
                    }
                )
                continue
            try:
                results.append(self._execute_quality_audit_target(project_id, target, target_index=index))
            except Exception as exc:
                failures.append({"target_index": index, "target": target, "error": str(exc)})
        payload = {
            "project_id": project_id,
            "status": "failed" if failures and not results else ("partial_failed" if failures else "completed"),
            "executed": results,
            "skipped": skipped,
            "failed": failures,
            "source_plan": plan,
        }
        payload["artifact_json_path"] = self.artifacts.write_text(
            project_id,
            "control/quality_audit_revision_execution.json",
            to_json_text(payload),
        )
        return payload

    def run_quality_iteration(
        self,
        project_id: str,
        *,
        max_rounds: int = 1,
        include_user_confirmation: bool = False,
        limit_per_round: int = 10,
        source_markdown: str | None = None,
        human_reference_markdown: str | None = None,
    ) -> dict:
        rounds: list[dict] = []
        max_rounds = max(1, min(int(max_rounds or 1), 5))
        for round_no in range(1, max_rounds + 1):
            audit = self.run_quality_audit(
                project_id,
                source_markdown=source_markdown,
                human_reference_markdown=human_reference_markdown,
                apply_feedback=True,
            )
            execution = self.execute_quality_audit_revision_targets(
                project_id,
                include_user_confirmation=include_user_confirmation,
                limit=limit_per_round,
            )
            round_payload = {
                "round": round_no,
                "audit": audit,
                "execution": execution,
                "metrics": _quality_iteration_round_metrics(audit, execution),
            }
            rounds.append(round_payload)
            if not execution.get("executed") or execution.get("status") == "failed":
                break
        final_audit = self.run_quality_audit(
            project_id,
            source_markdown=source_markdown,
            human_reference_markdown=human_reference_markdown,
            apply_feedback=True,
        )
        payload = {
            "project_id": project_id,
            "status": _quality_iteration_status(rounds, final_audit),
            "round_count": len(rounds),
            "rounds": rounds,
            "final_audit": final_audit,
            "content_revision_targets": self._version_content_revision_targets(project_id),
            "generation_metadata_targets": self._version_generation_metadata_targets(project_id),
            "summary": _quality_iteration_summary(rounds, final_audit),
        }
        payload["artifact_json_path"] = self.artifacts.write_text(
            project_id,
            "control/quality_iteration.json",
            to_json_text(payload),
        )
        payload["artifact_markdown_path"] = self.artifacts.write_text(
            project_id,
            "control/quality_iteration.md",
            _render_quality_iteration_markdown(payload),
        )
        payload["learning_report"] = self.quality_iteration_learning_report(project_id, quality_iteration=payload)
        payload["artifact_json_path"] = self.artifacts.write_text(
            project_id,
            "control/quality_iteration.json",
            to_json_text(payload),
        )
        payload["artifact_markdown_path"] = self.artifacts.write_text(
            project_id,
            "control/quality_iteration.md",
            _render_quality_iteration_markdown(payload),
        )
        return payload

    def quality_iteration_learning_report(self, project_id: str, *, quality_iteration: dict | None = None) -> dict:
        project = self.projects.get(project_id)
        iteration = quality_iteration or self._load_quality_iteration(project.id)
        if not iteration:
            raise ValueError("No quality iteration is available. Run /quality-iteration first.")
        iteration_for_learning = dict(iteration)
        iteration_for_learning["content_revision_targets"] = _merge_learning_targets(
            iteration_for_learning.get("content_revision_targets"),
            self._version_content_revision_targets(project.id),
        )
        iteration_for_learning["generation_metadata_targets"] = _merge_learning_targets(
            iteration_for_learning.get("generation_metadata_targets"),
            self._version_generation_metadata_targets(project.id),
        )
        report = build_quality_iteration_learning_report(project_id=project.id, quality_iteration=iteration_for_learning)
        payload = dump_model(report)
        payload["artifact_json_path"] = self.artifacts.write_text(
            project.id,
            "control/quality_iteration_learning.json",
            to_json_text(payload),
        )
        payload["artifact_markdown_path"] = self.artifacts.write_text(
            project.id,
            "control/quality_iteration_learning.md",
            render_quality_iteration_learning_report(report),
        )
        return payload

    def propose_control_outline_repair(self, project_id: str) -> dict:
        if self.workspace_store is None:
            raise ValueError("Workspace store is not configured.")
        project = self.projects.get(project_id)
        project = self._ensure_base_context(project)
        project.template_tree = self._effective_template_tree(project)
        if project.template_tree is None or project.source_toc is None:
            raise ValueError("Project generation control context is incomplete.")
        plan = self._generation_control_plan(project)
        existing = self.workspace_store.list_outline_nodes(project.id)
        preview_nodes = build_outline_repair_proposal_nodes(
            plan=plan,
            toc_items=project.source_toc.items,
            existing_node_ids={item["node_id"] for item in existing},
            start_sort_order=(max([int(item.get("sort_order") or 0) for item in existing] or [0]) + 10),
        )
        if not preview_nodes:
            raise ValueError("控制计划未发现需要创建的目录缺口节点。")
        suggestion = "根据生成控制计划，将输入文档中已有但当前项目目录未承接的施组通用主题补充为可确认目录节点。"
        return self.workspace_store.propose_outline_change(project.id, suggestion, preview_nodes)

    def propose_pre_generation_outline_refine(
        self,
        project_id: str,
        *,
        mode: str = "balanced",
        use_local_corpus: bool = True,
        use_human_reference: bool = False,
        human_reference_markdown: str | None = None,
        project_type: str = "auto",
    ) -> dict:
        if self.workspace_store is None:
            raise ValueError("Workspace store is not configured.")
        project = self.prepare_directory(project_id)
        project.template_tree = self._effective_template_tree(project)
        if project.template_tree is None or project.source_toc is None:
            raise ValueError("Project generation context is incomplete.")
        outline_nodes = self.workspace_store.list_outline_nodes(project.id)
        refined = build_pre_generation_outline_refine(
            template_tree=project.template_tree,
            current_outline_nodes=outline_nodes,
            toc_items=project.source_toc.items,
            mode=mode,
            project_type=project_type,
            use_local_corpus=use_local_corpus,
            use_human_reference=use_human_reference,
            human_reference_markdown=human_reference_markdown,
        )
        preview_nodes = refined["preview_nodes"]
        if not preview_nodes:
            raise ValueError("No pre-generation outline refinement nodes were found.")
        payload = {
            "project_id": project.id,
            "summary": refined["summary"],
            "preview_nodes": preview_nodes,
        }
        artifact_json_path = self.artifacts.write_text(
            project.id,
            "control/pre_generation_outline_refine.json",
            to_json_text(payload),
        )
        artifact_markdown_path = self.artifacts.write_text(
            project.id,
            "control/pre_generation_outline_refine.md",
            refined["markdown"],
        )
        suggestion = (
            "生成前目录精修建议：先按本地施组目录结构与煤火核心工艺规则扩细目录。"
            "应用后仅叶子节点进入来源映射和逐章生成；参考目录只作结构指导，不作项目事实来源。"
        )
        proposal = self.workspace_store.propose_outline_change(project.id, suggestion, preview_nodes)
        proposal["kind"] = "outline_proposal"
        proposal["refine_summary"] = refined["summary"]
        proposal["artifact_json_path"] = artifact_json_path
        proposal["artifact_markdown_path"] = artifact_markdown_path
        return proposal

    def propose_quality_feedback_outline_repair(self, project_id: str) -> dict:
        if self.workspace_store is None:
            raise ValueError("Workspace store is not configured.")
        project = self.projects.get(project_id)
        feedback = self._load_quality_feedback(project.id)
        if feedback is None:
            raise ValueError("No quality feedback plan is available. Apply a quality audit report first.")
        existing = self.workspace_store.list_outline_nodes(project.id)
        preview_nodes = build_quality_outline_repair_proposal_nodes(
            feedback_plan=feedback,
            existing_node_ids={item["node_id"] for item in existing},
            existing_titles={item["title"] for item in existing},
            start_sort_order=(max([int(item.get("sort_order") or 0) for item in existing] or [0]) + 10),
        )
        if not preview_nodes:
            raise ValueError("Quality feedback did not contain missing headings that can be converted into outline proposal nodes.")
        suggestion = "Create editable outline nodes from quality-audit heading gaps found in human-written reference documents."
        return self.workspace_store.propose_outline_change(project.id, suggestion, preview_nodes)

    def propose_subsection_expansion(self, project_id: str, node_id: str) -> dict:
        if self.workspace_store is None:
            raise ValueError("Workspace store is not configured.")
        project = self.projects.get(project_id)
        project = self._ensure_base_context(project)
        project.template_tree = self._effective_template_tree(project)
        if project.template_tree is None or project.source_toc is None:
            raise ValueError("Project generation control context is incomplete.")
        node = _find_node(project.template_tree.nodes, node_id)
        if node is None:
            raise KeyError(f"Unknown node_id: {node_id}")
        plan = self._generation_control_plan(project)
        outline_nodes = self.workspace_store.list_outline_nodes(project.id)
        existing_children = [item for item in outline_nodes if item.get("parent_id") == node_id]
        preview_nodes = build_subsection_proposal_nodes(
            plan=plan,
            parent_node=node,
            existing_child_titles={item["title"] for item in existing_children},
            start_sort_order=(max([int(item.get("sort_order") or 0) for item in existing_children] or [0]) + 10),
        )
        if not preview_nodes:
            raise ValueError("当前章节未达到拆小节条件，或已存在对应子节点。")
        suggestion = f"根据生成控制计划，将“{node.title}”拆分为可逐小节映射来源和生成正文的子章节。"
        return self.workspace_store.propose_outline_change(project.id, suggestion, preview_nodes)

    def propose_generation_metadata_subsection_expansion(self, project_id: str, node_id: str, audit: dict) -> dict:
        if self.workspace_store is None:
            raise ValueError("Workspace store is not configured.")
        project = self.projects.get(project_id)
        project = self._ensure_base_context(project)
        project.template_tree = self._effective_template_tree(project)
        if project.template_tree is None or project.source_toc is None:
            raise ValueError("Project generation control context is incomplete.")
        node = _find_node(project.template_tree.nodes, node_id)
        if node is None:
            raise KeyError(f"Unknown node_id: {node_id}")
        plan = self._generation_control_plan(project)
        outline_nodes = self.workspace_store.list_outline_nodes(project.id)
        existing_children = [item for item in outline_nodes if item.get("parent_id") == node_id]
        existing_titles = {item["title"] for item in existing_children if item.get("title")}
        start_sort_order = max([int(item.get("sort_order") or 0) for item in existing_children] or [0]) + 10
        preview_nodes = build_subsection_proposal_nodes(
            plan=plan,
            parent_node=node,
            existing_child_titles=existing_titles,
            start_sort_order=start_sort_order,
        )
        next_order = max([int(item.get("sort_order") or 0) for item in [*existing_children, *preview_nodes]] or [start_sort_order - 10]) + 10
        cue_nodes = _generation_metadata_cue_subsection_nodes(
            parent_node=node,
            audit=audit,
            existing_titles={*[item.get("title") for item in preview_nodes if item.get("title")], *existing_titles},
            start_sort_order=next_order,
        )
        preview_nodes.extend(cue_nodes)
        if not preview_nodes:
            raise ValueError("Generation metadata audit did not produce source-derived or cue-derived subsection proposal nodes.")
        audit_notes = [str(issue) for issue in (audit.get("issues") or [])[:3] if str(issue).strip()]
        for item in preview_nodes:
            _append_unique(
                item.setdefault("source_rules", []),
                [
                    "Generation metadata audit requested subsection expansion before another factual generation pass.",
                    *audit_notes,
                ],
            )
            _append_unique(
                item.setdefault("special_notes", []),
                [
                    "Local corpus writing cues are structural guidance only; generated facts still require mapped section_id/evidence_id, user supplements, or manual placeholders.",
                ],
            )
        suggestion = (
            "Split this chapter according to generation-metadata audit gaps. The preview nodes carry missing local writing-pattern cues; "
            "after confirmation each child must enter normal source mapping, evidence extraction, generation, validation, versioning, and merge gates."
        )
        return self.workspace_store.propose_outline_change(project.id, suggestion, preview_nodes)

    def propose_project_subsection_expansions(self, project_id: str) -> dict:
        if self.workspace_store is None:
            raise ValueError("Workspace store is not configured.")
        project = self.projects.get(project_id)
        project = self._ensure_base_context(project)
        project.template_tree = self._effective_template_tree(project)
        if project.template_tree is None or project.source_toc is None:
            raise ValueError("Project generation control context is incomplete.")
        plan = self._generation_control_plan(project)
        outline_nodes = self.workspace_store.list_outline_nodes(project.id)
        preview_nodes = build_project_subsection_proposal_nodes(
            plan=plan,
            template_tree=project.template_tree,
            existing_outline_nodes=outline_nodes,
        )
        if not preview_nodes:
            raise ValueError("当前项目未发现需要批量拆分的小节，或对应子节点已存在。")
        suggestion = "根据生成控制计划，批量拆分所有高信息密度章节，使其可逐小节映射来源、控制详略并生成正文。"
        return self.workspace_store.propose_outline_change(project.id, suggestion, preview_nodes)

    def execute_revision_action(self, project_id: str, node_id: str, action: str | None = None) -> dict:
        project = self.projects.get(project_id)
        if not project.runs:
            raise KeyError("Project has no generation run.")
        project = self._ensure_generation_context(project)
        project.template_tree = self._effective_template_tree(project)
        if project.template_tree is None:
            raise ValueError("Project template tree is not loaded.")
        control_plan = self._generation_control_plan(project)
        drafts = self._revision_decision_drafts(project)
        decisions = build_revision_decisions(
            run=project.runs[-1],
            drafts=drafts,
            template_tree=project.template_tree,
            policies=control_plan.chapter_policies,
        )
        decision = next((item for item in decisions if item.node_id == node_id), None)
        if decision is None:
            raise KeyError(f"Unknown node_id: {node_id}")
        selected_action = action or decision.decision
        if selected_action == "expand_subsections":
            return {
                "kind": "outline_proposal",
                "action": selected_action,
                "decision": dump_model(decision),
                "proposal": self.propose_subsection_expansion(project_id, node_id),
            }
        if selected_action in {"regenerate", "remap_sources", "repair_format"}:
            draft = self.generate_one(project_id, node_id, revision_context=_render_revision_context(decision))
            return {
                "kind": "chapter_version",
                "action": selected_action,
                "decision": dump_model(decision),
                "draft": dump_model(draft),
            }
        if selected_action == "request_human_input":
            return {
                "kind": "human_input_required",
                "action": selected_action,
                "decision": dump_model(decision),
                "message": "请先在章节工作区补充来源、图纸、参数、现场说明或人工要求，再重新生成。",
            }
        if selected_action == "accept":
            return {
                "kind": "accepted",
                "action": selected_action,
                "decision": dump_model(decision),
                "message": "当前章节无需自动修订。",
            }
        raise ValueError(f"Unsupported revision action: {selected_action}")

    def execute_generation_metadata_revision_action(
        self,
        project_id: str,
        node_id: str,
        version_id: str,
        action: str | None = None,
    ) -> dict:
        if self.workspace_store is None:
            raise ValueError("Workspace store is not configured.")
        project = self.projects.get(project_id)
        project = self._ensure_generation_context(project)
        project.template_tree = self._effective_template_tree(project)
        version = self.workspace_store.get_version(project_id, node_id, version_id)
        audit = audit_version_generation_metadata(version)
        selected_action = action or _generation_metadata_revision_action(audit)

        if selected_action == "accept":
            return {
                "kind": "accepted",
                "action": selected_action,
                "node_id": node_id,
                "version_id": version_id,
                "audit": audit,
                "message": "Current version generation metadata is acceptable; no automatic revision is required.",
            }
        if selected_action == "request_human_input":
            return {
                "kind": "human_input_required",
                "action": selected_action,
                "node_id": node_id,
                "version_id": version_id,
                "audit": audit,
                "message": "Add chapter supplements, attachment notes, tables, drawings, approvals, parameters, or site measurements before regenerating.",
            }
        if selected_action == "expand_subsections":
            try:
                proposal = self.propose_generation_metadata_subsection_expansion(project_id, node_id, audit)
            except Exception as exc:
                return {
                    "kind": "human_input_required",
                    "action": selected_action,
                    "node_id": node_id,
                    "version_id": version_id,
                    "audit": audit,
                    "message": (
                        "Generation metadata requires subsection expansion, but no automatic outline proposal was available. "
                        f"Please adjust the outline manually or add supplements before regenerating. Detail: {exc}"
                    ),
                }
            return {
                "kind": "outline_proposal",
                "action": selected_action,
                "node_id": node_id,
                "version_id": version_id,
                "audit": audit,
                "proposal": proposal,
            }
        if selected_action == "repair_outline_coverage":
            try:
                proposal = self.propose_subsection_expansion(project_id, node_id)
            except Exception:
                try:
                    proposal = self.propose_control_outline_repair(project_id)
                except Exception:
                    return {
                        "kind": "human_input_required",
                        "action": selected_action,
                        "node_id": node_id,
                        "version_id": version_id,
                        "audit": audit,
                        "message": "Outline coverage needs repair, but no automatic proposal was available. Please adjust the outline or add source-backed supplements.",
                    }
            return {
                "kind": "outline_proposal",
                "action": selected_action,
                "node_id": node_id,
                "version_id": version_id,
                "audit": audit,
                "proposal": proposal,
            }
        if selected_action == "regenerate":
            draft = self.generate_one(
                project_id,
                node_id,
                revision_context=_render_generation_metadata_revision_context(audit),
            )
            return {
                "kind": "chapter_version",
                "action": selected_action,
                "node_id": node_id,
                "version_id": version_id,
                "audit": audit,
                "draft": dump_model(draft),
            }
        raise ValueError(f"Unsupported generation metadata revision action: {selected_action}")

    def execute_evidence_utilization_revision_action(
        self,
        project_id: str,
        node_id: str,
        version_id: str,
        action: str | None = None,
    ) -> dict:
        if self.workspace_store is None:
            raise ValueError("Workspace store is not configured.")
        project = self.projects.get(project_id)
        project = self._ensure_generation_context(project)
        project.template_tree = self._effective_template_tree(project)
        version = self.workspace_store.get_version(project_id, node_id, version_id)
        audit = version.get("evidence_audit")
        selected_action = action or _evidence_utilization_revision_action(audit)

        if selected_action == "accept":
            return {
                "kind": "accepted",
                "action": selected_action,
                "node_id": node_id,
                "version_id": version_id,
                "audit": audit,
                "message": "Current version evidence utilization is acceptable; no automatic revision is required.",
            }
        if selected_action == "request_human_input":
            return {
                "kind": "human_input_required",
                "action": selected_action,
                "node_id": node_id,
                "version_id": version_id,
                "audit": audit,
                "message": "Add missing source sections, drawings, approved parameters, site measurements, or chapter supplements before regenerating.",
            }
        if selected_action in {"regenerate", "remap_sources", "repair_format"}:
            draft = self.generate_one(
                project_id,
                node_id,
                revision_context=_render_evidence_utilization_revision_context(audit, selected_action=selected_action),
            )
            return {
                "kind": "chapter_version",
                "action": selected_action,
                "node_id": node_id,
                "version_id": version_id,
                "audit": audit,
                "draft": dump_model(draft),
            }
        raise ValueError(f"Unsupported evidence utilization revision action: {selected_action}")

    def execute_content_revision_action(
        self,
        project_id: str,
        node_id: str,
        version_id: str,
        content_node_id: str,
        action: str | None = None,
    ) -> dict:
        if self.workspace_store is None:
            raise ValueError("Workspace store is not configured.")
        project = self.projects.get(project_id)
        project = self._ensure_base_context(project)
        project.template_tree = self._effective_template_tree(project)
        version = self.workspace_store.get_version(project_id, node_id, version_id)
        tree = version.get("content_tree") or self.workspace_store.get_version_content_tree(project_id, node_id, version_id)
        plan_payload = version.get("content_revision_plan") or dump_model(build_content_revision_plan(tree))
        content_node = _find_content_node((tree or {}).get("nodes") or [], content_node_id)
        if content_node is None:
            raise KeyError(f"Unknown content_node_id: {content_node_id}")
        item = _content_revision_item(plan_payload, content_node_id)
        selected_action = action or (item or {}).get("action") or "accept"
        if selected_action == "accept":
            return {
                "kind": "content_revision_accepted",
                "action": selected_action,
                "node_id": node_id,
                "version_id": version_id,
                "content_node_id": content_node_id,
                "revision_item": item,
            }
        if selected_action == "request_human_input":
            return {
                "kind": "human_input_required",
                "action": selected_action,
                "node_id": node_id,
                "version_id": version_id,
                "content_node_id": content_node_id,
                "revision_item": item,
                "message": "This generated subsection needs user-supplied source text, table data, attachment notes, drawings, approvals, or site measurements before factual regeneration.",
            }
        if selected_action == "split_subsection":
            proposal_nodes = _content_split_proposal_nodes(
                project_id=project_id,
                node_id=node_id,
                content_node=content_node,
                item=item,
                workspace=self.workspace_store.get_workspace(project_id, node_id),
            )
            proposal = self.workspace_store.propose_outline_change(
                project_id,
                (
                    "根据已生成正文小节的修订计划，将过密小节拆分为可确认的目录子节点。"
                    "应用后，这些子节点会进入现有逐节点来源映射、证据抽取、生成和版本管理流程。"
                ),
                proposal_nodes,
            )
            return {
                "kind": "outline_proposal",
                "action": selected_action,
                "node_id": node_id,
                "version_id": version_id,
                "content_node_id": content_node_id,
                "revision_item": item,
                "proposal": proposal,
                "suggested_titles": [node["title"] for node in proposal_nodes],
                "message": "已根据正文小节生成目录拆分 proposal；确认应用后再逐子节点映射来源并生成。",
            }
        if selected_action not in {"remap_sources", "review_source_link", "rewrite_subsection"}:
            raise ValueError(f"Unsupported content revision action: {selected_action}")

        source_sections = _content_revision_source_sections(project.sections, content_node, item, self.retriever)
        required_facts = _content_revision_required_facts(item or {})
        prompt = _build_content_revision_prompt(
            project=project,
            node_id=node_id,
            version=version,
            content_node=content_node,
            revision_item=item or {},
            action=selected_action,
            source_sections=source_sections,
            user_context=self._chapter_user_context(project_id, node_id),
            required_facts=required_facts,
        )
        replacement = self.llm.complete(prompt)
        trace_path = self.artifacts.write_text(
            project_id,
            f"chapters/{node_id}/versions/{version_id}.{content_node_id}.content_revision_trace.json",
            to_json_text(
                {
                    "project_id": project_id,
                    "node_id": node_id,
                    "version_id": version_id,
                    "content_node_id": content_node_id,
                    "action": selected_action,
                    "revision_item": item,
                    "required_facts": required_facts,
                    "selected_source_section_ids": [section.id for section in source_sections],
                    "prompt": prompt,
                    "response": replacement,
                }
            ),
        )
        new_version = self.workspace_store.update_version_content_node(
            project_id,
            node_id,
            version_id,
            content_node_id,
            replacement,
            select=True,
            generation_metadata=_content_revision_generation_metadata(
                version.get("generation_metadata"),
                action=selected_action,
                content_node_id=content_node_id,
                trace_path=trace_path,
                required_facts=required_facts,
            ),
            evidence_audit=version.get("evidence_audit"),
        )
        revision_plan = build_content_revision_plan(new_version["content_tree"])
        self.artifacts.write_text(
            project_id,
            f"chapters/{node_id}/versions/{new_version['id']}.content_revision_plan.md",
            render_content_revision_plan_markdown(revision_plan),
        )
        return {
            "kind": "content_revision_version",
            "action": selected_action,
            "node_id": node_id,
            "old_version_id": version_id,
            "new_version_id": new_version["id"],
            "content_node_id": content_node_id,
            "trace_path": trace_path,
            "selected_source_section_ids": [section.id for section in source_sections],
            "version": new_version,
        }

    def prepare_run(self, project_id: str) -> GenerationRun:
        project = self.projects.get(project_id)
        project = self._ensure_generation_context(project)
        project.template_tree = self._effective_template_tree(project)
        if project.template_tree is None:
            raise ValueError("Project template tree is not loaded.")
        if project.runs:
            run = project.runs[-1]
            self._sync_run_tasks(project, run)
        else:
            run = GenerationRun(project_name=project.name, template_id=project.template_id)
            self._sync_run_tasks(project, run)
            run.logs.append("Prepared source toc, project profile, and template outline plan.")
            project.runs.append(run)
        self.projects.save(project)
        return run

    def sync_generation_tasks(self, project_id: str) -> GenerationRun | None:
        project = self.projects.get(project_id)
        project = self._ensure_generation_context(project)
        project.template_tree = self._effective_template_tree(project)
        if project.template_tree is None:
            raise ValueError("Project template tree is not loaded.")
        if not project.runs:
            return self.prepare_run(project_id)
        run = project.runs[-1]
        self._sync_run_tasks(project, run)
        self.projects.save(project)
        return run

    def generate_all(self, project_id: str) -> GenerationRun:
        project = self.projects.get(project_id)
        run = project.runs[-1] if project.runs else self.prepare_run(project_id)
        project = self.projects.get(project_id)
        project = self._ensure_generation_context(project)
        project.template_tree = self._effective_template_tree(project)
        run = project.runs[-1] if project.runs else run
        if project.template_tree is None or project.project_profile is None or project.source_toc is None:
            raise ValueError("Project generation context is incomplete.")
        self._sync_run_tasks(project, run)
        nodes_by_id = {node.id: node for node in iter_template_nodes(project.template_tree.nodes)}
        control_plan = self._generation_control_plan(project)
        policy_by_node = {policy.node_id: policy for policy in control_plan.chapter_policies}
        run.status = RunStatus.running
        drafts: list[ChapterDraft] = []
        for task in run.chapter_tasks:
            try:
                node = nodes_by_id[task.node_id]
                task.target_word_count = node.target_word_count
                policy = policy_by_node.get(node.id)
                mapping, selected_sections, source_matches = map_chapter_sources(
                    project_id=project.id,
                    profile=project.project_profile,
                    toc_items=project.source_toc.items,
                    sections=project.sections,
                    node=node,
                    llm=self._structured_llm(),
                    artifacts=self.artifacts,
                    max_matches=policy.max_source_matches if policy else 8,
                    max_evidence_spans=policy.max_evidence_spans if policy else 14,
                    mapping_context=_join_context(
                        _mapping_control_context(policy),
                        self._quality_feedback_mapping_context(project.id),
                    ),
                )
                task.source_mapping = mapping
                task.source_matches = source_matches
                required_fact_hints = self._quality_feedback_required_facts(project.id, task, selected_sections)
                if _should_skip_no_source(policy, mapping):
                    draft = _no_source_draft(project.id, node, task, self.artifacts)
                    self._record_chapter_version(project.id, node.id, draft, "ai_placeholder")
                    drafts.append(draft)
                    run.logs.append(f"{task.status.value}: {task.title}")
                    continue
                draft = generate_chapter(
                    project_id=project.id,
                    node=node,
                    task=task,
                    llm=self.llm,
                    artifacts=self.artifacts,
                    project_profile=project.project_profile,
                    selected_source_sections=selected_sections,
                    user_context=_join_context(
                        self._chapter_user_context(project.id, node.id),
                        self._quality_feedback_context(project.id),
                    ),
                    required_fact_hints=required_fact_hints,
                    generation_policy=policy,
                )
                self._record_chapter_version(project.id, node.id, draft, "ai_generate")
                drafts.append(draft)
            except Exception as exc:
                task.status = TaskStatus.failed
                task.error_message = str(exc)
            run.logs.append(f"{task.status.value}: {task.title}")
        self._drafts[run.id] = drafts
        run.status = RunStatus.completed if all(task.status.value == "passed" for task in run.chapter_tasks) else RunStatus.partial_failed
        self._persist_validation(project.id, run, drafts=drafts, template_tree=project.template_tree, control_plan=control_plan)
        self.projects.save(project)
        return run

    def generate_one(self, project_id: str, node_id: str, *, revision_context: str = "") -> ChapterDraft:
        project = self.projects.get(project_id)
        run = project.runs[-1] if project.runs else self.prepare_run(project_id)
        project = self.projects.get(project_id)
        project = self._ensure_generation_context(project)
        project.template_tree = self._effective_template_tree(project)
        run = project.runs[-1] if project.runs else run
        if project.template_tree is None or project.project_profile is None or project.source_toc is None:
            raise ValueError("Project generation context is incomplete.")
        self._sync_run_tasks(project, run)
        node = _find_node(project.template_tree.nodes, node_id)
        if node is None:
            raise KeyError(f"Unknown node_id: {node_id}")
        task = next((item for item in run.chapter_tasks if item.node_id == node_id), None)
        if task is None:
            task = ChapterTask(node_id=node.id, title=node.title, target_word_count=node.target_word_count, source_matches=self.retriever.retrieve(node, project.sections, limit=4))
            run.chapter_tasks.append(task)
        else:
            task.target_word_count = node.target_word_count
        control_plan = self._generation_control_plan(project)
        policy_by_node = {policy.node_id: policy for policy in control_plan.chapter_policies}
        policy = policy_by_node.get(node.id)
        mapping, selected_sections, source_matches = map_chapter_sources(
            project_id=project.id,
            profile=project.project_profile,
            toc_items=project.source_toc.items,
            sections=project.sections,
            node=node,
            llm=self._structured_llm(),
            artifacts=self.artifacts,
            max_matches=policy.max_source_matches if policy else 8,
            max_evidence_spans=policy.max_evidence_spans if policy else 14,
            mapping_context=_join_context(
                _mapping_control_context(policy),
                self._quality_feedback_mapping_context(project.id),
                revision_context,
            ),
        )
        task.source_mapping = mapping
        task.source_matches = source_matches
        revision_source_text = _selected_source_text(task, selected_sections)
        quality_required_facts = _filter_required_fact_hints_by_source(
            self._quality_feedback_required_facts(project.id, task, selected_sections),
            revision_source_text,
        )
        required_fact_hints = _merge_required_fact_hints(
            quality_required_facts,
            _revision_context_required_fact_hints(revision_context, source_text=revision_source_text),
        )
        if _should_skip_no_source(policy, mapping):
            draft = _no_source_draft(project.id, node, task, self.artifacts)
            self._record_chapter_version(project.id, node.id, draft, "ai_placeholder")
            self._drafts.setdefault(run.id, []).append(draft)
            control_plan = self._generation_control_plan(project)
            self._persist_validation(project.id, run, drafts=self._drafts.get(run.id, []), template_tree=project.template_tree, control_plan=control_plan)
            self.projects.save(project)
            return draft
        draft = generate_chapter(
            project_id=project.id,
            node=node,
            task=task,
            llm=self.llm,
            artifacts=self.artifacts,
            project_profile=project.project_profile,
            selected_source_sections=selected_sections,
            user_context=_join_context(
                self._chapter_user_context(project.id, node.id),
                self._quality_feedback_context(project.id),
                revision_context,
            ),
            required_fact_hints=required_fact_hints,
            generation_policy=policy,
        )
        self._record_chapter_version(project.id, node.id, draft, "ai_generate")
        self._drafts.setdefault(run.id, []).append(draft)
        control_plan = self._generation_control_plan(project)
        self._persist_validation(project.id, run, drafts=self._drafts.get(run.id, []), template_tree=project.template_tree, control_plan=control_plan)
        self.projects.save(project)
        return draft

    def generate_child_chapters(
        self,
        project_id: str,
        parent_node_id: str,
        *,
        recursive: bool = False,
        only_pending: bool = False,
        limit: int | None = None,
    ) -> dict:
        project = self.prepare_directory(project_id)
        project = self.projects.get(project_id)
        project = self._ensure_generation_context(project)
        project.template_tree = self._effective_template_tree(project)
        run = project.runs[-1] if project.runs else self.prepare_run(project_id)
        if project.template_tree is None:
            raise ValueError("Project template tree is not loaded.")
        parent = _find_node(project.template_tree.nodes, parent_node_id)
        if parent is None:
            raise KeyError(f"Unknown parent_node_id: {parent_node_id}")
        self._sync_run_tasks(project, run)
        task_by_node = {task.node_id: task for task in run.chapter_tasks}
        candidates = [
            node
            for node in _child_generation_nodes(parent, recursive=recursive)
            if node.id in task_by_node and node.has_generation_contract
        ]
        if only_pending:
            candidates = [
                node
                for node in candidates
                if task_by_node[node.id].status.value in {"pending", "failed", "needs_repair", "running"}
                or not task_by_node[node.id].draft_id
            ]
        if limit is not None:
            candidates = candidates[: max(0, int(limit))]
        generated: list[dict] = []
        failed: list[dict] = []
        skipped: list[dict] = []
        if not candidates:
            skipped.append({"parent_node_id": parent_node_id, "reason": "No child generation tasks matched the requested filters."})
        for node in candidates:
            try:
                draft = self.generate_one(project_id, node.id)
                selected_version_id = _workspace_selected_version_id(self.workspace_store, project_id, node.id)
                if not selected_version_id:
                    failed.append(
                        {
                            "node_id": node.id,
                            "title": node.title,
                            "draft_id": draft.id,
                            "status": draft.validation_status.value,
                            "artifact_path": draft.artifact_path,
                            "error": _draft_error_message(draft, task_by_node.get(node.id))
                            or "Generated draft did not create a selectable chapter version.",
                            "next_action": "regenerate",
                            "endpoint": f"/projects/{project_id}/chapters/{node.id}/revision-action",
                        }
                    )
                    continue
                generated.append(
                    {
                        "node_id": node.id,
                        "title": node.title,
                        "draft_id": draft.id,
                        "status": draft.validation_status.value,
                        "artifact_path": draft.artifact_path,
                        "selected_version_id": selected_version_id,
                    }
                )
            except Exception as exc:
                failed.append(
                    {
                        "node_id": node.id,
                        "title": node.title,
                        "error": str(exc),
                        "next_action": "regenerate",
                        "endpoint": f"/projects/{project_id}/chapters/{node.id}/revision-action",
                    }
                )
        project = self.projects.get(project_id)
        run = project.runs[-1] if project.runs else run
        payload = {
            "project_id": project_id,
            "parent_node_id": parent_node_id,
            "recursive": recursive,
            "only_pending": only_pending,
            "candidate_count": len(candidates),
            "status": "failed" if failed and not generated else ("partial_failed" if failed else "completed"),
            "generated": generated,
            "skipped": skipped,
            "failed": failed,
            "run_id": run.id if run else None,
        }
        payload["artifact_json_path"] = self.artifacts.write_text(
            project_id,
            f"control/child_generation_{_safe_artifact_name(parent_node_id)}.json",
            to_json_text(payload),
        )
        return payload

    def merge_latest(self, project_id: str) -> GenerationRun:
        project = self.projects.get(project_id)
        if not project.runs:
            raise KeyError("Project has no generation run.")
        if project.template_tree is None:
            raise ValueError("Project template tree is not loaded.")
        project.template_tree = self._effective_template_tree(project)
        run = project.runs[-1]
        self._sync_run_tasks(project, run)
        drafts = self._selected_version_drafts(project)
        if not drafts:
            drafts = self._drafts.get(run.id)
        if drafts is None:
            drafts = _load_drafts_from_tasks(project.id, run, self.artifacts)
        run = merge_chapters(
            project_id=project.id,
            run=run,
            drafts=drafts,
            template_tree=project.template_tree,
            title=f"{project.name}施工组织设计",
            artifacts=self.artifacts,
        )
        self.projects.save(project)
        return run

    def _sync_run_tasks(self, project: Project, run: GenerationRun) -> None:
        if project.template_tree is None:
            raise ValueError("Project template tree is not loaded.")
        desired_tasks = build_chapter_tasks(project.template_tree, project.sections, self.retriever)
        desired_by_id = {task.node_id: task for task in desired_tasks}
        existing_by_id = {task.node_id: task for task in run.chapter_tasks}
        synced: list[ChapterTask] = []
        added = 0
        removed = 0
        marked_stale = 0
        for desired in desired_tasks:
            existing = existing_by_id.get(desired.node_id)
            if existing is None:
                synced.append(desired)
                added += 1
                continue
            title_changed = existing.title != desired.title
            target_changed = existing.target_word_count != desired.target_word_count
            if (title_changed or target_changed) and existing.draft_id:
                existing.status = TaskStatus.needs_repair
                existing.error_message = "Outline node changed after generation; regenerate this chapter or select a newer version before merge."
                marked_stale += 1
            existing.title = desired.title
            existing.target_word_count = desired.target_word_count
            if existing.source_mapping is None:
                existing.source_matches = desired.source_matches
            synced.append(existing)
        removed = len([task for task in run.chapter_tasks if task.node_id not in desired_by_id])
        run.chapter_tasks = synced
        if added or removed or marked_stale:
            run.logs.append(
                f"Synced chapter tasks with editable outline: +{added}, -{removed}, stale={marked_stale}, total={len(run.chapter_tasks)}."
            )
        elif not run.chapter_tasks:
            run.logs.append("Synced chapter tasks with editable outline: total=0.")

    def _ensure_generation_context(self, project: Project) -> Project:
        project = self._ensure_base_context(project)
        if project.outline_plan is None:
            project.outline_plan = plan_template_outline(
                project_id=project.id,
                profile=project.project_profile,
                toc_items=project.source_toc.items,
                template_tree=project.template_tree,
                llm=self._structured_llm(),
                artifacts=self.artifacts,
            )
        project.template_tree = apply_outline_to_template_tree(project.template_tree, project.outline_plan)
        self._generation_control_plan(project)
        return self.projects.save(project)

    def _ensure_base_context(self, project: Project) -> Project:
        if project.template_tree is None:
            project = load_template_tree(project, template_id=project.template_id, loader=self.templates)
        if not project.sections:
            raise ValueError("No bid markdown sections are available. Upload and normalize a bid markdown file before generation.")
        if project.source_toc is None:
            project.source_toc = persist_source_index(project.id, project.sections, self.artifacts)
        if project.project_profile is None:
            project.project_profile = generate_project_profile(
                project_id=project.id,
                toc_items=project.source_toc.items,
                sections=project.sections,
                llm=self._structured_llm(),
                artifacts=self.artifacts,
            )
        return self.projects.save(project)

    def _effective_template_tree(self, project: Project) -> TemplateTree | None:
        if self.workspace_store is None or project.template_tree is None:
            return project.template_tree
        try:
            nodes = self.workspace_store.outline_tree(project.id)
            if nodes:
                return TemplateTree(id=project.template_tree.id, name=project.template_tree.name, nodes=nodes)
        except Exception:
            return project.template_tree
        return project.template_tree

    def _structured_llm(self) -> StructuredLLMClient:
        if self.structured_llm is not None:
            return self.structured_llm
        if not hasattr(self.llm, "complete_json"):
            raise TypeError("Configured LLM client must implement complete_json for structured generation stages.")
        return self.llm  # type: ignore[return-value]

    def _generation_control_plan(self, project: Project) -> GenerationControlPlan:
        if project.template_tree is None or project.source_toc is None:
            raise ValueError("Project generation control context is incomplete.")
        base_plan = build_generation_control_plan(
            project_id=project.id,
            template_tree=project.template_tree,
            toc_items=project.source_toc.items,
        )
        feedback = self._load_quality_feedback(project.id)
        plan = apply_quality_feedback_to_generation_plan(base_plan, feedback) if feedback else base_plan
        if feedback:
            self.artifacts.write_text(project.id, "control/base_generation_control_plan.json", to_json_text(dump_model(base_plan)))
            self.artifacts.write_text(project.id, "control/base_generation_control_plan.md", render_generation_control_plan(base_plan))
        self.artifacts.write_text(project.id, "control/generation_control_plan.json", to_json_text(dump_model(plan)))
        self.artifacts.write_text(project.id, "control/generation_control_plan.md", render_generation_control_plan(plan))
        return plan

    def _persist_quality_feedback(
        self,
        project_id: str,
        feedback: QualityFeedbackPlan,
        *,
        next_plan: GenerationControlPlan | None = None,
        base_plan: GenerationControlPlan | None = None,
    ) -> dict:
        paths = {
            "quality_feedback_json": self.artifacts.write_text(project_id, "control/quality_feedback_plan.json", to_json_text(dump_model(feedback))),
            "quality_feedback_md": self.artifacts.write_text(project_id, "control/quality_feedback_plan.md", render_quality_feedback_plan(feedback)),
        }
        if base_plan is not None:
            paths["base_generation_control_json"] = self.artifacts.write_text(project_id, "control/base_generation_control_plan.json", to_json_text(dump_model(base_plan)))
            paths["base_generation_control_md"] = self.artifacts.write_text(project_id, "control/base_generation_control_plan.md", render_generation_control_plan(base_plan))
        if next_plan is not None:
            paths["generation_control_json"] = self.artifacts.write_text(project_id, "control/generation_control_plan.json", to_json_text(dump_model(next_plan)))
            paths["generation_control_md"] = self.artifacts.write_text(project_id, "control/generation_control_plan.md", render_generation_control_plan(next_plan))
        return paths

    def _load_quality_feedback(self, project_id: str) -> QualityFeedbackPlan | None:
        root = getattr(self.artifacts, "root", None)
        if root is None:
            return None
        path = Path(root) / project_id / "control" / "quality_feedback_plan.json"
        if not path.exists():
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8-sig"))
            if hasattr(QualityFeedbackPlan, "model_validate"):
                return QualityFeedbackPlan.model_validate(payload)
            return QualityFeedbackPlan.parse_obj(payload)
        except Exception:
            return None

    def _load_quality_audit_report(self, project_id: str) -> dict | None:
        root = getattr(self.artifacts, "root", None)
        if root is None:
            return None
        path = Path(root) / project_id / "control" / "quality_audit_report.json"
        if not path.exists():
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8-sig"))
            return payload if isinstance(payload, dict) else None
        except Exception:
            return None

    def _load_quality_iteration(self, project_id: str) -> dict | None:
        root = getattr(self.artifacts, "root", None)
        if root is None:
            return None
        path = Path(root) / project_id / "control" / "quality_iteration.json"
        if not path.exists():
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8-sig"))
            return payload if isinstance(payload, dict) else None
        except Exception:
            return None

    def _targeted_revision_summary(self, project: Project) -> dict:
        run = project.runs[-1] if project.runs else None
        tasks = run.chapter_tasks if run else []
        quality_report = self._load_quality_audit_report(project.id)
        pattern_usage = self._pattern_card_usage_summary(project.id)
        return {
            "output_root": str(getattr(self.artifacts, "root", "")),
            "model": getattr(self.llm, "model", None),
            "projects": [
                {
                    "key": project.id,
                    "project_id": project.id,
                    "template_id": project.template_id,
                    "run_status": run.status.value if run else "not_started",
                    "generation_scope": "full",
                    "task_count": len(tasks),
                    "passed_count": sum(1 for task in tasks if task.status == TaskStatus.passed),
                    "failed": [
                        {
                            "node_id": task.node_id,
                            "title": task.title,
                            "status": task.status.value,
                            "error_message": task.error_message,
                        }
                        for task in tasks
                        if task.status != TaskStatus.passed
                    ],
                    "quality_audit": _targeted_quality_summary(quality_report),
                    "pattern_card_usage": pattern_usage,
                    "content_revision_target_count": len(self._version_content_revision_targets(project.id)),
                    "generation_metadata_target_count": len(self._version_generation_metadata_targets(project.id)),
                }
            ],
        }

    def _pattern_card_usage_summary(self, project_id: str) -> dict:
        root = getattr(self.artifacts, "root", None)
        if root is None:
            return {}
        try:
            report = audit_pattern_card_usage(Path(root) / project_id)
        except Exception:
            return {}
        summary = report.get("summary") or {}
        return {
            "chapter_count": summary.get("chapter_count", 0),
            "chapters_with_prompt_cards": summary.get("chapters_with_prompt_cards", 0),
            "prompt_card_total": summary.get("prompt_card_total", 0),
            "prompt_card_actionable_total": summary.get("prompt_card_actionable_total", 0),
            "missing_prompt_card_count": summary.get("missing_prompt_card_count", 0),
            "warning_count": summary.get("warning_count", 0),
        }

    def _execute_quality_audit_target(
        self,
        project_id: str,
        target: dict,
        *,
        target_index: int,
        action: str | None = None,
    ) -> dict:
        selected_action = action or str(target.get("action") or "")
        target_type = str(target.get("target_type") or "")
        if target_type == "outline":
            return {
                "kind": "outline_proposal",
                "target_index": target_index,
                "action": selected_action,
                "target": target,
                "proposal": self._quality_audit_outline_proposal(project_id, target),
            }
        if target_type == "detail_budget":
            report = self._load_quality_audit_report(project_id)
            if report is None:
                raise ValueError("No quality audit report is available for detail-budget feedback.")
            return {
                "kind": "quality_feedback",
                "target_index": target_index,
                "action": selected_action,
                "target": target,
                "feedback": self.apply_quality_feedback_report(project_id, report),
            }
        if target_type == "chapter":
            node_id = str(target.get("node_id") or "")
            if not node_id:
                raise ValueError("Quality audit chapter target has no node_id.")
            if selected_action == "request_human_input":
                return {
                    "kind": "human_input_required",
                    "target_index": target_index,
                    "action": selected_action,
                    "target": target,
                    "message": "Persist chapter supplements or source material before regenerating this quality-audit target.",
                }
            draft = self.generate_one(
                project_id,
                node_id,
                revision_context=_render_quality_audit_target_context(target, selected_action=selected_action),
            )
            return {
                "kind": "chapter_version",
                "target_index": target_index,
                "action": selected_action,
                "target": target,
                "draft": dump_model(draft),
            }
        if target_type == "content_node":
            node_id = str(target.get("node_id") or "")
            version_id = str(target.get("version_id") or "")
            content_node_id = str(target.get("content_node_id") or "")
            if not node_id or not version_id or not content_node_id:
                raise ValueError("Quality audit content-node target is missing node_id, version_id, or content_node_id.")
            result = self.execute_content_revision_action(
                project_id,
                node_id,
                version_id,
                content_node_id,
                selected_action if selected_action in {"remap_sources", "review_source_link", "rewrite_subsection"} else "rewrite_subsection",
            )
            result["target_index"] = target_index
            result["quality_audit_target"] = target
            return result
        raise ValueError(f"Unsupported quality audit target type: {target_type}")

    def _quality_audit_outline_proposal(self, project_id: str, target: dict) -> dict:
        if self.workspace_store is None:
            raise ValueError("Workspace store is not configured.")
        existing = self.workspace_store.list_outline_nodes(project_id)
        order = max([int(item.get("sort_order") or 0) for item in existing] or [0]) + 10
        title = str(target.get("title") or "Quality audit outline target")
        node = {
            "__action": "create",
            "node_id": stable_id("qfbnode", project_id, title),
            "parent_id": None,
            "title": title,
            "level": 1,
            "sort_order": order,
            "enabled": True,
            "source_rules": [
                str(target.get("reason") or "Created from quality-audit revision target."),
                *[str(item) for item in target.get("evidence") or []],
            ],
            "auto_fill": [
                "Use mapped bid-document sections, project profile, and local construction-organization writing patterns to organize source-backed prose.",
            ],
            "manual_fill": [
                "【需人工补充：确认该质量审计目标是否适用于当前项目，并补充图纸、审批、现场、合同或实测资料中未在输入文档明确的信息。】",
            ],
            "special_notes": [
                "Created from project-level quality audit; apply only after user confirmation.",
            ],
            "target_word_count": 700,
        }
        return self.workspace_store.propose_outline_change(
            project_id,
            "Create editable outline nodes from project-level quality-audit revision targets.",
            [node],
        )

    def _quality_audit_outline_nodes(self, project: Project) -> list[dict]:
        if self.workspace_store is not None:
            try:
                return self.workspace_store.list_outline_nodes(project.id)
            except Exception:
                pass
        tree = self._effective_template_tree(project)
        if tree is None:
            return []
        return [
            {
                "node_id": node.id,
                "title": node.title,
                "source_rules": node.source_rules,
                "auto_fill": node.auto_fill,
                "manual_fill": node.manual_fill,
                "special_notes": node.special_notes,
            }
            for node in iter_template_nodes(tree.nodes)
        ]

    def _quality_audit_workspaces(self, project_id: str, outline_nodes: list[dict]) -> dict[str, dict]:
        if self.workspace_store is None:
            return {}
        workspaces: dict[str, dict] = {}
        for node in outline_nodes:
            node_id = str(node.get("node_id") or "")
            if not node_id:
                continue
            try:
                workspaces[node_id] = self.workspace_store.get_workspace(project_id, node_id)
            except Exception:
                continue
        return workspaces

    def _current_generated_markdown(self, project: Project) -> str:
        run = project.runs[-1] if project.runs else None
        if run is not None and run.final_artifact_path:
            try:
                return self.artifacts.read_text(run.final_artifact_path)
            except Exception:
                pass
        if project.template_tree is None:
            return ""
        drafts = self._selected_version_drafts(project)
        if not drafts and run is not None:
            drafts = self._drafts.get(run.id) or _load_drafts_from_tasks(project.id, run, self.artifacts)
        drafts = [draft for draft in drafts if (draft.markdown or "").strip()]
        if not drafts:
            return ""
        return merge_template_tree_markdowns(
            f"{project.name}施工组织设计",
            project.template_tree.nodes,
            drafts,
        )

    def _project_source_markdown(self, project: Project) -> str:
        for document in reversed(project.source_documents):
            if document.normalized_artifact_path:
                try:
                    return self.artifacts.read_text(document.normalized_artifact_path)
                except Exception:
                    pass
        if project.sections:
            return "\n\n".join(section.content for section in project.sections)
        return ""

    def _load_revision_decisions(self, project_id: str) -> list[dict]:
        root = getattr(self.artifacts, "root", None)
        if root is None:
            return []
        path = Path(root) / project_id / "control" / "revision_decisions.json"
        if not path.exists():
            return []
        try:
            payload = json.loads(path.read_text(encoding="utf-8-sig"))
            return payload if isinstance(payload, list) else []
        except Exception:
            return []

    def _outline_step_action_targets(self, project_id: str) -> list[dict]:
        try:
            project = self.projects.get(project_id)
            tree = self._effective_template_tree(project)
            progress = self.outline_generation_step_progress(project_id)
        except Exception:
            return []
        if tree is None:
            return []

        generation_contract_ids = {node.id for node in iter_template_nodes(tree.nodes) if node.has_generation_contract}
        targets: list[dict] = []
        for step in progress.get("steps", []):
            nodes = step.get("nodes") or []
            actionable_nodes = [
                node
                for node in nodes
                if node.get("node_id") in generation_contract_ids
                and (
                    node.get("task_status") in {"pending", "failed", "needs_repair"}
                    or not node.get("selected_version_id")
                )
            ]
            if not actionable_nodes:
                continue
            node_titles = [str(node.get("title") or node.get("node_id")) for node in actionable_nodes[:3]]
            targets.append(
                {
                    "step_id": step.get("step_id"),
                    "title": "生成目录层级",
                    "reason": (
                        f"{len(actionable_nodes)} 个可生成节点待处理："
                        + "、".join(node_titles)
                    ),
                    "node_count": len(actionable_nodes),
                    "node_ids": [node.get("node_id") for node in actionable_nodes],
                }
            )
            if len(targets) >= 3:
                break
        return targets

    def _child_generation_action_targets(self, project_id: str) -> list[dict]:
        try:
            project = self.projects.get(project_id)
            tree = self._effective_template_tree(project)
        except Exception:
            return []
        if tree is None:
            return []
        run = project.runs[-1] if project.runs else None
        if run is None:
            return []
        task_by_node = {task.node_id: task for task in run.chapter_tasks}
        targets: list[dict] = []
        for parent in iter_template_nodes(tree.nodes):
            child_nodes = [
                child
                for child in _child_generation_nodes(parent, recursive=False)
                if child.id in task_by_node and child.has_generation_contract
            ]
            if not child_nodes:
                continue
            actionable = []
            for child in child_nodes:
                task = task_by_node[child.id]
                selected_version_id = _workspace_selected_version_id(self.workspace_store, project_id, child.id)
                if task.status.value in {"pending", "failed", "needs_repair", "running"} or not selected_version_id:
                    actionable.append(child)
            if not actionable:
                continue
            titles = [child.title for child in actionable[:3]]
            targets.append(
                {
                    "parent_node_id": parent.id,
                    "title": parent.title,
                    "reason": (
                        f"{len(actionable)} child chapter(s) under `{parent.title}` need branch generation: "
                        + ", ".join(titles)
                    ),
                    "child_count": len(actionable),
                    "child_node_ids": [child.id for child in actionable],
                }
            )
            if len(targets) >= 3:
                break
        return targets

    def _version_generation_metadata_targets(self, project_id: str) -> list[dict]:
        if self.workspace_store is None:
            return []
        try:
            project = self.projects.get(project_id)
        except Exception:
            return []
        run = project.runs[-1] if project.runs else None
        node_ids = [task.node_id for task in run.chapter_tasks] if run else []
        if not node_ids:
            tree = self._effective_template_tree(project)
            if tree is not None:
                node_ids = [node.id for node in iter_template_nodes(tree.nodes) if not node.children]

        targets: list[dict] = []
        for node_id in node_ids:
            try:
                workspace = self.workspace_store.get_workspace(project_id, node_id)
            except Exception:
                continue
            version_id = workspace.get("selected_version_id")
            if not version_id:
                continue
            selected = next((item for item in workspace.get("versions", []) if item.get("id") == version_id), None)
            if not selected:
                continue
            audit = audit_version_generation_metadata(selected)
            action = _generation_metadata_revision_action(audit)
            if action == "accept":
                continue
            targets.append(
                {
                    "node_id": node_id,
                    "version_id": version_id,
                    "title": (workspace.get("outline_node") or {}).get("title") or selected.get("title") or node_id,
                    "action": action,
                    "reason": "；".join(str(item) for item in (audit.get("issues") or audit.get("next_actions") or [])[:3]),
                    "pattern_audits": _metadata_learning_pattern_audits(audit),
                    "prompt_card_audits": _metadata_learning_prompt_card_audits(audit),
                    "next_actions": audit.get("next_actions") or [],
                    "requires_llm": action in {"regenerate", "expand_subsections"},
                    "requires_user_confirmation": action in {"repair_outline_coverage", "expand_subsections", "request_human_input"},
                }
            )
        return targets

    def _version_evidence_utilization_targets(self, project_id: str) -> list[dict]:
        if self.workspace_store is None:
            return []
        try:
            project = self.projects.get(project_id)
        except Exception:
            return []
        run = project.runs[-1] if project.runs else None
        node_ids = [task.node_id for task in run.chapter_tasks] if run else []
        if not node_ids:
            tree = self._effective_template_tree(project)
            if tree is not None:
                node_ids = [node.id for node in iter_template_nodes(tree.nodes) if not node.children]

        targets: list[dict] = []
        for node_id in node_ids:
            try:
                workspace = self.workspace_store.get_workspace(project_id, node_id)
            except Exception:
                continue
            version_id = workspace.get("selected_version_id")
            if not version_id:
                continue
            selected = next((item for item in workspace.get("versions", []) if item.get("id") == version_id), None)
            audit = (selected or {}).get("evidence_audit")
            if not audit:
                targets.append(
                    {
                        "node_id": node_id,
                        "version_id": version_id,
                        "title": (workspace.get("outline_node") or {}).get("title") or node_id,
                        "action": "regenerate",
                        "reason": "Selected version has no persisted evidence audit; regenerate or review before merge.",
                        "requires_llm": True,
                        "requires_user_confirmation": False,
                    }
                )
                continue
            issues = [
                item
                for item in audit.get("issues") or []
                if item.get("suggested_action") and item.get("suggested_action") != "accept"
            ]
            if not issues:
                continue
            suggested = str(issues[0].get("suggested_action") or "review_evidence_utilization")
            reason_terms: list[str] = []
            for issue in issues[:3]:
                code = issue.get("code") or "evidence_issue"
                terms = "、".join(str(term) for term in (issue.get("terms") or [])[:3])
                reason_terms.append(f"{code}: {terms}" if terms else str(code))
            targets.append(
                {
                    "node_id": node_id,
                    "version_id": version_id,
                    "title": (workspace.get("outline_node") or {}).get("title") or selected.get("title") or node_id,
                    "action": suggested,
                    "reason": "；".join(reason_terms),
                    "requires_llm": suggested in {"regenerate", "remap_sources", "repair_format"},
                    "requires_user_confirmation": suggested in {"request_human_input", "expand_subsections", "disable_node"},
                }
            )
        return targets

    def _version_content_revision_targets(self, project_id: str) -> list[dict]:
        if self.workspace_store is None:
            return []
        try:
            project = self.projects.get(project_id)
        except Exception:
            return []
        run = project.runs[-1] if project.runs else None
        node_ids = [task.node_id for task in run.chapter_tasks] if run else []
        if not node_ids:
            tree = self._effective_template_tree(project)
            if tree is not None:
                node_ids = [node.id for node in iter_template_nodes(tree.nodes) if not node.children]

        targets: list[dict] = []
        for node_id in node_ids:
            try:
                workspace = self.workspace_store.get_workspace(project_id, node_id)
            except Exception:
                continue
            version_id = workspace.get("selected_version_id")
            if not version_id:
                continue
            selected = next((item for item in workspace.get("versions", []) if item.get("id") == version_id), None)
            plan = (selected or {}).get("content_revision_plan") or {}
            for item in plan.get("items", [])[:8]:
                action = item.get("action")
                content_node_id = item.get("content_node_id")
                if not action or action == "accept" or not content_node_id:
                    continue
                targets.append(
                    {
                        "node_id": node_id,
                        "version_id": version_id,
                        "content_node_id": content_node_id,
                        "title": " > ".join(item.get("title_path") or [item.get("title") or content_node_id]),
                        "action": action,
                        "reason": item.get("reason") or "; ".join(str(step) for step in item.get("next_steps", [])[:2]),
                        "evidence_targeted": "omitted_required_source_facts" in str(item.get("reason") or ""),
                        "evidence_ids": item.get("evidence_ids") or [],
                        "source_section_ids": item.get("source_section_ids") or [],
                        "source_status": item.get("source_status"),
                        "next_steps": item.get("next_steps") or [],
                        "requires_llm": bool(item.get("requires_llm")),
                        "requires_user_confirmation": bool(item.get("requires_user_confirmation")),
                    }
                )
        return targets

    def _workspace_summary_by_node(self, project_id: str) -> dict[str, dict]:
        if self.workspace_store is None:
            return {}
        try:
            nodes = self.workspace_store.list_outline_nodes(project_id)
        except Exception:
            return {}
        output: dict[str, dict] = {}
        for node in nodes:
            node_id = node.get("node_id")
            if not node_id:
                continue
            summary = {
                "title": node.get("title"),
                "selected_version_id": node.get("selected_version_id"),
                "selected_version": None,
            }
            try:
                workspace = self.workspace_store.get_workspace(project_id, node_id)
                selected_id = workspace.get("selected_version_id")
                selected = next((item for item in workspace.get("versions", []) if item.get("id") == selected_id), None)
                summary["selected_version_id"] = selected_id
                summary["selected_version"] = selected
            except Exception:
                pass
            output[node_id] = summary
        return output

    def _chapter_user_context(self, project_id: str, node_id: str) -> str:
        if self.workspace_store is None:
            return ""
        try:
            return self.workspace_store.render_chapter_context(project_id, node_id)
        except Exception:
            return ""

    def _quality_feedback_context(self, project_id: str) -> str:
        return render_quality_feedback_prompt_context(self._load_quality_feedback(project_id))

    def _quality_feedback_mapping_context(self, project_id: str) -> str:
        return render_quality_feedback_mapping_context(self._load_quality_feedback(project_id))

    def _quality_feedback_required_facts(self, project_id: str, task: ChapterTask, selected_sections: list) -> list[str]:
        source_parts = [getattr(section, "content", "") for section in selected_sections]
        if task.source_mapping:
            source_parts.extend(
                "\n".join([span.summary or "", span.quote or "", " ".join(span.matched_terms or [])])
                for span in task.source_mapping.evidence
            )
        return quality_feedback_required_fact_hints(
            self._load_quality_feedback(project_id),
            source_text="\n".join(source_parts),
        )

    def _record_chapter_version(self, project_id: str, node_id: str, draft: ChapterDraft, source_type: str) -> None:
        if self.workspace_store is None or draft.validation_status == TaskStatus.failed:
            return
        try:
            workspace = self.workspace_store.get_workspace(project_id, node_id)
            supplement_ids = [item["id"] for item in workspace.get("supplements", [])]
            generation_metadata = dict(draft.generation_metadata or {})
            generation_metadata["quality_review"] = {
                "status": draft.validation_status.value,
                "advisory_only": True,
                "message": "This version is visible for human review; quality findings suggest possible revision but do not block selection.",
                "issues": [dump_model(issue) for issue in draft.validation_issues],
            }
            self.workspace_store.create_chapter_version(
                project_id,
                node_id,
                title=draft.title,
                markdown=draft.markdown,
                artifact_path=draft.artifact_path,
                source_type=source_type,
                source_section_ids=draft.source_section_ids,
                supplement_ids=supplement_ids,
                created_by="ai",
                select=True,
                source_mapping=draft.source_mapping,
                generation_metadata=generation_metadata,
                evidence_audit=dump_model(draft.evidence_audit) if draft.evidence_audit else None,
            )
        except Exception as exc:
            # Versioning should not make the generation endpoint fail after a valid draft was produced.
            pass

    def _selected_version_drafts(self, project: Project) -> list[ChapterDraft]:
        if self.workspace_store is None:
            return []
        drafts: list[ChapterDraft] = []
        try:
            for node in iter_template_nodes(project.template_tree.nodes if project.template_tree else []):
                workspace = self.workspace_store.get_workspace(project.id, node.id)
                selected_id = workspace.get("selected_version_id")
                if not selected_id:
                    continue
                version = self.workspace_store.get_version(project.id, node.id, selected_id)
                drafts.append(
                    ChapterDraft(
                        node_id=node.id,
                        title=version["title"],
                        markdown=version["markdown"],
                        source_section_ids=version.get("source_section_ids", []),
                        validation_status=TaskStatus.passed,
                        evidence_audit=version.get("evidence_audit"),
                        generation_metadata=version.get("generation_metadata") or {},
                        artifact_path=version.get("artifact_path"),
                    )
                )
        except Exception:
            return []
        return drafts

    def _revision_decision_drafts(self, project: Project) -> list[ChapterDraft]:
        if not project.runs:
            return self._selected_version_drafts(project)
        run = project.runs[-1]
        task_by_node = {task.node_id: task for task in run.chapter_tasks}
        combined = {draft.node_id: draft for draft in self._selected_version_drafts(project)}
        for draft in _load_drafts_from_validation(project.id, run, self.artifacts):
            task = task_by_node.get(draft.node_id)
            should_prefer_validation_draft = (
                draft.node_id not in combined
                or draft.validation_status != TaskStatus.passed
                or (task is not None and task.status != TaskStatus.passed)
            )
            if should_prefer_validation_draft:
                combined[draft.node_id] = draft
        for draft in self._drafts.get(run.id, []):
            task = task_by_node.get(draft.node_id)
            should_prefer_run_draft = (
                draft.node_id not in combined
                or draft.validation_status != TaskStatus.passed
                or (task is not None and task.status != TaskStatus.passed)
            )
            if should_prefer_run_draft:
                combined[draft.node_id] = draft
        return list(combined.values())

    def _persist_validation(
        self,
        project_id: str,
        run: GenerationRun,
        *,
        drafts: list[ChapterDraft] | None = None,
        template_tree: TemplateTree | None = None,
        control_plan: GenerationControlPlan | None = None,
    ) -> None:
        decisions = []
        if template_tree is not None and control_plan is not None:
            decisions = build_revision_decisions(
                run=run,
                drafts=drafts or [],
                template_tree=template_tree,
                policies=control_plan.chapter_policies,
            )
            self.artifacts.write_text(project_id, "control/revision_decisions.json", to_json_text([dump_model(item) for item in decisions]))
            self.artifacts.write_text(project_id, "control/revision_decisions.md", render_revision_decisions(decisions))
        self.artifacts.write_text(
            project_id,
            f"runs/{run.id}/validation.json",
            to_json_text(_validation_payload(run, decisions=decisions, drafts=drafts or [])),
        )


def _find_node(nodes: list[TemplateNode], node_id: str) -> TemplateNode | None:
    for node in nodes:
        if node.id == node_id:
            return node
        found = _find_node(node.children, node_id)
        if found:
            return found
    return None


def _child_generation_nodes(parent: TemplateNode, *, recursive: bool = False) -> list[TemplateNode]:
    output: list[TemplateNode] = []
    for child in parent.children:
        if child.has_generation_contract:
            output.append(child)
        if recursive:
            output.extend(_child_generation_nodes(child, recursive=True))
    return output


def _workspace_selected_version_id(workspace_store, project_id: str, node_id: str) -> str | None:
    if workspace_store is None:
        return None
    try:
        workspace = workspace_store.get_workspace(project_id, node_id)
    except Exception:
        return None
    return workspace.get("selected_version_id")


def _find_content_node(nodes: list[dict], content_node_id: str) -> dict | None:
    for node in nodes:
        if node.get("id") == content_node_id:
            return node
        found = _find_content_node(node.get("children") or [], content_node_id)
        if found is not None:
            return found
    return None


def _content_revision_item(plan: dict, content_node_id: str) -> dict | None:
    for item in plan.get("items") or []:
        if item.get("content_node_id") == content_node_id:
            return item
    return None


def _content_revision_required_facts(item: dict) -> list[dict]:
    facts: list[dict] = []
    seen: set[tuple[str, str, str, str]] = set()
    pattern = re.compile(
        r"omitted required source fact `(?P<fact_id>[^`]+)` "
        r"from evidence `(?P<evidence_id>[^`]+)` / section `(?P<section_id>[^`]+)`:\s*(?P<fact>.+)",
        re.IGNORECASE,
    )
    for step in item.get("next_steps") or []:
        match = pattern.search(str(step))
        if not match:
            continue
        fact = {
            "fact_id": match.group("fact_id").strip(),
            "evidence_id": match.group("evidence_id").strip(),
            "section_id": match.group("section_id").strip(),
            "fact": match.group("fact").strip(),
        }
        key = (fact["fact_id"], fact["evidence_id"], fact["section_id"], fact["fact"])
        if key in seen:
            continue
        seen.add(key)
        facts.append(fact)
    return facts


def _content_revision_generation_metadata(
    metadata: dict | None,
    *,
    action: str,
    content_node_id: str,
    trace_path: str,
    required_facts: list[dict],
) -> dict:
    payload = dict(metadata or {})
    history = [item for item in payload.get("content_revision_history") or [] if isinstance(item, dict)]
    history.append(
        {
            "action": action,
            "content_node_id": content_node_id,
            "trace_path": trace_path,
            "required_fact_count": len(required_facts),
            "required_facts": required_facts,
        }
    )
    payload["content_revision_history"] = history[-12:]
    payload["last_content_revision_action"] = action
    payload["last_content_revision_trace_path"] = trace_path
    return payload


def _content_revision_source_sections(sections, content_node: dict, item: dict | None, retriever: SourceRetriever) -> list:
    section_ids = []
    for section_id in (item or {}).get("source_section_ids") or []:
        if section_id not in section_ids:
            section_ids.append(section_id)
    linked_sections = [section for section in sections if section.id in section_ids]
    query_node = TemplateNode(
        id=str(content_node.get("id") or "content_node"),
        title=str(content_node.get("title") or ""),
        level=int(content_node.get("level") or 3),
        source_rules=[
            str(content_node.get("body") or content_node.get("markdown") or ""),
            str((item or {}).get("reason") or ""),
            " ".join(str(step) for step in ((item or {}).get("next_steps") or [])),
        ],
        auto_fill=[],
        manual_fill=[],
        special_notes=[],
    )
    retrieved = retriever.retrieve(query_node, sections, limit=6)
    for match in retrieved:
        if match.section_id not in section_ids:
            section_ids.append(match.section_id)
    return [section for section in sections if section.id in section_ids[:8] or section in linked_sections]


def _content_split_proposal_nodes(*, project_id: str, node_id: str, content_node: dict, item: dict | None, workspace: dict) -> list[dict]:
    titles = _suggest_split_titles(content_node)
    outline = workspace.get("outline_node") or {}
    parent_level = int(outline.get("level") or 1)
    parent_sort = int(outline.get("sort_order") or 0)
    parent_target = outline.get("target_word_count")
    target_word_count = _split_target_word_count(parent_target, len(titles))
    body = str(content_node.get("body") or content_node.get("markdown") or "").strip()
    source_sections = (item or {}).get("source_section_ids") or []
    evidence_ids = (item or {}).get("evidence_ids") or []
    nodes: list[dict] = []
    for index, title in enumerate(titles, start=1):
        nodes.append(
            {
                "__action": "create",
                "node_id": f"split_{uuid4().hex[:12]}",
                "parent_id": node_id,
                "title": title,
                "level": parent_level + 1,
                "sort_order": parent_sort + index,
                "enabled": True,
                "source_rules": [
                    f"由已生成正文小节拆分而来：{' > '.join(content_node.get('title_path') or [content_node.get('title') or ''])}",
                    f"原 content_node_id：{content_node.get('id')}",
                    *[f"优先复用来源章节：{section_id}" for section_id in source_sections[:6]],
                    *[f"优先复核证据：{evidence_id}" for evidence_id in evidence_ids[:6]],
                ],
                "auto_fill": [
                    "根据该拆分主题重新进行来源映射、证据抽取和正文生成。",
                    "结合本地施组写作模式补齐对象、依据、流程、资源、质量、安全、环保、验收或记录等适用要点。",
                    "可参考原小节内容组织顺序，但事实必须重新由来源章节或用户补充支撑。",
                ],
                "manual_fill": [
                    "【需人工补充：若拆分后主题涉及图纸、审批、现场实测、最终参数、人员设备或合同约束，请在章节工作区补充后再生成。】"
                ],
                "special_notes": [
                    "该节点来自正文小节级 split_subsection 动作；应用 proposal 后应作为普通目录节点进入逐节点来源映射和生成流程。"
                ],
                "target_word_count": target_word_count,
                "split_from": {
                    "source_node_id": node_id,
                    "content_node_id": content_node.get("id"),
                    "content_title": content_node.get("title"),
                    "revision_action": (item or {}).get("action"),
                    "source_section_ids": source_sections,
                    "evidence_ids": evidence_ids,
                    "body_snippet": body[:500],
                },
            }
        )
    return nodes


def _split_target_word_count(parent_target, count: int) -> int:
    try:
        value = int(parent_target or 0)
    except Exception:
        value = 0
    if value > 0 and count > 0:
        return max(350, int(value / count))
    return 600


def _build_content_revision_prompt(
    *,
    project: Project,
    node_id: str,
    version: dict,
    content_node: dict,
    revision_item: dict,
    action: str,
    source_sections: list,
    user_context: str,
    required_facts: list[dict] | None = None,
) -> str:
    title = str(content_node.get("title") or "")
    level = int(content_node.get("level") or 3)
    heading = "#" * min(max(level, 1), 6)
    return "\n".join(
        [
            "CONTENT_SUBSECTION_REVISION_PROMPT",
            "你是施工组织设计正文小节修订 agent。你只修订当前正文小节，不重写整章。",
            "事实只能来自给定来源章节、当前章节工作区补充材料或人工补充占位；不得编造参数、工程量、日期、审批、坐标、监测或验收结论。",
            "",
            "## 项目概况 JSON",
            to_json_text(dump_model(project.project_profile)) if project.project_profile else "{}",
            "",
            "## 章节版本",
            f"- node_id: {node_id}",
            f"- version_id: {version.get('id')}",
            f"- chapter_title: {version.get('title')}",
            "",
            "## 当前小节",
            f"- content_node_id: {content_node.get('id')}",
            f"- title_path: {' > '.join(content_node.get('title_path') or [])}",
            f"- source_status: {content_node.get('source_status')}",
            "",
            "```markdown",
            str(content_node.get("markdown") or ""),
            "```",
            "",
            "## 小节修订动作",
            to_json_text(revision_item or {"action": action}),
            "",
            "## 已选来源章节全文",
            "## content_revision_required_facts",
            _render_content_revision_required_facts(required_facts or []),
            "",
            "## selected_source_sections",
            _render_content_revision_sources(source_sections),
            "",
            "## 章节工作区补充材料",
            user_context or "无。",
            "",
            "## 输出合同",
            "只输出当前小节的 Markdown，不要输出整章，不要 JSON，不要解释。",
            f"第一行必须是：{heading} {title}",
            "正文应围绕该小节标题展开；如来源不足，必须写成 `【需人工补充：...】`。",
            "如果本次动作是 remap_sources 或 review_source_link，应优先吸收新匹配来源中的明确事实，并在句中保留 section_id 或 evidence_id 便于后续追溯。",
            "如果本次动作是 rewrite_subsection，应在不编造的前提下补齐对象、依据、流程、资源、质量、安全、环保、验收或记录等适用要点。",
        ]
    )


def _render_content_revision_required_facts(facts: list[dict]) -> str:
    if not facts:
        return "none"
    lines: list[str] = []
    for fact in facts[:16]:
        lines.append(
            "- "
            f"fact_id: {fact.get('fact_id', '-')}; "
            f"evidence_id: {fact.get('evidence_id', '-')}; "
            f"section_id: {fact.get('section_id', '-')}; "
            f"fact: {fact.get('fact', '-')}"
        )
    return "\n".join(lines)


def _render_content_revision_sources(sections: list) -> str:
    if not sections:
        return "未找到可靠来源章节。"
    blocks = []
    for section in sections[:8]:
        content = (section.content or "").strip()
        if len(content) > 5000:
            content = content[:5000].rstrip() + "\n【来源章节已截断】"
        blocks.append(
            "\n".join(
                [
                    f"### section_id: {section.id}",
                    f"标题路径：{' > '.join(section.title_path)}",
                    "```text",
                    content,
                    "```",
                ]
            )
        )
    return "\n\n".join(blocks)


def _suggest_split_titles(content_node: dict) -> list[str]:
    title = str(content_node.get("title") or "当前小节")
    body = str(content_node.get("body") or content_node.get("markdown") or "")
    candidates = []
    if any(term in body for term in ["流程", "工艺", "施工方法", "工序"]):
        candidates.append(f"{title}工艺流程")
    if any(term in body for term in ["人员", "设备", "材料", "机械"]):
        candidates.append(f"{title}资源配置")
    if any(term in body for term in ["质量", "检验", "验收"]):
        candidates.append(f"{title}质量检验")
    if any(term in body for term in ["安全", "风险", "应急"]):
        candidates.append(f"{title}安全控制")
    if any(term in body for term in ["环保", "文明施工", "水保"]):
        candidates.append(f"{title}环保与文明施工")
    return candidates or [f"{title}施工方法", f"{title}质量安全控制"]


def _load_drafts_from_tasks(project_id: str, run: GenerationRun, artifacts: ArtifactRepository) -> list[ChapterDraft]:
    drafts: list[ChapterDraft] = []
    for task in run.chapter_tasks:
        path = f"{getattr(artifacts, 'root')}/{project_id}/chapters/{task.node_id}.md"
        try:
            markdown = artifacts.read_text(path)
        except Exception:
            continue
        drafts.append(
            ChapterDraft(
                node_id=task.node_id,
                title=task.title,
                markdown=markdown,
                source_section_ids=[match.section_id for match in task.source_matches],
                validation_status=task.status,
                artifact_path=path,
            )
        )
    return drafts


def _load_drafts_from_validation(project_id: str, run: GenerationRun, artifacts: ArtifactRepository) -> list[ChapterDraft]:
    root = getattr(artifacts, "root", None)
    if root is None:
        return []
    validation_path = Path(root) / project_id / "runs" / run.id / "validation.json"
    if not validation_path.exists():
        return []
    try:
        payload = json.loads(validation_path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return []
    tasks = payload.get("tasks") or []
    if not isinstance(tasks, list):
        return []
    drafts: list[ChapterDraft] = []
    task_by_node = {task.node_id: task for task in run.chapter_tasks}
    for item in tasks:
        if not isinstance(item, dict):
            continue
        node_id = str(item.get("node_id") or "")
        if not node_id:
            continue
        task = task_by_node.get(node_id)
        markdown_path = Path(root) / project_id / "chapters" / f"{node_id}.md"
        try:
            markdown = markdown_path.read_text(encoding="utf-8-sig")
        except OSError:
            markdown = ""
        status_value = item.get("status") or (task.status.value if task else TaskStatus.pending.value)
        try:
            status = TaskStatus(status_value)
        except ValueError:
            status = task.status if task else TaskStatus.pending
        drafts.append(
            ChapterDraft(
                node_id=node_id,
                title=str(item.get("title") or (task.title if task else node_id)),
                markdown=markdown,
                source_section_ids=[str(section_id) for section_id in item.get("source_section_ids") or []],
                source_mapping=item.get("mapping"),
                validation_status=status,
                evidence_audit=item.get("evidence_audit"),
                artifact_path=str(markdown_path) if markdown_path.exists() else None,
            )
        )
    return drafts


def _should_skip_no_source(policy, mapping) -> bool:
    return bool(policy and not policy.generate_when_no_source and mapping is not None and not mapping.matches)


def _join_context(*parts: str) -> str:
    return "\n\n".join(part.strip() for part in parts if part and part.strip())


def _mapping_control_context(policy) -> str:
    if policy is None:
        return ""
    lines = ["## Mapping Policy Requirements"]
    if getattr(policy, "writing_pattern_key", None):
        lines.append(f"- writing_pattern_key: {policy.writing_pattern_key}")
    if getattr(policy, "writing_pattern_matches", None):
        lines.append("- writing_pattern_matches: " + ", ".join(policy.writing_pattern_matches))
    if getattr(policy, "pattern_required_source_facts", None):
        lines.append("- pattern_required_source_facts:")
        lines.extend(f"  - {item}" for item in policy.pattern_required_source_facts[:12])
    if getattr(policy, "pattern_human_only_items", None):
        lines.append("- pattern_human_only_items:")
        lines.extend(f"  - {item}" for item in policy.pattern_human_only_items[:12])
    if getattr(policy, "pattern_prompt_cards", None):
        lines.append("- pattern_prompt_cards:")
        for card in policy.pattern_prompt_cards[:3]:
            lines.append(f"  - pattern_key: {card.get('pattern_key')}")
            source_requirements = card.get("source_mapping_requirements") or []
            if source_requirements:
                lines.append("    source_mapping_requirements:")
                lines.extend(f"      - {item}" for item in source_requirements[:6])
            human_only = card.get("human_only_items") or []
            if human_only:
                lines.append("    human_only_items:")
                lines.extend(f"      - {item}" for item in human_only[:6])
    if getattr(policy, "source_subtopics", None):
        lines.append("- source_subtopics:")
        lines.extend(f"  - {item}" for item in policy.source_subtopics[:12])
    if getattr(policy, "required_subtopics", None):
        lines.append("- required_subtopics:")
        lines.extend(f"  - {item}" for item in policy.required_subtopics[:12])
    if getattr(policy, "reason", None):
        lines.append(f"- policy_reason: {policy.reason}")
    lines.extend(
        [
            "",
            "Mapping rules:",
            "- Prefer source sections that can support the pattern_required_source_facts.",
            "- Treat pattern_human_only_items as evidence gaps to find, not as facts to invent.",
            "- If no section supports the required facts, return missing_evidence instead of weak matches.",
        ]
    )
    return "\n".join(lines).strip()


def _merge_learning_targets(existing: Any, current: list[dict]) -> list[dict]:
    output: list[dict] = []
    seen: set[tuple[str, str, str, str, str]] = set()
    for target in [*(existing or []), *(current or [])]:
        if not isinstance(target, dict):
            continue
        key = (
            str(target.get("node_id") or ""),
            str(target.get("version_id") or ""),
            str(target.get("content_node_id") or ""),
            str(target.get("action") or ""),
            str(target.get("reason") or ""),
        )
        if key in seen:
            continue
        seen.add(key)
        output.append(target)
    return output


def _render_revision_context(decision: ChapterRevisionDecision) -> str:
    lines = [
        "## Revision Control Requirements",
        f"- action: {decision.decision}",
        f"- severity: {decision.severity}",
    ]
    if decision.reasons:
        lines.append("- reasons:")
        lines.extend(f"  - {item}" for item in decision.reasons)
    if decision.required_changes:
        lines.append("- required_changes:")
        lines.extend(f"  - {item}" for item in decision.required_changes)
    if decision.missing_evidence:
        lines.append("- missing_evidence:")
        lines.extend(f"  - {item}" for item in decision.missing_evidence)
    if decision.evidence_audit:
        audit = decision.evidence_audit
        lines.extend(
            [
                "- evidence_audit:",
                f"  - coverage_ratio: {audit.coverage_ratio if audit.coverage_ratio is not None else '-'}",
            ]
        )
        if audit.omitted_required_fact_ids:
            facts_by_id = {fact.fact_id: fact for fact in audit.required_source_facts}
            lines.append("  - omitted_required_source_facts:")
            for fact_id in audit.omitted_required_fact_ids:
                fact = facts_by_id.get(fact_id)
                if fact is None:
                    lines.append(f"    - {fact_id}")
                    continue
                lines.append(
                    f"    - fact_id: {fact.fact_id}; evidence_id: {fact.evidence_id}; "
                    f"section_id: {fact.section_id}; fact: {fact.text}"
                )
        if audit.unused_high_value_evidence_ids:
            lines.append("  - unused_high_value_evidence_ids:")
            lines.extend(f"    - {item}" for item in audit.unused_high_value_evidence_ids[:12])
        if audit.manual_items_with_source_support:
            lines.append("  - manual_items_with_source_support:")
            lines.extend(f"    - {item}" for item in audit.manual_items_with_source_support)
    lines.extend(
        [
            "",
            "Regeneration rules:",
            "- Use the mapped source sections and evidence spans to address the required_changes.",
            "- If an omitted source fact is within this chapter scope, place it in `## 生成正文`.",
            "- If it is out of scope or still unsupported, explain it under `## 人工补充需补充` instead of silently dropping it.",
            "- Do not add unsupported parameters or facts only to satisfy the revision request.",
        ]
    )
    return "\n".join(lines).strip()


def _revision_context_required_fact_hints(revision_context: str, *, source_text: str = "") -> list[str]:
    if not revision_context:
        return []
    hints: list[str] = []
    active_block: str | None = None
    for raw_line in revision_context.splitlines():
        line = raw_line.strip(" -")
        if not line:
            active_block = None
            continue
        if line.endswith(":"):
            active_block = line[:-1]
            continue
        fact_match = re.search(r"\bfact:\s*(.+)$", line)
        if fact_match:
            _append_required_fact_hint(hints, fact_match.group(1), source_text=source_text)
            continue
        if line.startswith("fact_id:") and "fact:" in line:
            _append_required_fact_hint(hints, line.rsplit("fact:", 1)[-1], source_text=source_text)
            continue
        if active_block in {"omitted_feedback_required_facts", "manual_items_with_source_support"}:
            _append_required_fact_hint(hints, line, source_text=source_text)
            continue
        if "prompted_but_omitted" in line:
            _append_required_fact_hint(hints, line, source_text=source_text)
    return hints


def _merge_required_fact_hints(*groups: list[str]) -> list[str]:
    merged: list[str] = []
    for group in groups:
        for item in group:
            _append_required_fact_hint(merged, item)
    return merged


def _filter_required_fact_hints_by_source(hints: list[str], source_text: str) -> list[str]:
    output: list[str] = []
    for hint in hints:
        _append_required_fact_hint(output, hint, source_text=source_text)
    return output


def _append_required_fact_hint(output: list[str], value: str, *, source_text: str = "") -> None:
    cleaned = str(value).strip().strip("- ")
    cleaned = re.sub(r"\s+", " ", cleaned)
    if source_text and not _hint_supported_by_source(cleaned, source_text):
        return
    if cleaned and cleaned not in output:
        output.append(cleaned)


def _selected_source_text(task: ChapterTask, selected_sections: list) -> str:
    parts = [getattr(section, "content", "") for section in selected_sections]
    if task.source_mapping:
        parts.extend("\n".join([span.summary or "", span.quote or "", " ".join(span.matched_terms or [])]) for span in task.source_mapping.evidence)
    return "\n".join(parts)


def _hint_supported_by_source(hint: str, source_text: str) -> bool:
    normalized_source = re.sub(r"\s+", "", source_text or "")
    if not normalized_source:
        return False
    normalized_hint = re.sub(r"\s+", "", hint or "")
    if normalized_hint and len(normalized_hint) <= 120 and normalized_hint in normalized_source:
        return True
    for phrase in re.findall(r"[\u4e00-\u9fffA-Za-z0-9·（）()#\-~～.]{8,}", hint or ""):
        compact_phrase = re.sub(r"\s+", "", phrase)
        if len(compact_phrase) >= 8 and compact_phrase in normalized_source:
            return True
    numbers = re.findall(r"\d+(?:\.\d+)?", hint)
    number_hits = sum(1 for number in numbers if number in normalized_source)
    broad_terms = {
        "fact",
        "section",
        "evidence",
        "工程",
        "施工",
        "项目",
        "进行",
        "根据",
        "采用",
        "现场",
        "要求",
        "内容",
        "技术",
        "治理",
        "火区",
        "安全",
        "生态",
        "工作",
        "主要",
        "作业",
        "确定",
        "确保",
        "结合",
        "实际",
        "不同",
        "区域",
        "特征",
        "因素",
        "合同",
        "任务",
        "位于",
    }
    terms = [
        term
        for term in re.findall(r"[\u4e00-\u9fff]{2,12}|[A-Za-z][A-Za-z0-9_-]{1,30}", hint)
        if term not in broad_terms
    ]
    if not terms:
        return bool(number_hits) if numbers else normalized_hint in normalized_source
    hits = sum(1 for term in terms[:12] if term in normalized_source)
    if numbers:
        return bool(number_hits) and hits >= 1
    return hits >= min(3, len(terms))


def _render_quality_audit_target_context(target: dict, *, selected_action: str) -> str:
    lines = [
        "## Quality Audit Revision Target",
        f"- action: {selected_action}",
        f"- target_type: {target.get('target_type')}",
        f"- title: {target.get('title')}",
        f"- reason: {target.get('reason')}",
    ]
    evidence = [str(item) for item in target.get("evidence") or [] if str(item).strip()]
    if evidence:
        lines.append("- audit_evidence:")
        lines.extend(f"  - {item}" for item in evidence[:12])
    lines.extend(
        [
            "",
            "Regeneration rules:",
            "- This target comes from project-level quality audit, not from a new factual source.",
            "- Use the target as a control signal to improve source mapping, evidence absorption, detail budget, or subsection organization.",
            "- Only write facts that are supported by the mapped bid sections, evidence spans, project profile, or user supplements.",
            "- If the target fact or heading is unsupported in the current chapter scope, keep it as `【需人工补充：...】` instead of inventing it.",
        ]
    )
    return "\n".join(lines).strip()


def _quality_iteration_round_metrics(audit: dict, execution: dict) -> dict:
    report = audit.get("report") or {}
    word_counts = report.get("word_counts") or {}
    source_facts = report.get("source_facts") or {}
    targets = (audit.get("revision_targets") or {}).get("targets") or []
    return {
        "generated_words": word_counts.get("generated"),
        "generated_vs_human_ratio": word_counts.get("generated_vs_human_ratio"),
        "source_fact_absorption_ratio": source_facts.get("absorption_ratio"),
        "target_count": len(targets),
        "executed_count": len(execution.get("executed") or []),
        "skipped_count": len(execution.get("skipped") or []),
        "failed_count": len(execution.get("failed") or []),
    }


def _quality_iteration_status(rounds: list[dict], final_audit: dict) -> str:
    if any((round_item.get("execution") or {}).get("failed") for round_item in rounds):
        return "partial_failed"
    if not rounds or not any((round_item.get("execution") or {}).get("executed") for round_item in rounds):
        return "no_auto_actions"
    targets = ((final_audit.get("revision_targets") or {}).get("targets") or [])
    return "completed_with_remaining_targets" if targets else "completed"


def _quality_iteration_summary(rounds: list[dict], final_audit: dict) -> str:
    executed = sum(len((round_item.get("execution") or {}).get("executed") or []) for round_item in rounds)
    skipped = sum(len((round_item.get("execution") or {}).get("skipped") or []) for round_item in rounds)
    failed = sum(len((round_item.get("execution") or {}).get("failed") or []) for round_item in rounds)
    final_targets = len(((final_audit.get("revision_targets") or {}).get("targets") or []))
    return f"{len(rounds)} round(s), executed={executed}, skipped={skipped}, failed={failed}, final_targets={final_targets}."


def _render_quality_iteration_markdown(payload: dict) -> str:
    lines = [
        "# Quality Iteration",
        "",
        f"- project_id: `{payload.get('project_id')}`",
        f"- status: `{payload.get('status')}`",
        f"- summary: {payload.get('summary')}",
        f"- round_count: {payload.get('round_count')}",
        f"- content_revision_targets: {len(payload.get('content_revision_targets') or [])}",
        f"- generation_metadata_targets: {len(payload.get('generation_metadata_targets') or [])}",
        "",
        "## Rounds",
        "",
    ]
    for round_item in payload.get("rounds") or []:
        metrics = round_item.get("metrics") or {}
        execution = round_item.get("execution") or {}
        lines.extend(
            [
                f"### Round {round_item.get('round')}",
                f"- generated_words: {metrics.get('generated_words')}",
                f"- generated_vs_human_ratio: {metrics.get('generated_vs_human_ratio')}",
                f"- source_fact_absorption_ratio: {metrics.get('source_fact_absorption_ratio')}",
                f"- targets: {metrics.get('target_count')}",
                f"- executed: {metrics.get('executed_count')}",
                f"- skipped: {metrics.get('skipped_count')}",
                f"- failed: {metrics.get('failed_count')}",
                f"- execution_artifact: {execution.get('artifact_json_path') or '-'}",
                "",
            ]
        )
    final_report = (payload.get("final_audit") or {}).get("report") or {}
    final_facts = final_report.get("source_facts") or {}
    final_words = final_report.get("word_counts") or {}
    lines.extend(
        [
            "## Final Audit",
            "",
            f"- generated_words: {final_words.get('generated')}",
            f"- generated_vs_human_ratio: {final_words.get('generated_vs_human_ratio')}",
            f"- source_fact_absorption_ratio: {final_facts.get('absorption_ratio')}",
            f"- remaining_targets: {len(((payload.get('final_audit') or {}).get('revision_targets') or {}).get('targets') or [])}",
        ]
    )
    learning = payload.get("learning_report") or {}
    if learning:
        lines.extend(
            [
                "",
                "## Learning Report",
                "",
                f"- status: `{learning.get('status')}`",
                f"- suggestion_count: {len(learning.get('suggestions') or [])}",
                f"- artifact_json: {learning.get('artifact_json_path') or '-'}",
                f"- artifact_markdown: {learning.get('artifact_markdown_path') or '-'}",
            ]
        )
    return "\n".join(lines).strip() + "\n"


def _metadata_learning_pattern_audits(audit: dict) -> list[dict]:
    output: list[dict] = []
    for item in audit.get("pattern_audits") or []:
        if not isinstance(item, dict):
            continue
        suggested = str(item.get("suggested_action") or "accept")
        if suggested == "accept":
            continue
        output.append(
            {
                "pattern_key": item.get("pattern_key"),
                "suggested_action": suggested,
                "coverage_ratio": item.get("coverage_ratio"),
                "missing_points": [str(point) for point in item.get("missing_points") or [] if str(point).strip()][:8],
                "covered_points": [str(point) for point in item.get("covered_points") or [] if str(point).strip()][:8],
            }
        )
    return output


def _metadata_learning_prompt_card_audits(audit: dict) -> list[dict]:
    output: list[dict] = []
    for item in audit.get("prompt_card_audits") or []:
        if not isinstance(item, dict):
            continue
        suggested = str(item.get("suggested_action") or "accept")
        if suggested == "accept":
            continue
        output.append(
            {
                "pattern_key": item.get("pattern_key"),
                "suggested_action": suggested,
                "coverage_ratio": item.get("coverage_ratio"),
                "missing_requirements": [
                    str(point) for point in item.get("missing_requirements") or [] if str(point).strip()
                ][:8],
                "source_mapping_requirements": [
                    str(point) for point in item.get("source_mapping_requirements") or [] if str(point).strip()
                ][:8],
                "human_only_items": [str(point) for point in item.get("human_only_items") or [] if str(point).strip()][:8],
            }
        )
    return output


_METADATA_CUE_SUBTOPICS = [
    (
        ("施工准备", "construction preparation", "作业条件"),
        "施工准备与作业条件",
        "Map source sections about preparation, working conditions, personnel, equipment, materials, site access, utilities, and pre-work approvals.",
        "Organize preparation requirements, work conditions, resource readiness, technical disclosure, and records before the method body.",
    ),
    (
        ("测量放样", "setting out", "测量"),
        "测量放样与定位控制",
        "Map source sections about survey setting out, control points, layout, coordinates, boundaries, elevations, hole positions, or construction objects.",
        "Organize survey basis, setting-out procedure, review method, deviation control, and records.",
    ),
    (
        ("工艺流程", "process flow", "施工程序"),
        "工艺流程与施工顺序",
        "Map source sections about process flow, construction sequence, main methods, equipment routes, and operation steps.",
        "Organize the method as a clear sequence from preparation to operation, inspection, records, and handover.",
    ),
    (
        ("过程控制", "process control", "控制要求"),
        "过程控制与参数管理",
        "Map source sections about process controls, parameters, pressure, flow, mix ratio, temperature, thickness, compaction, monitoring, or deviation handling.",
        "Organize control points, monitoring feedback, abnormal handling, and parameter placeholders where source evidence is insufficient.",
    ),
    (
        ("检查验收", "inspection", "acceptance", "质量检查", "验收"),
        "检查验收与资料记录",
        "Map source sections about quality inspection, tests, acceptance criteria, hidden work acceptance, rectification, and records.",
        "Organize inspection items, test method, acceptance standard, rectification loop, and record deliverables.",
    ),
    (
        ("安全", "危险源", "environment", "环保", "应急"),
        "安全环保与应急控制",
        "Map source sections about hazards, safety measures, environmental protection, emergency response, firefighting, flood control, and civilized construction.",
        "Organize hazard controls, PPE, equipment safety, environmental measures, emergency response, and inspection responsibilities.",
    ),
]


def _generation_metadata_cue_subsection_nodes(
    *,
    parent_node: TemplateNode,
    audit: dict,
    existing_titles: set[str],
    start_sort_order: int,
) -> list[dict]:
    missing_text = _generation_metadata_missing_text(audit)
    if not missing_text:
        return []
    source_requirements = _generation_metadata_source_requirements(audit)
    selected: list[tuple[str, str, str]] = []
    lowered = missing_text.lower()
    for needles, title, source_rule, auto_fill in _METADATA_CUE_SUBTOPICS:
        if any(needle.lower() in lowered for needle in needles):
            selected.append((title, source_rule, auto_fill))
    if not selected and "expand_subsections" in lowered:
        selected = [(title, source_rule, auto_fill) for _needles, title, source_rule, auto_fill in _METADATA_CUE_SUBTOPICS[:5]]
    nodes: list[dict] = []
    order = start_sort_order
    for title, source_rule, auto_fill in selected[:6]:
        if title in existing_titles:
            continue
        nodes.append(
            {
                "__action": "create",
                "node_id": stable_id("metadata-subnode", parent_node.id, title),
                "parent_id": parent_node.id,
                "title": title,
                "level": parent_node.level + 1,
                "sort_order": order,
                "enabled": True,
                "source_rules": [source_rule, *source_requirements[:6]],
                "auto_fill": [
                    auto_fill,
                    "Use this subsection to satisfy missing local corpus body-writing cues without inventing unsupported project facts.",
                ],
                "manual_fill": [
                    f"【需人工补充：{parent_node.title}中“{title}”对应的审批参数、图纸编号、责任人、现场实测数据或附件说明。】"
                ],
                "special_notes": [
                    "Created from generation metadata audit; run source mapping and evidence extraction before factual writing, and cite mapped section_id/evidence_id in the generated source summary.",
                ],
                "target_word_count": _metadata_subsection_target(parent_node.target_word_count, len(selected)),
            }
        )
        existing_titles.add(title)
        order += 10
    return nodes


def _generation_metadata_missing_text(audit: dict) -> str:
    chunks: list[str] = []
    chunks.extend(str(item) for item in audit.get("issues") or [])
    chunks.extend(str(item) for item in audit.get("next_actions") or [])
    for item in audit.get("pattern_audits") or []:
        chunks.extend(str(point) for point in item.get("missing_points") or [])
        if item.get("suggested_action"):
            chunks.append(str(item.get("suggested_action")))
    for item in audit.get("prompt_card_audits") or []:
        chunks.extend(str(point) for point in item.get("missing_requirements") or [])
        chunks.extend(str(point) for point in item.get("revision_checks") or [])
        if item.get("suggested_action"):
            chunks.append(str(item.get("suggested_action")))
    return "\n".join(chunk for chunk in chunks if chunk.strip())


def _generation_metadata_source_requirements(audit: dict) -> list[str]:
    output: list[str] = []
    for item in audit.get("prompt_card_audits") or []:
        for point in item.get("source_mapping_requirements") or []:
            text = str(point).strip()
            if text and text not in output:
                output.append(text)
    return output[:8]


def _metadata_subsection_target(parent_target: int | None, count: int) -> int:
    if not parent_target or count <= 0:
        return 700
    return max(450, min(1000, int(round((parent_target / max(1, count)) / 50) * 50)))


def _append_unique(target: list, values: list[str]) -> None:
    for value in values:
        if value and value not in target:
            target.append(value)


def _generation_metadata_revision_action(audit: dict) -> str:
    if audit.get("status") == "passed":
        return "accept"
    metrics = audit.get("metrics") or {}
    if metrics.get("missing_metadata"):
        return "regenerate"

    pattern_actions = [
        item.get("suggested_action")
        for item in audit.get("pattern_audits", [])
        if item.get("suggested_action") and item.get("suggested_action") != "accept"
    ]
    pattern_actions.extend(
        item.get("suggested_action")
        for item in audit.get("prompt_card_audits", [])
        if item.get("suggested_action") and item.get("suggested_action") != "accept"
    )
    priority = ["repair_outline_coverage", "expand_subsections", "regenerate", "request_human_input"]
    for action in priority:
        if action in pattern_actions:
            return action
    return "request_human_input" if audit.get("issues") else "accept"


def _evidence_utilization_revision_action(audit: dict | None) -> str:
    if not audit:
        return "regenerate"
    issues = [
        item
        for item in audit.get("issues") or []
        if item.get("suggested_action") and item.get("suggested_action") != "accept"
    ]
    if not issues:
        return "accept"
    priority = ["remap_sources", "regenerate", "repair_format", "request_human_input"]
    suggested = [str(item.get("suggested_action")) for item in issues]
    for action in priority:
        if action in suggested:
            return action
    return suggested[0] if suggested else "request_human_input"


def _render_generation_metadata_revision_context(audit: dict) -> str:
    lines = [
        "## Local Writing Pattern Revision Requirements",
        f"- audit_status: {audit.get('status', '-')}",
    ]
    if audit.get("issues"):
        lines.append("- issues:")
        lines.extend(f"  - {item}" for item in audit["issues"][:8])
    if audit.get("next_actions"):
        lines.append("- next_actions:")
        lines.extend(f"  - {item}" for item in audit["next_actions"][:8])
    if audit.get("metrics"):
        lines.append("- metrics:")
        for key, value in sorted(audit["metrics"].items()):
            lines.append(f"  - {key}: {value}")
    pattern_audits = audit.get("pattern_audits") or []
    if pattern_audits:
        lines.append("- pattern_audits:")
        for item in pattern_audits[:5]:
            lines.append(
                "  - "
                f"pattern_key: {item.get('pattern_key', '-')}; "
                f"suggested_action: {item.get('suggested_action', '-')}; "
                f"coverage_ratio: {item.get('coverage_ratio', '-')}"
            )
            missing = item.get("missing_points") or []
            if missing:
                lines.append("    missing_points:")
                lines.extend(f"      - {point}" for point in missing[:8])
    prompt_card_audits = audit.get("prompt_card_audits") or []
    if prompt_card_audits:
        lines.append("- prompt_card_audits:")
        for item in prompt_card_audits[:5]:
            lines.append(
                "  - "
                f"pattern_key: {item.get('pattern_key', '-')}; "
                f"suggested_action: {item.get('suggested_action', '-')}; "
                f"coverage_ratio: {item.get('coverage_ratio', '-')}"
            )
            missing = item.get("missing_requirements") or []
            if missing:
                lines.append("    missing_requirements:")
                lines.extend(f"      - {point}" for point in missing[:8])
            source_requirements = item.get("source_mapping_requirements") or []
            if source_requirements:
                lines.append("    source_mapping_requirements:")
                lines.extend(f"      - {point}" for point in source_requirements[:8])
            human_only = item.get("human_only_items") or []
            if human_only:
                lines.append("    human_only_items:")
                lines.extend(f"      - {point}" for point in human_only[:8])
    lines.extend(
        [
            "",
            "Regeneration rules:",
            "- Treat local writing patterns as structural guidance only, not factual evidence.",
            "- Keep all project facts source-backed by mapped sections, evidence spans, or user supplements.",
            "- Expand the organization of the chapter to cover the missing pattern points when source evidence supports them.",
            "- Put unsupported parameters, drawings, approvals, site data, and personnel/equipment details under `## 人工补充需补充`.",
            "- Do not invent facts only to satisfy the writing pattern audit.",
        ]
    )
    return "\n".join(lines).strip()


def _render_evidence_utilization_revision_context(audit: dict | None, *, selected_action: str) -> str:
    lines = [
        "## Evidence Utilization Revision Requirements",
        f"- action: {selected_action}",
    ]
    if not audit:
        lines.extend(
            [
                "- audit_status: missing",
                "- reason: Selected version has no persisted evidence audit, so the retry must rebuild source mapping, evidence spans, and evidence utilization audit.",
                "",
                "Regeneration rules:",
                "- Re-run source mapping before writing.",
                "- Persist a new evidence audit for the regenerated version.",
                "- Keep all project facts source-backed by mapped sections, evidence spans, user supplements, or manual placeholders.",
            ]
        )
        return "\n".join(lines).strip()

    lines.extend(
        [
            f"- audit_node_id: {audit.get('node_id', '-')}",
            f"- evidence_count: {audit.get('evidence_count', 0)}",
            f"- coverage_ratio: {audit.get('coverage_ratio') if audit.get('coverage_ratio') is not None else '-'}",
        ]
    )
    issues = audit.get("issues") or []
    if issues:
        lines.append("- issues:")
        for issue in issues[:8]:
            lines.append(
                "  - "
                f"code: {issue.get('code', '-')}; "
                f"action: {issue.get('suggested_action', '-')}; "
                f"message: {issue.get('message', '-')}"
            )
            terms = issue.get("terms") or []
            if terms:
                lines.append("    terms:")
                lines.extend(f"      - {term}" for term in terms[:8])
            evidence_ids = issue.get("evidence_ids") or []
            if evidence_ids:
                lines.append("    evidence_ids:")
                lines.extend(f"      - {item}" for item in evidence_ids[:8])
    omitted_ids = set(str(item) for item in audit.get("omitted_required_fact_ids") or [])
    facts = [item for item in audit.get("required_source_facts") or [] if str(item.get("fact_id")) in omitted_ids]
    if facts:
        lines.append("- omitted_required_source_facts:")
        for fact in facts[:16]:
            lines.append(
                "  - "
                f"fact_id: {fact.get('fact_id', '-')}; "
                f"evidence_id: {fact.get('evidence_id', '-')}; "
                f"section_id: {fact.get('section_id', '-')}; "
                f"type: {fact.get('fact_type', '-')}; "
                f"fact: {fact.get('text', '-')}"
            )
            tokens = fact.get("tokens") or []
            if tokens:
                lines.append("    tokens: " + ", ".join(str(token) for token in tokens[:8]))
    if audit.get("omitted_feedback_fact_hints"):
        lines.append("- omitted_feedback_required_facts:")
        lines.extend(f"  - {item}" for item in audit["omitted_feedback_fact_hints"][:12])
    if audit.get("unused_high_value_evidence_ids"):
        lines.append("- unused_high_value_evidence_ids:")
        lines.extend(f"  - {item}" for item in audit["unused_high_value_evidence_ids"][:12])
    if audit.get("manual_items_with_source_support"):
        lines.append("- manual_items_with_source_support:")
        lines.extend(f"  - {item}" for item in audit["manual_items_with_source_support"][:12])
    lines.extend(
        [
            "",
            "Regeneration rules:",
            "- Re-run source mapping and evidence extraction with the omitted facts and unused evidence ids as search/control hints.",
            "- If an omitted source fact is within this chapter scope, place it in `## 生成正文` and cite the source/evidence in `## 主要来源摘要`.",
            "- If a fact is out of scope or still unsupported, explain it under `## 人工补充需补充` instead of silently dropping it.",
            "- Move any manual-fill item that is already supported by mapped evidence into the generated body when source-backed.",
            "- Do not invent parameters, quantities, approvals, drawings, coordinates, or measured data to satisfy the audit.",
        ]
    )
    return "\n".join(lines).strip()


def _outline_node_title(outline, node_id: str) -> str | None:
    for node in getattr(outline, "nodes", []) or []:
        if node.node_id == node_id:
            return node.title
    return None


def _task_source_section_ids(task: ChapterTask | None) -> list[str]:
    if task is None or task.source_mapping is None:
        return []
    ids: list[str] = []
    for match in task.source_mapping.matches:
        if match.section_id not in ids:
            ids.append(match.section_id)
    return ids


def _content_revision_action_count(plan: dict | None) -> int:
    if not plan:
        return 0
    return sum(1 for item in plan.get("items", []) if item.get("action") and item.get("action") != "accept")


def _outline_step_status(nodes: list[dict]) -> str:
    if not nodes:
        return "empty"
    if any(node["task_status"] == "failed" for node in nodes):
        return "warning"
    if any(node["content_revision_action_count"] or node["generation_metadata_action_count"] for node in nodes):
        return "warning"
    if all(node.get("selected_version_id") and node["task_status"] in {"passed", "needs_repair"} for node in nodes):
        return "completed"
    if any(node["task_status"] in {"running"} for node in nodes):
        return "running"
    if any(node["task_status"] in {"pending", "not_in_run"} for node in nodes):
        return "pending"
    return "ready"


def _outline_progress_status(steps: list[dict]) -> str:
    if not steps:
        return "not_prepared"
    statuses = {step["status"] for step in steps}
    if "warning" in statuses:
        return "warning"
    if statuses == {"completed"}:
        return "completed"
    if "running" in statuses:
        return "running"
    return "pending"


def _outline_progress_summary(steps: list[dict]) -> str:
    if not steps:
        return "No outline generation steps are available."
    completed = sum(1 for step in steps if step["status"] == "completed")
    warning = sum(1 for step in steps if step["status"] == "warning")
    return f"{completed}/{len(steps)} outline layer step(s) completed; {warning} step(s) need review."


def _targeted_quality_summary(report: dict | None) -> dict | None:
    if not report:
        return None
    word_counts = report.get("word_counts") or {}
    headings = report.get("headings") or {}
    facts = report.get("source_facts") or {}
    recommendations = report.get("recommendations") or []
    return {
        "generated_vs_human_ratio": word_counts.get("generated_vs_human_ratio"),
        "human_heading_coverage_ratio": headings.get("human_heading_coverage_ratio"),
        "source_fact_absorption_ratio": facts.get("absorption_ratio"),
        "issue_count": len(report.get("issues") or []),
        "issues": report.get("issues") or [],
        "recommendation_count": len(recommendations),
        "recommended_actions": [item.get("action") for item in recommendations if isinstance(item, dict) and item.get("action")],
    }


def _safe_artifact_name(value: str) -> str:
    return "".join(ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in value)[:120] or "step"


def _no_source_draft(project_id: str, node: TemplateNode, task: ChapterTask, artifacts: ArtifactRepository) -> ChapterDraft:
    task.status = TaskStatus.needs_repair
    task.error_message = "No reliable source mapping; review this placeholder, add human input, remap sources, or disable the node."
    missing = []
    if task.source_mapping and task.source_mapping.missing_evidence:
        missing = task.source_mapping.missing_evidence
    markdown = "\n".join(
        [
            f"# {node.title}",
            "",
            "## 主要来源摘要",
            "",
            "- 未匹配到可靠来源章节，本节点未调用 LLM 生成确定性正文。",
            "",
            "## 生成正文",
            "",
            "【需人工补充：当前章节缺少可追溯来源，需补充投标文件、图纸、审批资料、现场说明或禁用该目录节点后再生成。】",
            "",
            "## 人工补充需补充",
            "",
            *[f"- 【需人工补充：{item}】" for item in (missing or node.manual_fill or ["可靠来源章节"])],
        ]
    )
    draft = ChapterDraft(
        node_id=node.id,
        title=node.title,
        markdown=markdown,
        source_section_ids=[],
        source_mapping=task.source_mapping,
        missing_items=node.manual_fill,
        validation_status=TaskStatus.needs_repair,
        validation_issues=[
            ValidationIssue(
                code="no_source_mapping",
                message="No reliable source mapping; a placeholder was created for human review instead of unsupported factual writing.",
                severity="warning",
            )
        ],
    )
    draft.artifact_path = artifacts.write_text(project_id, f"chapters/{node.id}.md", draft.markdown)
    task.draft_id = draft.id
    return draft


def _render_generation_readiness_batch_execution(payload: dict) -> str:
    source = payload.get("source_readiness") or {}
    next_readiness = payload.get("next_readiness") or {}
    lines = [
        "# Generation Readiness Batch Execution",
        "",
        f"- project_id: `{payload.get('project_id') or '-'}`",
        f"- status: `{payload.get('status') or '-'}`",
        f"- group_id: `{payload.get('group_id') or '-'}`",
        f"- include_user_confirmation: `{str(bool(payload.get('include_user_confirmation'))).lower()}`",
        f"- respect_execution_window: `{str(bool(payload.get('respect_execution_window', True))).lower()}`",
        f"- limit: {payload.get('limit')}",
        f"- executed: {len(payload.get('executed') or [])}",
        f"- skipped: {len(payload.get('skipped') or [])}",
        f"- failed: {len(payload.get('failed') or [])}",
        "",
    ]
    warning = payload.get("execution_window_warning") or {}
    if warning:
        lines.extend(
            [
                "## Advisory Execution Window",
                "",
                f"- current_phase_id: `{warning.get('current_phase_id') or '-'}`",
                f"- message: {warning.get('message') or '-'}",
                "- recommended_actions:",
            ]
        )
        actions = warning.get("allowed_action_ids") or []
        lines.extend(f"  - `{item}`" for item in actions if item)
        if not actions:
            lines.append("  - -")
        lines.append("")
    lines.extend(
        [
        "## Readiness Delta",
        "",
        f"- before: `{source.get('status') or '-'}`; {source.get('summary') or '-'}",
        f"- after: `{next_readiness.get('status') or '-'}`; {next_readiness.get('summary') or '-'}",
        "",
        ]
    )
    lines.extend(_render_execution_items("Executed", payload.get("executed") or []))
    lines.extend(_render_execution_items("Skipped", payload.get("skipped") or []))
    lines.extend(_render_execution_items("Failed", payload.get("failed") or []))
    return "\n".join(lines).strip() + "\n"


def _readiness_execution_allowed_by_window(window: dict | None) -> bool:
    if not window:
        return True
    return window.get("status") == "auto_runnable"


def _readiness_execution_entry(batch_id: str | None, item: dict, result: dict) -> dict:
    response = result.get("response") if isinstance(result.get("response"), dict) else {}
    generated = result.get("generated") if isinstance(result.get("generated"), list) else []
    return {
        "batch": batch_id,
        "node_id": item.get("node_id") or result.get("node_id"),
        "title": item.get("title") or result.get("title"),
        "action": item.get("next_action") or result.get("action"),
        "result_kind": result.get("kind"),
        "status": result.get("status") or response.get("status") or response.get("kind"),
        "draft_id": result.get("draft_id"),
        "version_id": response.get("version_id") or response.get("new_version_id"),
        "artifact_path": result.get("artifact_path") or response.get("artifact_path"),
        "generated_count": len(generated),
        "failed_count": len(result.get("failed") or []) if isinstance(result.get("failed"), list) else 0,
        "item": item,
        "result": result,
    }


def _draft_error_message(draft: ChapterDraft, task: ChapterTask | None = None) -> str:
    if task is not None and task.error_message:
        return task.error_message
    if draft.validation_issues:
        return "; ".join(issue.message for issue in draft.validation_issues)
    if draft.evidence_audit and draft.evidence_audit.issues:
        return "; ".join(str(issue.get("message") or issue.get("code") or issue) for issue in draft.evidence_audit.issues)
    return ""


def _render_execution_items(title: str, items: list[dict]) -> list[str]:
    lines = [f"## {title}", ""]
    if not items:
        return [*lines, "- none", ""]
    for index, entry in enumerate(items, start=1):
        item = entry.get("item") or {}
        result = entry.get("result") or {}
        node_id = entry.get("node_id") or item.get("node_id") or result.get("node_id") or "-"
        action = entry.get("action") or item.get("next_action") or result.get("action") or "-"
        batch = entry.get("batch") or "-"
        lines.extend(
            [
                f"### {index}. {node_id}",
                "",
                f"- batch: `{batch}`",
                f"- action: `{action}`",
                f"- title: {entry.get('title') or item.get('title') or '-'}",
            ]
        )
        if entry.get("reason"):
            lines.append(f"- reason: {entry.get('reason')}")
        if entry.get("error"):
            lines.append(f"- error: {entry.get('error')}")
        if result:
            lines.append(f"- result_kind: `{entry.get('result_kind') or result.get('kind') or '-'}`")
            if entry.get("status") or result.get("status"):
                lines.append(f"- result_status: `{entry.get('status') or result.get('status')}`")
            if entry.get("artifact_path") or result.get("artifact_path"):
                lines.append(f"- artifact_path: `{entry.get('artifact_path') or result.get('artifact_path')}`")
            if entry.get("draft_id") or result.get("draft_id"):
                lines.append(f"- draft_id: `{entry.get('draft_id') or result.get('draft_id')}`")
            if entry.get("version_id"):
                lines.append(f"- version_id: `{entry.get('version_id')}`")
            if result.get("generated") is not None:
                lines.append(f"- generated_count: {entry.get('generated_count', len(result.get('generated') or []))}")
            if result.get("failed") is not None:
                lines.append(f"- failed_count: {entry.get('failed_count', len(result.get('failed') or []))}")
                for failed_item in (result.get("failed") or [])[:6]:
                    lines.append(
                        "  - "
                        f"{failed_item.get('node_id') or '-'}: {failed_item.get('error') or '-'}"
                        f"; next={failed_item.get('next_action') or '-'}"
                    )
                    if failed_item.get("endpoint"):
                        lines.append(f"    endpoint: `{failed_item.get('endpoint')}`")
        lines.append("")
    return lines


def _validation_payload(run: GenerationRun, decisions=None, drafts: list[ChapterDraft] | None = None) -> dict:
    decision_by_node = {item.node_id: dump_model(item) for item in (decisions or [])}
    draft_by_node = {draft.node_id: draft for draft in (drafts or [])}
    return {
        "run_id": run.id,
        "status": run.status.value,
        "tasks": [
            {
                "node_id": task.node_id,
                "title": task.title,
                "status": task.status.value,
                "source_section_ids": [match.section_id for match in task.source_matches],
                "mapping": dump_model(task.source_mapping) if task.source_mapping else None,
                "evidence_count": len(task.source_mapping.evidence) if task.source_mapping else 0,
                "evidence_artifact_path": task.source_mapping.evidence_artifact_path if task.source_mapping else None,
                "evidence_audit": dump_model(draft_by_node[task.node_id].evidence_audit)
                if task.node_id in draft_by_node and draft_by_node[task.node_id].evidence_audit
                else None,
                "revision_decision": decision_by_node.get(task.node_id),
                "error_message": task.error_message,
            }
            for task in run.chapter_tasks
        ],
    }


def _render_word_count_targets(estimates) -> str:
    lines = ["# 目录目标字数", ""]
    for estimate in estimates:
        matched = f"；参考标题：{estimate.matched_reference_title}" if estimate.matched_reference_title else ""
        reference_count = f"；参考字数：{estimate.reference_word_count}" if estimate.reference_word_count else ""
        lines.append(f"- `{estimate.node_id}` {estimate.title}：{estimate.target_word_count} 字（{estimate.method}{matched}{reference_count}）")
    return "\n".join(lines).strip() + "\n"
