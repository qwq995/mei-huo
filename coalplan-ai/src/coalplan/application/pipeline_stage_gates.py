from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from coalplan.application.generation_metadata_audit import audit_version_generation_metadata
from coalplan.application.serialization import dump_model
from coalplan.domain.generation import Project
from coalplan.domain.generation_control import GenerationControlPlan
from coalplan.domain.templates import TemplateTree, iter_template_nodes


GateStatus = Literal["pending", "passed", "warning", "blocked"]


class PipelineGateStatus(BaseModel):
    name: str
    status: GateStatus
    summary: str
    issues: list[str] = Field(default_factory=list)
    next_actions: list[str] = Field(default_factory=list)
    artifact_paths: list[str] = Field(default_factory=list)
    metrics: dict[str, int | float | str | None] = Field(default_factory=dict)


class PipelineGateReport(BaseModel):
    project_id: str
    overall_status: GateStatus
    gates: list[PipelineGateStatus] = Field(default_factory=list)


def build_pipeline_gate_report(
    *,
    project: Project,
    template_tree: TemplateTree | None = None,
    control_plan: GenerationControlPlan | None = None,
    revision_decisions: list[dict] | None = None,
    quality_feedback: dict | None = None,
    workspace_store=None,
    artifacts_root: Path | None = None,
) -> PipelineGateReport:
    gates = [
        _input_gate(project),
        _profile_gate(project),
        _outline_gate(project, template_tree=template_tree, workspace_store=workspace_store),
        _coverage_gate(control_plan),
        _detail_gate(control_plan),
        _mapping_gate(project),
        _generation_gate(project),
        _revision_gate(revision_decisions),
        _quality_feedback_gate(quality_feedback),
        _version_gate(project, template_tree=template_tree, workspace_store=workspace_store),
        _merge_gate(project, artifacts_root=artifacts_root),
    ]
    return PipelineGateReport(project_id=project.id, overall_status=_overall_status(gates), gates=gates)


def _input_gate(project: Project) -> PipelineGateStatus:
    issues: list[str] = []
    actions: list[str] = []
    artifacts: list[str] = []
    if not project.source_documents:
        issues.append("No source document has been uploaded.")
        actions.append("Upload a normalized bid markdown document.")
    if not project.sections:
        issues.append("No persisted source sections are available.")
        actions.append("Run markdown normalization and section splitting.")
    if project.source_toc is None:
        issues.append("Source TOC has not been persisted.")
        actions.append("Persist toc.json, toc.md, sections.json, and per-section markdown files.")
    else:
        artifacts.extend(_paths(project.source_toc.artifact_json_path, project.source_toc.artifact_markdown_path))

    status: GateStatus = "passed" if not issues else ("blocked" if not project.sections else "warning")
    return PipelineGateStatus(
        name="input",
        status=status,
        summary=f"{len(project.sections)} source section(s), {len(project.source_documents)} source document(s).",
        issues=issues,
        next_actions=_dedupe(actions),
        artifact_paths=artifacts,
        metrics={"section_count": len(project.sections), "source_document_count": len(project.source_documents)},
    )


def _profile_gate(project: Project) -> PipelineGateStatus:
    profile = project.project_profile
    if profile is None:
        return PipelineGateStatus(
            name="profile",
            status="pending" if project.sections else "blocked",
            summary="Project profile has not been extracted.",
            issues=["ProjectProfile is missing."],
            next_actions=["Extract project name, type, location, scope, quantities, methods, schedule, targets, risks, and source ids."],
        )

    required_fields = {
        "project_name": profile.project_name,
        "project_type": profile.project_type,
        "location": profile.location,
        "construction_scope": profile.construction_scope,
        "key_quantities": profile.key_quantities,
        "main_methods": profile.main_methods,
        "schedule": profile.schedule,
        "quality_safety_environment_targets": profile.quality_safety_environment_targets,
        "risk_points": profile.risk_points,
        "source_section_ids": profile.source_section_ids,
    }
    missing = [key for key, value in required_fields.items() if not value]
    issues = [f"Profile field is empty: {key}" for key in missing]
    fallback_markers = ("fallback", "兜底", "抽取失败", "校验失败")
    if any(any(marker in item for marker in fallback_markers) for item in profile.missing_items):
        issues.append("Project profile contains fallback or extraction-failure markers.")
    status: GateStatus = "passed" if not issues else "warning"
    return PipelineGateStatus(
        name="profile",
        status=status,
        summary=f"Profile extracted for: {profile.project_name or '-'}",
        issues=issues,
        next_actions=["Repair ProjectProfile before formal generation."] if issues else [],
        artifact_paths=_paths(profile.artifact_json_path, profile.artifact_markdown_path),
        metrics={
            "missing_field_count": len(missing),
            "source_section_id_count": len(profile.source_section_ids),
            "missing_item_count": len(profile.missing_items),
        },
    )


