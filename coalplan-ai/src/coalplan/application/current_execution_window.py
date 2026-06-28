from __future__ import annotations

from pydantic import BaseModel, Field


class ExecutionWindowAction(BaseModel):
    action_id: str
    phase_id: str
    stage: str
    action: str
    priority: str = "normal"
    title: str
    reason: str = ""
    method: str | None = None
    endpoint: str | None = None
    target_id: str | None = None
    proposal_id: str | None = None
    proposal_status: str | None = None
    proposal_created_at: str | None = None
    requires_llm: bool = False
    requires_user_confirmation: bool = False
    blocked_by_phase_id: str | None = None
    blocked_reason: str | None = None


class CurrentExecutionWindow(BaseModel):
    project_id: str
    status: str
    current_phase_id: str | None = None
    current_phase_title: str | None = None
    blocking_reason: str = ""
    allowed_actions: list[ExecutionWindowAction] = Field(default_factory=list)
    deferred_actions: list[ExecutionWindowAction] = Field(default_factory=list)
    requires_llm_count: int = 0
    requires_user_confirmation_count: int = 0


def build_current_execution_window(iteration_plan: dict, *, pending_proposals: list[dict] | None = None) -> CurrentExecutionWindow:
    phases = iteration_plan.get("phases") or []
    project_id = str(iteration_plan.get("project_id") or "")
    pending_outline_proposal = _pending_outline_proposal(pending_proposals or [])
    if pending_outline_proposal is not None:
        return _pending_outline_proposal_window(
            project_id=project_id,
            proposal=pending_outline_proposal,
            phases=phases,
        )
    current = next((phase for phase in phases if phase.get("actions")), None)
    allowed: list[ExecutionWindowAction] = []
    deferred: list[ExecutionWindowAction] = []
    if current is None:
        return CurrentExecutionWindow(
            project_id=project_id,
            status="complete" if iteration_plan.get("status") == "ready_to_merge_or_complete" else "idle",
            blocking_reason="No pending action is available in the current iteration plan.",
        )

    current_phase_id = str(current.get("phase_id") or "")
    current_blocks = bool(current.get("blocks_later_phases"))
    current_reason = _blocking_reason(current)
    for phase in phases:
        phase_id = str(phase.get("phase_id") or "")
        for action in phase.get("actions") or []:
            item = _action_item(action, phase_id=phase_id)
            if phase_id == current_phase_id:
                allowed.append(item)
            else:
                item.blocked_by_phase_id = current_phase_id
                item.blocked_reason = current_reason if current_blocks else f"Execute phase `{current_phase_id}` before later phases."
                deferred.append(item)

    return CurrentExecutionWindow(
        project_id=project_id,
        status="waiting_for_user" if any(item.requires_user_confirmation for item in allowed) else "auto_runnable",
        current_phase_id=current_phase_id,
        current_phase_title=str(current.get("title") or ""),
        blocking_reason=current_reason,
        allowed_actions=allowed,
        deferred_actions=deferred,
        requires_llm_count=sum(1 for item in allowed if item.requires_llm),
        requires_user_confirmation_count=sum(1 for item in allowed if item.requires_user_confirmation),
    )


def render_current_execution_window_markdown(window: CurrentExecutionWindow) -> str:
    lines = [
        "# Current Execution Window",
        "",
        f"- project_id: `{window.project_id}`",
        f"- status: `{window.status}`",
        f"- current_phase_id: `{window.current_phase_id or '-'}`",
        f"- current_phase_title: {window.current_phase_title or '-'}",
        f"- requires_llm_count: {window.requires_llm_count}",
        f"- requires_user_confirmation_count: {window.requires_user_confirmation_count}",
        "",
        "## Blocking Reason",
        "",
        window.blocking_reason or "-",
        "",
        "## Allowed Now",
        "",
    ]
    lines.extend(_render_actions(window.allowed_actions, include_blocker=False))
    lines.extend(["", "## Deferred Until Current Phase Clears", ""])
    lines.extend(_render_actions(window.deferred_actions, include_blocker=True))
    return "\n".join(lines).rstrip() + "\n"


def _action_item(action: dict, *, phase_id: str) -> ExecutionWindowAction:
    return ExecutionWindowAction(
        action_id=str(action.get("action_id") or ""),
        phase_id=phase_id,
        stage=str(action.get("stage") or ""),
        action=str(action.get("action") or ""),
        priority=str(action.get("priority") or "normal"),
        title=str(action.get("title") or ""),
        reason=str(action.get("reason") or ""),
        method=action.get("method"),
        endpoint=action.get("endpoint"),
        target_id=action.get("target_id"),
        proposal_id=action.get("proposal_id"),
        proposal_status=action.get("proposal_status"),
        proposal_created_at=action.get("proposal_created_at"),
        requires_llm=bool(action.get("requires_llm")),
        requires_user_confirmation=bool(action.get("requires_user_confirmation")),
    )


