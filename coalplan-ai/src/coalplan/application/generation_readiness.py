from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from coalplan.domain.enums import TaskStatus
from coalplan.domain.generation import GenerationRun, Project
from coalplan.domain.generation_control import ChapterGenerationPolicy, GenerationControlPlan
from coalplan.domain.templates import TemplateNode, TemplateTree


ReadinessStatus = Literal[
    "structure_only",
    "has_children",
    "split_required",
    "needs_mapping",
    "needs_human_input",
    "ready_to_generate",
    "needs_revision",
    "ready_for_merge",
]


class GenerationReadinessNode(BaseModel):
    node_id: str
    parent_node_id: str | None = None
    title: str
    level: int
    has_children: bool = False
    has_generation_contract: bool = False
    status: ReadinessStatus
    next_action: str
    reason: str
    target_word_count: int | None = None
    detail_level: str | None = None
    split_required: bool = False
    mapping_status: str = "not_required"
    source_section_ids: list[str] = Field(default_factory=list)
    evidence_count: int = 0
    task_status: str | None = None
    selected_version_id: str | None = None
    revision_decision: str | None = None
    revision_severity: str | None = None
    revision_reasons: list[str] = Field(default_factory=list)
    required_changes: list[str] = Field(default_factory=list)
    requires_llm: bool = False
    requires_user_confirmation: bool = False
    endpoint: str | None = None


class GenerationReadinessBatchItem(BaseModel):
    node_id: str
    title: str
    status: ReadinessStatus
    next_action: str
    requires_llm: bool = False
    requires_user_confirmation: bool = False
    endpoint: str | None = None


class GenerationReadinessBatch(BaseModel):
    group_id: str
    title: str
    execution_mode: Literal["auto", "user_confirmation", "manual_review"] = "manual_review"
    reason: str = ""
    items: list[GenerationReadinessBatchItem] = Field(default_factory=list)


class GenerationReadinessReport(BaseModel):
    project_id: str
    status: str
    summary: str
    nodes: list[GenerationReadinessNode] = Field(default_factory=list)
    batches: list[GenerationReadinessBatch] = Field(default_factory=list)
    metrics: dict[str, int] = Field(default_factory=dict)


def build_generation_readiness_report(
    *,
    project: Project,
    template_tree: TemplateTree | None,
    control_plan: GenerationControlPlan | None = None,
    revision_decisions: list[dict] | None = None,
    generation_metadata_targets: list[dict] | None = None,
    workspace_store=None,
) -> GenerationReadinessReport:
    run = project.runs[-1] if project.runs else None
    policy_by_node = {policy.node_id: policy for policy in (control_plan.chapter_policies if control_plan else [])}
    task_by_node = {task.node_id: task for task in (run.chapter_tasks if run else [])}
    selected_versions = _selected_versions(project.id, template_tree, workspace_store)
    walk = list(_walk_nodes(template_tree.nodes if template_tree else []))
    task_by_node = {task.node_id: task for task in (run.chapter_tasks if run else [])}
    revision_by_node = _merge_revisions(
        _merge_revisions(
            _control_revision_by_node(
                control_plan=control_plan,
                walked_nodes=walk,
                task_by_node=task_by_node,
                selected_versions=selected_versions,
            ),
            _generation_metadata_revision_by_node(generation_metadata_targets or []),
        ),
        _revision_by_node(revision_decisions or []),
    )
    nodes = [
        _node_readiness(
            project_id=project.id,
            node=node,
            parent_node_id=parent_node_id,
            run=run,
            policy=policy_by_node.get(node.id),
            task=task_by_node.get(node.id),
            revision=revision_by_node.get(node.id),
            selected_version_id=selected_versions.get(node.id),
        )
        for parent_node_id, node in walk
    ]
    metrics = _metrics(nodes)
    batches = _batches(nodes)
    status = _status(metrics)
    summary = (
        f"{metrics['ready_to_generate']} ready, {metrics['needs_mapping']} need mapping, "
        f"{metrics['split_required']} need split, {metrics['needs_human_input']} need human input, "
        f"{metrics['ready_for_merge']} selected-version ready, "
        f"{sum(len(batch.items) for batch in batches if batch.execution_mode == 'auto')} auto-runnable."
    )
    return GenerationReadinessReport(project_id=project.id, status=status, summary=summary, nodes=nodes, batches=batches, metrics=metrics)