def _outline_gate(project: Project, *, template_tree: TemplateTree | None, workspace_store) -> PipelineGateStatus:
    tree = template_tree or project.template_tree
    nodes = list(iter_template_nodes(tree.nodes)) if tree else []
    editable_nodes = _safe_list_outline_nodes(workspace_store, project.id)
    issues: list[str] = []
    actions: list[str] = []
    if tree is None:
        issues.append("Template tree is not loaded.")
        actions.append("Select and load a compatible construction organization template.")
    if not nodes:
        issues.append("No template or outline nodes are available.")
    if not editable_nodes and tree is not None:
        issues.append("Project editable outline has not been copied to the workspace.")
        actions.append("Generate the project directory so users can edit, add, disable, and reorder nodes.")
    status: GateStatus = "passed" if not issues else ("warning" if nodes else "blocked")
    return PipelineGateStatus(
        name="outline",
        status=status,
        summary=f"{len(nodes)} effective outline node(s), {len(editable_nodes)} editable workspace node(s).",
        issues=issues,
        next_actions=_dedupe(actions),
        artifact_paths=_paths(
            project.outline_plan.artifact_json_path if project.outline_plan else None,
            project.outline_plan.artifact_markdown_path if project.outline_plan else None,
        ),
        metrics={"effective_node_count": len(nodes), "editable_node_count": len(editable_nodes)},
    )


def _coverage_gate(control_plan: GenerationControlPlan | None) -> PipelineGateStatus:
    if control_plan is None:
        return PipelineGateStatus(
            name="coverage",
            status="pending",
            summary="Generation control plan is not available.",
            issues=["Outline coverage has not been evaluated."],
            next_actions=["Build a generation control plan before generation."],
        )
    missing = [item for item in control_plan.outline_coverage if item.status == "missing"]
    partial = [item for item in control_plan.outline_coverage if item.status == "partial"]
    issues = [f"Missing outline coverage for source topic: {item.topic}" for item in missing]
    issues.extend(f"Partial outline coverage for source topic: {item.topic}" for item in partial)
    return PipelineGateStatus(
        name="coverage",
        status="passed" if not issues else "warning",
        summary=f"{len(control_plan.outline_coverage)} common topic coverage item(s) evaluated.",
        issues=issues,
        next_actions=["Create an outline proposal for missing or partial source-backed topics."] if issues else [],
        metrics={"coverage_item_count": len(control_plan.outline_coverage), "missing_count": len(missing), "partial_count": len(partial)},
    )


def _detail_gate(control_plan: GenerationControlPlan | None) -> PipelineGateStatus:
    if control_plan is None:
        return PipelineGateStatus(
            name="detail",
            status="pending",
            summary="No detail policy has been computed.",
            issues=["Chapter detail policy is missing."],
            next_actions=["Compute target word counts, source budgets, evidence budgets, and split decisions."],
        )
    policies = control_plan.chapter_policies
    without_targets = [policy for policy in policies if policy.target_word_count is None]
    split_required = [policy for policy in policies if policy.split_required]
    issues = [f"No target word count for chapter: {policy.title}" for policy in without_targets[:20]]
    if len(without_targets) > 20:
        issues.append(f"{len(without_targets) - 20} more chapter(s) have no target word count.")
    return PipelineGateStatus(
        name="detail",
        status="passed" if not without_targets else "warning",
        summary=f"{len(policies)} chapter policy item(s), {len(split_required)} split-required item(s).",
        issues=issues,
        next_actions=["Estimate target word counts and apply source-derived subsection expansion where needed."] if issues or split_required else [],
        metrics={
            "policy_count": len(policies),
            "without_target_word_count": len(without_targets),
            "split_required_count": len(split_required),
        },
    )


