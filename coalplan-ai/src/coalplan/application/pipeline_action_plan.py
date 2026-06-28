from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


ActionPriority = Literal["critical", "high", "normal", "low"]


class PipelineAction(BaseModel):
    action_id: str
    stage: str
    action: str
    priority: ActionPriority = "normal"
    title: str
    reason: str = ""
    target_id: str | None = None
    target_version_id: str | None = None
    target_content_node_id: str | None = None
    target_step_id: str | None = None
    method: str | None = None
    endpoint: str | None = None
    requires_llm: bool = False
    requires_user_confirmation: bool = False
    source_gate: str | None = None
    source_decision: str | None = None


class PipelineActionPlan(BaseModel):
    project_id: str
    overall_status: str
    actions: list[PipelineAction] = Field(default_factory=list)


def build_pipeline_action_plan(
    *,
    project_id: str,
    gate_report: dict,
    revision_decisions: list[dict] | None = None,
    version_content_targets: list[dict] | None = None,
    version_metadata_targets: list[dict] | None = None,
    version_evidence_targets: list[dict] | None = None,
    outline_step_targets: list[dict] | None = None,
    child_generation_targets: list[dict] | None = None,
) -> PipelineActionPlan:
    actions: list[PipelineAction] = []
    gates = {gate.get("name"): gate for gate in gate_report.get("gates", [])}
    actions.extend(
        _gate_actions(
            project_id,
            gates,
            version_content_targets or [],
            version_metadata_targets or [],
            version_evidence_targets or [],
            outline_step_targets or [],
            child_generation_targets or [],
        )
    )
    actions.extend(_revision_actions(project_id, revision_decisions or []))
    return PipelineActionPlan(
        project_id=project_id,
        overall_status=gate_report.get("overall_status") or "pending",
        actions=_dedupe_actions(sorted(actions, key=_action_sort_key)),
    )