def render_generation_readiness_markdown(report: GenerationReadinessReport) -> str:
    lines = [
        "# Generation Readiness",
        "",
        f"- project_id: `{report.project_id}`",
        f"- status: `{report.status}`",
        f"- summary: {report.summary}",
        "",
        "## Metrics",
        "",
        *[f"- {key}: {value}" for key, value in sorted(report.metrics.items())],
        "",
        "## Nodes",
        "",
    ]
    if report.batches:
        lines.extend(["## Batches", ""])
        for batch in report.batches:
            lines.extend(
                [
                    f"### {batch.title}",
                    "",
                    f"- group_id: `{batch.group_id}`",
                    f"- execution_mode: `{batch.execution_mode}`",
                    f"- reason: {batch.reason}",
                    f"- item_count: {len(batch.items)}",
                    "",
                ]
            )
            for item in batch.items:
                lines.append(f"- `{item.node_id}` {item.title}: `{item.next_action}` / `{item.status}`")
            lines.append("")
    for item in report.nodes:
        indent = "  " * max(0, item.level - 1)
        sources = ", ".join(item.source_section_ids) if item.source_section_ids else "-"
        lines.extend(
            [
                f"{indent}- `{item.node_id}` {item.title}",
                f"{indent}  - status: `{item.status}`",
                f"{indent}  - next_action: `{item.next_action}`",
                f"{indent}  - reason: {item.reason}",
                f"{indent}  - mapping: `{item.mapping_status}`; sources: {sources}; evidence: {item.evidence_count}",
                f"{indent}  - selected_version_id: `{item.selected_version_id or '-'}`",
            ]
        )
        if item.revision_decision:
            lines.extend(
                [
                    f"{indent}  - revision_decision: `{item.revision_decision}` / `{item.revision_severity or '-'}`",
                    f"{indent}  - revision_reasons: {'; '.join(item.revision_reasons) if item.revision_reasons else '-'}",
                ]
            )
    return "\n".join(lines).strip() + "\n"