def _mapping_gate(project: Project) -> PipelineGateStatus:
    run = project.runs[-1] if project.runs else None
    if run is None or not run.chapter_tasks:
        return PipelineGateStatus(
            name="mapping",
            status="pending",
            summary="No chapter task has been prepared.",
            issues=["Chapter source mapping has not run."],
            next_actions=["Prepare a generation run, then map sources per chapter."],
        )
    mapped = [task for task in run.chapter_tasks if task.source_mapping is not None]
    no_matches = [task for task in mapped if task.source_mapping is not None and not task.source_mapping.matches]
    missing_mapping = [task for task in run.chapter_tasks if task.source_mapping is None]
    issues = [f"Missing source mapping for chapter: {task.title}" for task in missing_mapping[:20]]
    issues.extend(f"No reliable source match for chapter: {task.title}" for task in no_matches[:20])
    status: GateStatus = "passed" if not issues else ("pending" if len(mapped) == 0 else "warning")
    return PipelineGateStatus(
        name="mapping",
        status=status,
        summary=f"{len(mapped)}/{len(run.chapter_tasks)} chapter task(s) have source mapping.",
        issues=issues,
        next_actions=["Run source mapping or route unsupported chapters to human input/disablement."] if issues else [],
        metrics={"task_count": len(run.chapter_tasks), "mapped_count": len(mapped), "no_match_count": len(no_matches)},
    )


def _generation_gate(project: Project) -> PipelineGateStatus:
    run = project.runs[-1] if project.runs else None
    if run is None or not run.chapter_tasks:
        return PipelineGateStatus(
            name="generation",
            status="pending",
            summary="No generation run is available.",
            issues=["No chapter draft has been generated."],
            next_actions=["Generate all chapters or generate one chapter from the workspace."],
        )
    passed = [task for task in run.chapter_tasks if task.status.value == "passed"]
    failed = [task for task in run.chapter_tasks if task.status.value == "failed"]
    pending = [task for task in run.chapter_tasks if task.status.value in {"pending", "running", "needs_repair"}]
    issues = [f"Chapter not passed: {task.title} ({task.status.value})" for task in [*failed, *pending][:20]]
    if failed:
        status: GateStatus = "blocked"
    elif pending:
        status = "warning"
    else:
        status = "passed"
    return PipelineGateStatus(
        name="generation",
        status=status,
        summary=f"{len(passed)}/{len(run.chapter_tasks)} chapter task(s) passed.",
        issues=issues,
        next_actions=["Inspect failed chapters, repair format, remap sources, regenerate, or request human input."] if issues else [],
        metrics={"task_count": len(run.chapter_tasks), "passed_count": len(passed), "failed_count": len(failed), "pending_count": len(pending)},
    )


def _revision_gate(revision_decisions: list[dict] | None) -> PipelineGateStatus:
    if not revision_decisions:
        return PipelineGateStatus(
            name="revision",
            status="pending",
            summary="No revision decisions are available.",
            issues=["Generation revision audit has not run or has not been persisted."],
            next_actions=["Run generation validation and persist revision decisions."],
        )
    actionable = [item for item in revision_decisions if item.get("decision") != "accept"]
    errors = [item for item in actionable if item.get("severity") == "error"]
    warnings = [item for item in actionable if item.get("severity") == "warning"]
    issues = [
        f"{item.get('decision')} required for {item.get('title') or item.get('node_id')}: {', '.join(item.get('reasons') or [])}"
        for item in actionable[:20]
    ]
    status: GateStatus = "blocked" if errors else ("warning" if warnings else "passed")
    return PipelineGateStatus(
        name="revision",
        status=status,
        summary=f"{len(actionable)} actionable revision decision(s) out of {len(revision_decisions)}.",
        issues=issues,
        next_actions=["Apply revision actions before final merge."] if actionable else [],
        metrics={"decision_count": len(revision_decisions), "actionable_count": len(actionable), "error_count": len(errors), "warning_count": len(warnings)},
    )