def _gate_actions(
    project_id: str,
    gates: dict[str, dict],
    version_content_targets: list[dict],
    version_metadata_targets: list[dict],
    version_evidence_targets: list[dict],
    outline_step_targets: list[dict],
    child_generation_targets: list[dict],
) -> list[PipelineAction]:
    actions: list[PipelineAction] = []
    input_gate = gates.get("input") or {}
    if input_gate.get("status") in {"blocked", "pending"}:
        actions.append(
            PipelineAction(
                action_id="input.upload_bid_markdown",
                stage="input",
                action="upload_bid_markdown",
                priority="critical",
                title="上传并切分投标 Markdown",
                reason=_gate_reason(input_gate),
                method="POST",
                endpoint=f"/projects/{project_id}/bid-markdown",
                requires_user_confirmation=True,
                source_gate="input",
            )
        )
        return actions

    if (gates.get("profile") or {}).get("status") in {"pending", "blocked", "warning"}:
        actions.append(
            _project_action(
                project_id,
                "profile.prepare_directory",
                "profile",
                "prepare_directory",
                "生成或修复项目概况",
                "/directory",
                _gate_reason(gates.get("profile")),
                requires_llm=True,
            )
        )

    if (gates.get("outline") or {}).get("status") in {"pending", "blocked", "warning"}:
        actions.append(
            _project_action(
                project_id,
                "outline.prepare_directory",
                "outline",
                "prepare_directory",
                "生成基础目录并复制为可编辑目录",
                "/directory",
                _gate_reason(gates.get("outline")),
            )
        )

    if (gates.get("coverage") or {}).get("status") == "warning":
        actions.append(
            _project_action(
                project_id,
                "outline.control_plan_proposal",
                "coverage",
                "propose_outline_repair",
                "为缺失来源主题生成目录修补 proposal",
                "/outline/control-plan-proposal",
                _gate_reason(gates.get("coverage")),
                requires_user_confirmation=True,
            )
        )

    detail_gate = gates.get("detail") or {}
    if detail_gate.get("status") == "warning":
        actions.append(
            _project_action(
                project_id,
                "detail.estimate_word_counts",
                "detail",
                "estimate_word_counts",
                "估算章节目标字数",
                "/outline/word-counts/estimate",
                _gate_reason(detail_gate),
                requires_user_confirmation=True,
            )
        )
        if int((detail_gate.get("metrics") or {}).get("split_required_count") or 0) > 0:
            actions.append(
                _project_action(
                    project_id,
                    "detail.subsection_proposals",
                    "detail",
                    "propose_subsections",
                    "批量拆分高信息密度章节",
                    "/outline/subsection-proposals",
                    _gate_reason(detail_gate),
                    requires_user_confirmation=True,
                )
            )

    if (gates.get("mapping") or {}).get("status") in {"pending", "warning"}:
        actions.append(
            _project_action(
                project_id,
                "mapping.generate",
                "mapping",
                "generate_or_regenerate",
                "运行章节来源映射与生成",
                "/generate",
                _gate_reason(gates.get("mapping")),
                requires_llm=True,
            )
        )

    generation_gate = gates.get("generation") or {}
    if generation_gate.get("status") in {"pending", "warning", "blocked"}:
        if child_generation_targets:
            for target in child_generation_targets[:3]:
                parent_node_id = str(target.get("parent_node_id") or "")
                if not parent_node_id:
                    continue
                actions.append(
                    PipelineAction(
                        action_id=f"generation.child_branch.{parent_node_id}",
                        stage="generation",
                        action="generate_child_chapters",
                        priority="high",
                        title=f"{target.get('title') or 'Generate child chapters'}: {parent_node_id}",
                        reason=str(target.get("reason") or _gate_reason(generation_gate)),
                        target_id=parent_node_id,
                        method="POST",
                        endpoint=f"/projects/{project_id}/chapters/{parent_node_id}/children/generate",
                        requires_llm=True,
                        requires_user_confirmation=False,
                        source_gate="generation",
                    )
                )
        if outline_step_targets:
            for target in outline_step_targets[:3]:
                step_id = str(target.get("step_id") or "")
                if not step_id:
                    continue
                actions.append(
                    PipelineAction(
                        action_id=f"generation.outline_step.{step_id}",
                        stage="generation",
                        action="generate_outline_step",
                        priority="high",
                        title=f"{target.get('title') or '生成目录层级'}: {step_id}",
                        reason=str(target.get("reason") or _gate_reason(generation_gate)),
                        target_step_id=step_id,
                        method="POST",
                        endpoint=f"/projects/{project_id}/outline-generation-steps/{step_id}/generate",
                        requires_llm=True,
                        requires_user_confirmation=False,
                        source_gate="generation",
                    )
                )
        actions.append(
            _project_action(
                project_id,
                "generation.generate",
                "generation",
                "generate_chapters",
                "生成或修复未通过章节",
                "/generate",
                _gate_reason(generation_gate),
                priority="normal" if outline_step_targets or child_generation_targets else "high",
                requires_llm=True,
            )
        )

    actions.extend(_quality_feedback_actions(project_id, gates))

    version_gate = gates.get("version") or {}
    if version_gate.get("status") == "warning":
        metrics = version_gate.get("metrics") or {}
        missing = int(metrics.get("selected_version_missing_source_subsections") or 0)
        weak = int(metrics.get("selected_version_weak_source_subsections") or 0)
        content_actions = int(metrics.get("selected_version_content_revision_actions") or 0)
        content_llm_actions = int(metrics.get("selected_version_content_revision_llm_actions") or 0)
        missing_metadata = int(metrics.get("selected_version_missing_generation_metadata") or 0)
        pattern_actions = int(metrics.get("selected_version_pattern_revision_actions") or 0)
        pattern_llm_actions = int(metrics.get("selected_version_pattern_revision_llm_actions") or 0)
        missing_evidence_audit = int(metrics.get("selected_version_missing_evidence_audit") or 0)
        evidence_actions = int(metrics.get("selected_version_evidence_revision_actions") or 0)
        evidence_llm_actions = int(metrics.get("selected_version_evidence_revision_llm_actions") or 0)
        has_content_review = missing > 0 or weak > 0 or content_actions > 0
        has_pattern_review = missing_metadata > 0 or pattern_actions > 0
        has_evidence_review = missing_evidence_audit > 0 or evidence_actions > 0
        if has_content_review and version_content_targets:
            for target in version_content_targets:
                node_id = str(target.get("node_id") or "")
                version_id = str(target.get("version_id") or "")
                content_node_id = str(target.get("content_node_id") or "")
                action = str(target.get("action") or "review_content_tree_sources")
                evidence_targeted = bool(target.get("evidence_targeted"))
                reason = str(target.get("reason") or _gate_reason(version_gate))
                if evidence_targeted and "evidence-targeted" not in reason:
                    reason = f"evidence-targeted omitted source fact repair: {reason}"
                actions.append(
                    PipelineAction(
                        action_id=f"version.review_content_tree_sources.{node_id}.{version_id}.{content_node_id}",
                        stage="version",
                        action=action,
                        priority="high" if action in {"remap_sources", "review_source_link", "rewrite_subsection"} else "normal",
                        title=f"{target.get('title') or node_id}: {action}{' (evidence)' if evidence_targeted else ''}",
                        reason=reason,
                        target_id=node_id,
                        target_version_id=version_id,
                        target_content_node_id=content_node_id,
                        endpoint=(
                            f"/projects/{project_id}/chapters/{node_id}/versions/{version_id}"
                            f"/content-nodes/{content_node_id}/revision-action"
                        ),
                        method="POST",
                        requires_llm=bool(target.get("requires_llm")),
                        requires_user_confirmation=bool(target.get("requires_user_confirmation", True)),
                        source_gate="version",
                        source_decision=action,
                    )
                )
            has_content_review = False
        if has_content_review:
            actions.append(
                PipelineAction(
                    action_id="version.review_content_tree_sources",
                    stage="version",
                    action="review_content_tree_sources",
                    priority="high",
                    title="检查选中版本正文小节来源与修订动作",
                    reason=_gate_reason(version_gate),
                    endpoint=f"/projects/{project_id}/chapters/{{node_id}}/versions/{{version_id}}/content-revision-plan",
                    method="GET",
                    requires_llm=content_llm_actions > 0,
                    requires_user_confirmation=True,
                    source_gate="version",
                )
            )
        if has_pattern_review:
            if version_metadata_targets:
                for target in version_metadata_targets:
                    action = str(target.get("action") or "review_generation_metadata")
                    node_id = str(target.get("node_id") or "")
                    version_id = str(target.get("version_id") or "")
                    actions.append(
                        PipelineAction(
                            action_id=f"version.review_generation_metadata.{node_id}.{version_id}",
                            stage="version",
                            action=action,
                            priority="high" if action in {"regenerate", "repair_outline_coverage", "expand_subsections"} else "normal",
                            title=f"{target.get('title') or node_id}: review local writing pattern metadata",
                            reason=str(target.get("reason") or _gate_reason(version_gate)),
                            target_id=node_id,
                            target_version_id=version_id,
                            endpoint=(
                                f"/projects/{project_id}/chapters/{node_id}/versions/{version_id}"
                                "/generation-metadata/revision-action"
                            ),
                            method="POST",
                            requires_llm=bool(target.get("requires_llm")),
                            requires_user_confirmation=bool(target.get("requires_user_confirmation", True)),
                            source_gate="version",
                            source_decision=action,
                        )
                    )
            else:
                actions.append(
                    PipelineAction(
                        action_id="version.review_generation_metadata",
                        stage="version",
                        action="review_generation_metadata",
                        priority="high" if pattern_actions > 0 else "normal",
                        title="Review selected-version local writing pattern metadata",
                        reason=_gate_reason(version_gate),
                        endpoint=f"/projects/{project_id}/chapters/{{node_id}}/versions/{{version_id}}/generation-metadata",
                        method="GET",
                        requires_llm=pattern_llm_actions > 0,
                        requires_user_confirmation=True,
                        source_gate="version",
                    )
                )
        if has_evidence_review:
            if version_evidence_targets:
                for target in version_evidence_targets:
                    decision = str(target.get("action") or "review_evidence_utilization")
                    node_id = str(target.get("node_id") or "")
                    version_id = str(target.get("version_id") or "")
                    actions.append(
                        PipelineAction(
                            action_id=f"version.review_evidence_utilization.{node_id}.{version_id}",
                            stage="version",
                            action="review_evidence_utilization",
                            priority="high" if decision in {"regenerate", "remap_sources"} else "normal",
                            title=f"{target.get('title') or node_id}: review evidence utilization ({decision})",
                            reason=str(target.get("reason") or _gate_reason(version_gate)),
                            target_id=node_id,
                            target_version_id=version_id,
                            endpoint=f"/projects/{project_id}/chapters/{node_id}/versions/{version_id}/evidence-audit/revision-action",
                            method="POST",
                            requires_llm=bool(target.get("requires_llm")),
                            requires_user_confirmation=bool(target.get("requires_user_confirmation", True)),
                            source_gate="version",
                            source_decision=decision,
                        )
                    )
                has_evidence_review = False
            else:
                actions.append(
                    PipelineAction(
                        action_id="version.review_evidence_utilization",
                        stage="version",
                        action="review_evidence_utilization",
                        priority="high" if evidence_actions > 0 else "normal",
                        title="Review selected-version evidence utilization",
                        reason=_gate_reason(version_gate),
                        endpoint=f"/projects/{project_id}/chapters/{{node_id}}/versions/{{version_id}}/evidence-audit/revision-action",
                        method="POST",
                        requires_llm=evidence_llm_actions > 0,
                        requires_user_confirmation=True,
                        source_gate="version",
                    )
                )
        if not has_content_review and not has_pattern_review and not has_evidence_review:
            actions.append(
                PipelineAction(
                    action_id="version.select_versions",
                    stage="version",
                    action="select_versions",
                    priority="normal",
                    title="选择或保存章节版本",
                    reason=_gate_reason(version_gate),
                    requires_user_confirmation=True,
                    source_gate="version",
                )
            )

    if (gates.get("merge") or {}).get("status") == "pending" and _ready_for_merge(gates):
        actions.append(
            _project_action(
                project_id,
                "merge.final",
                "merge",
                "merge_final",
                "合并选中章节版本",
                "/merge",
                _gate_reason(gates.get("merge")),
                requires_user_confirmation=True,
            )
        )

    return actions