def _node_readiness(
    *,
    project_id: str,
    node: TemplateNode,
    parent_node_id: str | None,
    run: GenerationRun | None,
    policy: ChapterGenerationPolicy | None,
    task,
    revision: dict | None,
    selected_version_id: str | None,
) -> GenerationReadinessNode:
    has_children = bool(node.children)
    has_contract = node.has_generation_contract
    mapping_status, source_section_ids, evidence_count = _mapping_summary(task)
    task_status = task.status.value if task else None
    base = {
        "node_id": node.id,
        "parent_node_id": parent_node_id,
        "title": node.title,
        "level": node.level,
        "has_children": has_children,
        "has_generation_contract": has_contract,
        "target_word_count": node.target_word_count or (policy.target_word_count if policy else None),
        "detail_level": policy.detail_level if policy else None,
        "split_required": bool(policy and policy.split_required),
        "mapping_status": mapping_status,
        "source_section_ids": source_section_ids,
        "evidence_count": evidence_count,
        "task_status": task_status,
        "selected_version_id": selected_version_id,
        "revision_decision": revision.get("decision") if revision else None,
        "revision_severity": revision.get("severity") if revision else None,
        "revision_reasons": [str(item) for item in (revision.get("reasons") or [])] if revision else [],
        "required_changes": [str(item) for item in (revision.get("required_changes") or [])] if revision else [],
    }
    if not has_contract and not has_children:
        return GenerationReadinessNode(
            **base,
            status="structure_only",
            next_action="skip",
            reason="This node has no generation modules and only acts as outline structure.",
        )
    if policy and policy.split_required and not has_children:
        return GenerationReadinessNode(
            **base,
            status="split_required",
            next_action="propose_subsections",
            reason="Dense craft or implementation chapter should be split before factual writing.",
            requires_llm=True,
            requires_user_confirmation=True,
            endpoint=f"/projects/{project_id}/chapters/{node.id}/subsections/propose",
        )
    if has_children:
        return GenerationReadinessNode(
            **base,
            status="has_children",
            next_action="generate_child_chapters",
            reason="Generate and review child chapters branch-by-branch before merging this outline branch.",
            requires_llm=True,
            endpoint=f"/projects/{project_id}/chapters/{node.id}/children/generate",
        )
    revision_action = str(revision.get("decision") or "") if revision else ""
    if revision_action and revision_action != "accept":
        if revision_action == "expand_subsections":
            return GenerationReadinessNode(
                **base,
                status="split_required",
                next_action=revision_action,
                reason=_revision_reason(revision, "Revision decision requires splitting this chapter before retrying generation."),
                requires_llm=True,
                requires_user_confirmation=True,
                endpoint=f"/projects/{project_id}/chapters/{node.id}/revision-action",
            )
        if revision_action in {"request_human_input", "disable_node"}:
            return GenerationReadinessNode(
                **base,
                status="needs_human_input",
                next_action=revision_action,
                reason=_revision_reason(revision, "Revision decision requires user input or node disablement before factual writing."),
                requires_user_confirmation=True,
                endpoint=f"/projects/{project_id}/chapters/{node.id}/revision-action",
            )
        return GenerationReadinessNode(
            **base,
            status="needs_revision",
            next_action=revision_action,
            reason=_revision_reason(revision, "Revision decision requires a controlled retry."),
            requires_llm=revision_action in {"regenerate", "remap_sources", "repair_format"},
            requires_user_confirmation=False,
            endpoint=f"/projects/{project_id}/chapters/{node.id}/revision-action",
        )
    if selected_version_id and task_status == TaskStatus.passed.value:
        return GenerationReadinessNode(
            **base,
            status="ready_for_merge",
            next_action="review_or_merge",
            reason="A selected passed version exists for this leaf chapter.",
        )
    if task_status in {TaskStatus.failed.value, TaskStatus.needs_repair.value}:
        if mapping_status == "no_reliable_source":
            return GenerationReadinessNode(
                **base,
                status="needs_human_input",
                next_action="add_supplement_or_disable",
                reason="Generation was blocked because no reliable source mapping supports factual writing.",
                requires_user_confirmation=True,
                endpoint=f"/projects/{project_id}/chapters/{node.id}/workspace",
            )
        return GenerationReadinessNode(
            **base,
            status="needs_revision",
            next_action="execute_revision_action",
            reason=f"Chapter task status is {task_status}; inspect revision decision before retrying.",
            requires_llm=True,
            endpoint=f"/projects/{project_id}/chapters/{node.id}/revision-action",
        )
    if mapping_status == "no_reliable_source":
        return GenerationReadinessNode(
            **base,
            status="needs_human_input",
            next_action="add_supplement_or_disable",
            reason="Source mapping exists but has no reliable matches; do not generate factual prose yet.",
            requires_user_confirmation=True,
            endpoint=f"/projects/{project_id}/chapters/{node.id}/workspace",
        )
    if mapping_status == "mapped":
        return GenerationReadinessNode(
            **base,
            status="ready_to_generate",
            next_action="generate_chapter",
            reason="Source mapping and evidence are available; generate or regenerate this leaf chapter.",
            requires_llm=True,
            endpoint=f"/projects/{project_id}/chapters/{node.id}/generate",
        )
    return GenerationReadinessNode(
        **base,
        status="needs_mapping",
        next_action="map_sources_then_generate",
        reason="No persisted source mapping is available for this leaf chapter.",
        requires_llm=True,
        endpoint=f"/projects/{project_id}/chapters/{node.id}/generate",
    )


def _mapping_summary(task) -> tuple[str, list[str], int]:
    if task is None or task.source_mapping is None:
        source_ids = [match.section_id for match in (task.source_matches if task else [])]
        return ("mapped" if source_ids else "not_mapped"), source_ids, 0
    if not task.source_mapping.matches:
        return "no_reliable_source", [], len(task.source_mapping.evidence)
    source_ids = [match.section_id for match in task.source_mapping.matches]
    return "mapped", source_ids, len(task.source_mapping.evidence)


def _revision_by_node(decisions: list[dict]) -> dict[str, dict]:
    output: dict[str, dict] = {}
    for decision in decisions:
        node_id = str(decision.get("node_id") or "")
        if not node_id:
            continue
        output[node_id] = decision
    return output


def _generation_metadata_revision_by_node(targets: list[dict]) -> dict[str, dict]:
    output: dict[str, dict] = {}
    for target in targets:
        node_id = str(target.get("node_id") or "")
        action = str(target.get("action") or "")
        if not node_id or not action or action == "accept":
            continue
        decision_action = "expand_subsections" if action == "repair_outline_coverage" else action
        decision = {
            "node_id": node_id,
            "title": str(target.get("title") or node_id),
            "decision": decision_action,
            "severity": "warning",
            "reasons": [
                str(target.get("reason") or "Selected version has local writing-pattern metadata issues."),
            ],
            "required_changes": [
                *[str(item) for item in target.get("next_actions") or []],
                *[
                    _metadata_audit_label(item)
                    for item in [
                        *(target.get("pattern_audits") or []),
                        *(target.get("prompt_card_audits") or []),
                    ]
                ],
            ],
        }
        output[node_id] = _stronger_revision(output.get(node_id), decision) if node_id in output else decision
    return output