def _quality_feedback_gate(quality_feedback: dict | None) -> PipelineGateStatus:
    if not quality_feedback:
        return PipelineGateStatus(
            name="quality_feedback",
            status="pending",
            summary="No post-generation quality feedback has been applied.",
            next_actions=["After comparing against source and human references, apply quality feedback to control the next run."],
        )
    actions = quality_feedback.get("actions") or []
    issues = [f"{item.get('action')}: {item.get('reason')}" for item in actions[:20]]
    status: GateStatus = "passed" if not actions else "warning"
    return PipelineGateStatus(
        name="quality_feedback",
        status=status,
        summary=f"{len(actions)} quality feedback action(s).",
        issues=issues,
        next_actions=["Apply outline repair, increase detail budgets, or strengthen evidence utilization before regeneration."] if actions else [],
        metrics={"action_count": len(actions)},
    )


def _version_gate(project: Project, *, template_tree: TemplateTree | None, workspace_store) -> PipelineGateStatus:
    run = project.runs[-1] if project.runs else None
    if workspace_store is None:
        return PipelineGateStatus(
            name="version",
            status="pending",
            summary="Workspace version store is not configured.",
            issues=["Chapter versions and selected versions cannot be verified."],
            next_actions=["Configure the database workspace store for versioned chapter editing."],
        )
    tree = template_tree or project.template_tree
    nodes = list(iter_template_nodes(tree.nodes)) if tree else []
    task_node_ids = {task.node_id for task in run.chapter_tasks} if run else {node.id for node in nodes if not node.children}
    selected_count = 0
    missing_selected: list[str] = []
    missing_source_nodes: list[str] = []
    weak_source_nodes: list[str] = []
    content_revision_nodes: list[str] = []
    content_revision_llm_count = 0
    content_revision_user_count = 0
    evidence_targeted_content_revision_count = 0
    missing_metadata_nodes: list[str] = []
    pattern_revision_nodes: list[str] = []
    pattern_revision_llm_count = 0
    pattern_revision_user_count = 0
    missing_evidence_audit_nodes: list[str] = []
    evidence_revision_nodes: list[str] = []
    evidence_revision_llm_count = 0
    for node_id in task_node_ids:
        try:
            workspace = workspace_store.get_workspace(project.id, node_id)
        except Exception:
            missing_selected.append(node_id)
            continue
        if workspace.get("selected_version_id"):
            selected_count += 1
            selected = _selected_workspace_version(workspace)
            status_counts = _content_tree_source_status_counts((selected or {}).get("content_tree"))
            if status_counts["missing"]:
                missing_source_nodes.append(f"{node_id}: {status_counts['missing']} missing subsection source link(s)")
            if status_counts["weak"]:
                weak_source_nodes.append(f"{node_id}: {status_counts['weak']} weak subsection source link(s)")
            revision_counts = _content_revision_plan_counts((selected or {}).get("content_revision_plan"))
            if revision_counts["actionable"]:
                content_revision_nodes.append(f"{node_id}: {revision_counts['actionable']} generated subsection revision action(s)")
                content_revision_llm_count += revision_counts["requires_llm"]
                content_revision_user_count += revision_counts["requires_user_confirmation"]
                evidence_targeted_content_revision_count += revision_counts["evidence_targeted_rewrite"]
            metadata_counts = _generation_metadata_pattern_counts(selected)
            if metadata_counts["missing_metadata"]:
                missing_metadata_nodes.append(node_id)
            if metadata_counts["actionable"]:
                pattern_revision_nodes.append(f"{node_id}: {metadata_counts['actionable']} local writing pattern revision action(s)")
                pattern_revision_llm_count += metadata_counts["requires_llm"]
                pattern_revision_user_count += metadata_counts["requires_user_confirmation"]
            evidence_counts = _evidence_utilization_counts(selected)
            if evidence_counts["missing_evidence_audit"]:
                missing_evidence_audit_nodes.append(node_id)
            if evidence_counts["actionable"]:
                evidence_revision_nodes.append(f"{node_id}: {evidence_counts['actionable']} evidence utilization revision action(s)")
                evidence_revision_llm_count += evidence_counts["requires_llm"]
        else:
            missing_selected.append(node_id)
    expected = len(task_node_ids)
    issues = [f"No selected chapter version for node: {node_id}" for node_id in missing_selected[:20]]
    issues.extend(f"Selected version has missing subsection sources for node {item}" for item in missing_source_nodes[:20])
    issues.extend(f"Selected version has weak subsection source links for node {item}" for item in weak_source_nodes[:20])
    issues.extend(f"Selected version has generated subsection revision actions for node {item}" for item in content_revision_nodes[:20])
    issues.extend(f"Selected version lacks generation metadata for node: {node_id}" for node_id in missing_metadata_nodes[:20])
    issues.extend(f"Selected version needs local writing pattern review for node {item}" for item in pattern_revision_nodes[:20])
    issues.extend(f"Selected version lacks evidence audit for node: {node_id}" for node_id in missing_evidence_audit_nodes[:20])
    issues.extend(f"Selected version needs evidence utilization review for node {item}" for item in evidence_revision_nodes[:20])
    status: GateStatus = (
        "passed"
        if expected
        and selected_count == expected
        and not missing_source_nodes
        and not weak_source_nodes
        and not content_revision_nodes
        and not missing_metadata_nodes
        and not pattern_revision_nodes
        and not missing_evidence_audit_nodes
        and not evidence_revision_nodes
        else ("pending" if not expected else "warning")
    )
    return PipelineGateStatus(
        name="version",
        status=status,
        summary=f"{selected_count}/{expected} chapter node(s) have selected versions.",
        issues=issues,
        next_actions=[
            "Generate, manually save, or select chapter versions before merging.",
            "Review selected version content trees; remap, rewrite, or manually explain missing subsection sources.",
        ] if issues else [],
        metrics={
            "expected_version_count": expected,
            "selected_version_count": selected_count,
            "selected_version_missing_source_subsections": sum(_parse_count(item) for item in missing_source_nodes),
            "selected_version_weak_source_subsections": sum(_parse_count(item) for item in weak_source_nodes),
            "selected_version_content_revision_actions": sum(_parse_count(item) for item in content_revision_nodes),
            "selected_version_content_revision_llm_actions": content_revision_llm_count,
            "selected_version_content_revision_user_actions": content_revision_user_count,
            "selected_version_evidence_targeted_content_revision_actions": evidence_targeted_content_revision_count,
            "selected_version_missing_generation_metadata": len(missing_metadata_nodes),
            "selected_version_pattern_revision_actions": sum(_parse_count(item) for item in pattern_revision_nodes),
            "selected_version_pattern_revision_llm_actions": pattern_revision_llm_count,
            "selected_version_pattern_revision_user_actions": pattern_revision_user_count,
            "selected_version_missing_evidence_audit": len(missing_evidence_audit_nodes),
            "selected_version_evidence_revision_actions": sum(_parse_count(item) for item in evidence_revision_nodes),
            "selected_version_evidence_revision_llm_actions": evidence_revision_llm_count,
        },
    )