def _quality_feedback_actions(project_id: str, gates: dict[str, dict]) -> list[PipelineAction]:
    quality_gate = gates.get("quality_feedback") or {}
    status = quality_gate.get("status")
    if status == "pending" and (gates.get("generation") or {}).get("status") in {"passed", "warning"}:
        return [
            _project_action(
                project_id,
                "quality_feedback.run_quality_audit",
                "quality_feedback",
                "run_quality_audit",
                "运行项目级质量审计并生成反馈",
                "/quality-audit",
                _gate_reason(quality_gate),
                priority="high",
                requires_user_confirmation=True,
            ),
            _project_action(
                project_id,
                "quality_feedback.apply_audit_report",
                "quality_feedback",
                "apply_audit_feedback",
                "导入质量审计反馈",
                "/quality-feedback",
                _gate_reason(quality_gate),
                requires_user_confirmation=True,
            )
        ]
    if status != "warning":
        return []

    issues = [str(item) for item in quality_gate.get("issues") or []]
    issue_text = "\n".join(issues)
    actions: list[PipelineAction] = []
    actions.append(
        PipelineAction(
            action_id="quality_feedback.review_audit_revision_targets",
            stage="quality_feedback",
            action="run_quality_iteration",
            priority="normal",
            title="Run bounded quality-audit revision iteration",
            reason=_gate_reason(quality_gate),
            method="POST",
            endpoint=f"/projects/{project_id}/quality-iteration",
            requires_llm=True,
            requires_user_confirmation=False,
            source_gate="quality_feedback",
        )
    )
    if "repair_outline_coverage" in issue_text or "add_missing_common_topics" in issue_text:
        actions.append(
            _project_action(
                project_id,
                "quality_feedback.outline_repair_proposal",
                "quality_feedback",
                "propose_quality_outline_repair",
                "根据质量反馈生成目录修补 proposal",
                "/quality-feedback/outline-proposal",
                _gate_reason(quality_gate),
                requires_user_confirmation=True,
            )
        )
    if "increase_detail_budget" in issue_text:
        actions.append(
            PipelineAction(
                action_id="quality_feedback.review_detail_budget",
                stage="quality_feedback",
                action="review_detail_budget",
                priority="normal",
                title="复核质量反馈后的字数预算",
                reason=_gate_reason(quality_gate),
                requires_user_confirmation=True,
                source_gate="quality_feedback",
            )
        )
    if "strengthen_evidence_utilization" in issue_text or "traceability" in issue_text:
        actions.append(
            _project_action(
                project_id,
                "quality_feedback.remap_and_regenerate",
                "quality_feedback",
                "remap_and_regenerate_with_feedback",
                "按 trace/审计反馈重新映射并生成",
                "/generate",
                _gate_reason(quality_gate),
                priority="high",
                requires_llm=True,
            )
        )
    if not actions:
        actions.append(
            _project_action(
                project_id,
                "quality_feedback.regenerate_with_feedback",
                "quality_feedback",
                "regenerate_with_feedback",
                "按质量反馈重新生成",
                "/generate",
                _gate_reason(quality_gate),
                priority="high",
                requires_llm=True,
            )
        )
    return actions