def _metadata_audit_label(item: dict) -> str:
    if not isinstance(item, dict):
        return str(item)
    key = item.get("pattern_key") or item.get("key") or "-"
    action = item.get("suggested_action") or "-"
    coverage = item.get("coverage_ratio")
    missing = item.get("missing_points") or item.get("missing_requirements") or []
    missing_text = "; ".join(str(value) for value in missing[:3])
    suffix = f"; missing={missing_text}" if missing_text else ""
    return f"pattern={key}; action={action}; coverage={coverage if coverage is not None else '-'}{suffix}"


def _control_revision_by_node(
    *,
    control_plan: GenerationControlPlan | None,
    walked_nodes: list[tuple[str | None, TemplateNode]],
    task_by_node: dict[str, object],
    selected_versions: dict[str, str | None],
) -> dict[str, dict]:
    if control_plan is None or not control_plan.revision_triggers:
        return {}
    node_by_id = {node.id: node for _, node in walked_nodes}
    output: dict[str, dict] = {}
    for trigger in control_plan.revision_triggers:
        target_node_ids = _revision_trigger_targets(trigger.node_id, walked_nodes, task_by_node, selected_versions)
        for node_id in target_node_ids:
            node = node_by_id.get(node_id)
            if node is None:
                continue
            existing = output.get(node_id)
            decision = {
                "node_id": node_id,
                "title": node.title,
                "decision": trigger.action,
                "severity": trigger.severity,
                "reasons": [trigger.reason],
                "required_changes": [str(item) for item in trigger.evidence],
            }
            output[node_id] = _stronger_revision(existing, decision) if existing else decision
    return output


def _revision_trigger_targets(
    trigger_node_id: str,
    walked_nodes: list[tuple[str | None, TemplateNode]],
    task_by_node: dict[str, object],
    selected_versions: dict[str, str | None],
) -> list[str]:
    node_ids = [node.id for _, node in walked_nodes]
    if trigger_node_id in node_ids:
        return [trigger_node_id]
    if trigger_node_id != "all_chapters":
        return []
    targets: list[str] = []
    for _, node in walked_nodes:
        if node.children or not node.has_generation_contract:
            continue
        task = task_by_node.get(node.id)
        task_status = getattr(getattr(task, "status", None), "value", getattr(task, "status", None))
        if selected_versions.get(node.id) or task_status == TaskStatus.passed.value:
            targets.append(node.id)
    return targets


def _merge_revisions(left: dict[str, dict], right: dict[str, dict]) -> dict[str, dict]:
    output = dict(left)
    for node_id, decision in right.items():
        output[node_id] = _stronger_revision(output.get(node_id), decision) if node_id in output else decision
    return output


def _stronger_revision(left: dict | None, right: dict) -> dict:
    if left is None:
        return right
    severity_order = {"info": 0, "warning": 1, "error": 2}
    left_severity = severity_order.get(str(left.get("severity") or "info"), 0)
    right_severity = severity_order.get(str(right.get("severity") or "info"), 0)
    primary = right if right_severity >= left_severity else left
    secondary = left if primary is right else right
    merged = dict(primary)
    merged["reasons"] = _dedupe_strings([*(primary.get("reasons") or []), *(secondary.get("reasons") or [])])
    merged["required_changes"] = _dedupe_strings(
        [*(primary.get("required_changes") or []), *(secondary.get("required_changes") or [])]
    )
    return merged


def _dedupe_strings(items: list) -> list[str]:
    output: list[str] = []
    seen: set[str] = set()
    for item in items:
        text = str(item).strip()
        if not text or text in seen:
            continue
        seen.add(text)
        output.append(text)
    return output


def _revision_reason(revision: dict | None, fallback: str) -> str:
    if not revision:
        return fallback
    parts = [str(item) for item in [*(revision.get("reasons") or []), *(revision.get("required_changes") or [])] if str(item).strip()]
    return " ".join(parts[:3]) if parts else fallback


def _walk_nodes(nodes: list[TemplateNode], parent_node_id: str | None = None):
    for node in nodes:
        yield parent_node_id, node
        yield from _walk_nodes(node.children, node.id)