def _merge_gate(project: Project, *, artifacts_root: Path | None) -> PipelineGateStatus:
    run = project.runs[-1] if project.runs else None
    path = run.final_artifact_path if run else None
    exists = _path_exists(path, artifacts_root)
    if exists:
        status: GateStatus = "passed"
        issues: list[str] = []
        actions: list[str] = []
    else:
        status = "pending"
        issues = ["Final merged markdown is not available."]
        actions = ["Merge selected chapter versions after generation and revision gates pass."]
    return PipelineGateStatus(
        name="merge",
        status=status,
        summary="Final document is available." if exists else "Final document has not been merged.",
        issues=issues,
        next_actions=actions,
        artifact_paths=_paths(path),
    )


def _overall_status(gates: list[PipelineGateStatus]) -> GateStatus:
    if any(gate.status == "blocked" for gate in gates):
        return "blocked"
    if any(gate.status == "warning" for gate in gates):
        return "warning"
    if any(gate.status == "pending" for gate in gates):
        return "pending"
    return "passed"


def _safe_list_outline_nodes(workspace_store, project_id: str) -> list[dict]:
    if workspace_store is None:
        return []
    try:
        return list(workspace_store.list_outline_nodes(project_id))
    except Exception:
        return []


def _path_exists(path: str | None, artifacts_root: Path | None) -> bool:
    if not path:
        return False
    candidate = Path(path)
    if candidate.exists():
        return True
    if artifacts_root is not None:
        return (artifacts_root / path).exists()
    return False