def _revision_actions(project_id: str, decisions: list[dict]) -> list[PipelineAction]:
    actions: list[PipelineAction] = []
    for decision in decisions:
        action = decision.get("decision")
        if not action or action == "accept":
            continue
        node_id = decision.get("node_id")
        title = decision.get("title") or node_id or "未命名章节"
        actions.append(
            PipelineAction(
                action_id=f"revision.{node_id}.{action}",
                stage="revision",
                action=action,
                priority="high" if action in {"regenerate", "remap_sources", "repair_format"} else "normal",
                title=f"{title}: {action}",
                reason="；".join(decision.get("reasons") or decision.get("required_changes") or []),
                target_id=node_id,
                method="POST",
                endpoint=f"/projects/{project_id}/chapters/{node_id}/revision-action",
                requires_llm=action in {"regenerate", "remap_sources", "repair_format"},
                requires_user_confirmation=action in {"expand_subsections", "request_human_input", "disable_node"},
                source_gate="revision",
                source_decision=action,
            )
        )
    return actions


def _project_action(
    project_id: str,
    action_id: str,
    stage: str,
    action: str,
    title: str,
    endpoint_suffix: str,
    reason: str,
    *,
    priority: ActionPriority = "normal",
    requires_llm: bool = False,
    requires_user_confirmation: bool = False,
) -> PipelineAction:
    return PipelineAction(
        action_id=action_id,
        stage=stage,
        action=action,
        priority=priority,
        title=title,
        reason=reason,
        method="POST",
        endpoint=f"/projects/{project_id}{endpoint_suffix}",
        requires_llm=requires_llm,
        requires_user_confirmation=requires_user_confirmation,
        source_gate=stage,
    )