def _selected_versions(project_id: str, template_tree: TemplateTree | None, workspace_store) -> dict[str, str | None]:
    if workspace_store is None or template_tree is None:
        return {}
    output: dict[str, str | None] = {}
    for _, node in _walk_nodes(template_tree.nodes):
        try:
            workspace = workspace_store.get_workspace(project_id, node.id)
        except Exception:
            continue
        output[node.id] = workspace.get("selected_version_id")
    return output


def _metrics(nodes: list[GenerationReadinessNode]) -> dict[str, int]:
    metrics = {
        "total": len(nodes),
        "structure_only": 0,
        "has_children": 0,
        "split_required": 0,
        "needs_mapping": 0,
        "needs_human_input": 0,
        "ready_to_generate": 0,
        "needs_revision": 0,
        "ready_for_merge": 0,
        "requires_llm": 0,
        "requires_user_confirmation": 0,
        "auto_runnable": 0,
    }
    for item in nodes:
        metrics[item.status] += 1
        if item.requires_llm:
            metrics["requires_llm"] += 1
        if item.requires_user_confirmation:
            metrics["requires_user_confirmation"] += 1
        if _auto_runnable(item):
            metrics["auto_runnable"] += 1
    return metrics


def _batches(nodes: list[GenerationReadinessNode]) -> list[GenerationReadinessBatch]:
    auto_items = [_batch_item(item) for item in nodes if _auto_generation(item)]
    revision_items = [_batch_item(item) for item in nodes if _auto_revision(item)]
    user_items = [_batch_item(item) for item in nodes if item.requires_user_confirmation]
    merge_items = [_batch_item(item) for item in nodes if item.status == "ready_for_merge"]
    structure_items = [_batch_item(item) for item in nodes if item.status == "structure_only"]
    batches = [
        GenerationReadinessBatch(
            group_id="auto_generation",
            title="Auto-runnable mapping/generation",
            execution_mode="auto",
            reason="Leaf chapters and child branches that can run through existing mapping and generation endpoints without extra user confirmation.",
            items=auto_items,
        ),
        GenerationReadinessBatch(
            group_id="auto_revision",
            title="Auto-runnable LLM revisions",
            execution_mode="auto",
            reason="Open revision decisions such as regenerate, remap_sources, or repair_format that can be executed with persisted revision context.",
            items=revision_items,
        ),
        GenerationReadinessBatch(
            group_id="user_confirmation",
            title="Needs user confirmation or supplements",
            execution_mode="user_confirmation",
            reason="Splits, human-input requests, and disable decisions must pause for user review before factual generation continues.",
            items=user_items,
        ),
        GenerationReadinessBatch(
            group_id="merge_review",
            title="Selected versions ready for merge review",
            execution_mode="manual_review",
            reason="These nodes have selected passed versions; review evidence and version gates before final merge.",
            items=merge_items,
        ),
        GenerationReadinessBatch(
            group_id="structure_only",
            title="Structure-only outline nodes",
            execution_mode="manual_review",
            reason="Container headings with no generation contract are kept as structure and should not call the LLM for factual text.",
            items=structure_items,
        ),
    ]
    return [batch for batch in batches if batch.items]


def _batch_item(item: GenerationReadinessNode) -> GenerationReadinessBatchItem:
    return GenerationReadinessBatchItem(
        node_id=item.node_id,
        title=item.title,
        status=item.status,
        next_action=item.revision_decision if item.revision_decision and item.revision_decision != "accept" else item.next_action,
        requires_llm=item.requires_llm,
        requires_user_confirmation=item.requires_user_confirmation,
        endpoint=item.endpoint,
    )


def _auto_generation(item: GenerationReadinessNode) -> bool:
    return (
        not item.requires_user_confirmation
        and item.revision_decision in {None, "", "accept"}
        and item.next_action in {"generate_chapter", "map_sources_then_generate", "generate_child_chapters"}
    )


def _auto_revision(item: GenerationReadinessNode) -> bool:
    action = item.revision_decision if item.revision_decision and item.revision_decision != "accept" else item.next_action
    return not item.requires_user_confirmation and action in {"regenerate", "remap_sources", "repair_format"}


def _auto_runnable(item: GenerationReadinessNode) -> bool:
    return _auto_generation(item) or _auto_revision(item)


def _status(metrics: dict[str, int]) -> str:
    if metrics["needs_human_input"] or metrics["split_required"]:
        return "waiting_for_user"
    if metrics["needs_revision"]:
        return "revision_required"
    if metrics["needs_mapping"] or metrics["ready_to_generate"] or metrics["has_children"]:
        return "generation_required"
    if metrics["ready_for_merge"]:
        return "ready_for_merge"
    return "pending"