def _selected_workspace_version(workspace: dict) -> dict | None:
    selected_id = workspace.get("selected_version_id")
    for version in workspace.get("versions") or []:
        if version.get("id") == selected_id:
            return version
    return None


def _content_tree_source_status_counts(content_tree: dict | None) -> dict[str, int]:
    counts = {"missing": 0, "weak": 0}
    for node in _walk_content_tree_nodes((content_tree or {}).get("nodes") or []):
        status = node.get("source_status")
        if status in counts:
            counts[status] += 1
    return counts


def _content_revision_plan_counts(plan: dict | None) -> dict[str, int]:
    counts = {"actionable": 0, "requires_llm": 0, "requires_user_confirmation": 0, "evidence_targeted_rewrite": 0}
    metrics = (plan or {}).get("metrics") or {}
    metric_count = int(metrics.get("evidence_targeted_rewrite_count") or 0)
    reason_count = 0
    for item in (plan or {}).get("items") or []:
        if item.get("action") == "accept":
            continue
        counts["actionable"] += 1
        if item.get("requires_llm"):
            counts["requires_llm"] += 1
        if item.get("requires_user_confirmation"):
            counts["requires_user_confirmation"] += 1
        if "omitted_required_source_facts" in str(item.get("reason") or ""):
            reason_count += 1
    counts["evidence_targeted_rewrite"] = max(metric_count, reason_count)
    return counts


def _generation_metadata_pattern_counts(version: dict | None) -> dict[str, int]:
    counts = {"missing_metadata": 0, "actionable": 0, "requires_llm": 0, "requires_user_confirmation": 0}
    audit = audit_version_generation_metadata(version)
    metrics = audit.get("metrics") or {}
    if metrics.get("missing_metadata"):
        counts["missing_metadata"] = 1
    counts["actionable"] = int(metrics.get("actionable_count") or 0)
    counts["requires_llm"] = int(metrics.get("requires_llm_count") or 0)
    counts["requires_user_confirmation"] = int(metrics.get("requires_user_confirmation_count") or 0)
    return counts


def _evidence_utilization_counts(version: dict | None) -> dict[str, int]:
    counts = {"missing_evidence_audit": 0, "actionable": 0, "requires_llm": 0}
    audit = (version or {}).get("evidence_audit")
    if not audit:
        counts["missing_evidence_audit"] = 1
        return counts
    issues = [
        item
        for item in audit.get("issues") or []
        if item.get("suggested_action") and item.get("suggested_action") != "accept"
    ]
    counts["actionable"] = len(issues)
    counts["requires_llm"] = sum(1 for item in issues if item.get("suggested_action") in {"regenerate", "remap_sources", "repair_format"})
    return counts


def _walk_content_tree_nodes(nodes: list[dict]):
    for node in nodes:
        yield node
        yield from _walk_content_tree_nodes(node.get("children") or [])


def _parse_count(value: str) -> int:
    try:
        return int(value.split(":", 1)[1].strip().split(" ", 1)[0])
    except Exception:
        return 0


def _paths(*paths: str | None) -> list[str]:
    return [path for path in paths if path]


def _dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    output: list[str] = []
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        output.append(item)
    return output


def report_to_dict(report: PipelineGateReport) -> dict:
    return dump_model(report)