def _gate_reason(gate: dict | None) -> str:
    if not gate:
        return ""
    issues = gate.get("issues") or []
    if issues:
        return "；".join(str(item) for item in issues[:3])
    return str(gate.get("summary") or "")


def _ready_for_merge(gates: dict[str, dict]) -> bool:
    blockers = {"input", "profile", "outline", "mapping", "generation", "revision", "version"}
    return all((gates.get(name) or {}).get("status") == "passed" for name in blockers)


def _action_sort_key(action: PipelineAction) -> tuple[int, str, str]:
    priority_order = {"critical": 0, "high": 1, "normal": 2, "low": 3}
    stage_order = {
        "input": "00",
        "profile": "01",
        "outline": "02",
        "coverage": "03",
        "detail": "04",
        "mapping": "05",
        "generation": "06",
        "revision": "07",
        "quality_feedback": "08",
        "version": "09",
        "merge": "10",
    }
    return (priority_order.get(action.priority, 2), stage_order.get(action.stage, "99"), action.action_id)


def _dedupe_actions(actions: list[PipelineAction]) -> list[PipelineAction]:
    seen: set[str] = set()
    output: list[PipelineAction] = []
    for action in actions:
        if action.action_id in seen:
            continue
        seen.add(action.action_id)
        output.append(action)
    return output