def _with_pending_proposal(action: ExecutionWindowAction, proposals: list[dict], *, project_id: str) -> ExecutionWindowAction:
    if action.action_id not in {"outline.pending_proposal", "outline.control_plan_proposal", "quality_feedback.outline_repair_proposal", "detail.subsection_proposals"}:
        return action
    proposal = next((item for item in proposals if item.get("target_type") == "outline" and item.get("status") == "pending"), None)
    if proposal is None:
        return action
    action.action_id = f"outline.apply_pending_proposal.{proposal.get('id')}"
    action.action = "apply_pending_outline_proposal"
    action.title = "审阅并应用待确认目录 proposal"
    action.reason = f"已有待确认 outline proposal：{proposal.get('suggestion') or '-'}"
    action.method = "POST"
    action.endpoint = f"/projects/{project_id}/outline/proposals/{proposal.get('id')}/apply"
    action.target_id = str(proposal.get("target_id") or project_id)
    action.proposal_id = str(proposal.get("id") or "")
    action.proposal_status = str(proposal.get("status") or "")
    action.proposal_created_at = proposal.get("created_at")
    action.requires_llm = False
    action.requires_user_confirmation = True
    return action


def _pending_outline_proposal(proposals: list[dict]) -> dict | None:
    return next((item for item in proposals if item.get("target_type") == "outline" and item.get("status") == "pending"), None)


def _pending_outline_proposal_window(*, project_id: str, proposal: dict, phases: list[dict]) -> CurrentExecutionWindow:
    action = _with_pending_proposal(
        ExecutionWindowAction(
            action_id="outline.pending_proposal",
            phase_id="outline_detail",
            stage="coverage",
            action="review_outline_proposal",
            priority="normal",
            title="Review pending outline proposal",
            reason=str(proposal.get("suggestion") or ""),
            requires_user_confirmation=True,
        ),
        [proposal],
        project_id=project_id,
    )
    deferred: list[ExecutionWindowAction] = []
    blocked_reason = (
        "Pending editable outline proposal must be reviewed and applied before source mapping, chapter generation, "
        "revision, version selection, or merge."
    )
    for phase in phases:
        phase_id = str(phase.get("phase_id") or "")
        for raw_action in phase.get("actions") or []:
            item = _action_item(raw_action, phase_id=phase_id)
            if item.action_id == action.action_id:
                continue
            item.blocked_by_phase_id = "outline_detail"
            item.blocked_reason = blocked_reason
            deferred.append(item)
    return CurrentExecutionWindow(
        project_id=project_id,
        status="waiting_for_user",
        current_phase_id="outline_detail",
        current_phase_title="Review pending outline proposal",
        blocking_reason=blocked_reason,
        allowed_actions=[action],
        deferred_actions=deferred,
        requires_llm_count=0,
        requires_user_confirmation_count=1,
    )


def _blocking_reason(phase: dict) -> str:
    stop_conditions = [str(item) for item in (phase.get("stop_conditions") or [])]
    if stop_conditions:
        return " ".join(stop_conditions)
    if phase.get("blocks_later_phases"):
        return "This phase blocks later phases until its user-confirmed actions are handled."
    return "Execute the current phase before later phases."


def _render_actions(actions: list[ExecutionWindowAction], *, include_blocker: bool) -> list[str]:
    if not actions:
        return ["- -"]
    lines: list[str] = []
    for action in actions:
        endpoint = f" `{action.method or 'GET'} {action.endpoint}`" if action.endpoint else ""
        markers = []
        if action.requires_user_confirmation:
            markers.append("requires user confirmation")
        if action.requires_llm:
            markers.append("requires LLM")
        marker_text = f" ({'; '.join(markers)})" if markers else ""
        target = f" target=`{action.target_id}`" if action.target_id else ""
        proposal = f" proposal=`{action.proposal_id}`" if action.proposal_id else ""
        lines.append(f"- `{action.action_id}` [{action.priority}] {action.title}{endpoint}{target}{proposal}{marker_text}")
        if include_blocker and action.blocked_reason:
            lines.append(f"  - deferred: {action.blocked_reason}")
        elif action.reason:
            lines.append(f"  - reason: {action.reason}")
    return lines
