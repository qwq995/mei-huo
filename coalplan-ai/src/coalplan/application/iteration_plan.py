from __future__ import annotations

from collections import defaultdict

from pydantic import BaseModel, Field

from coalplan.application.pipeline_action_plan import PipelineAction, PipelineActionPlan


class IterationPhase(BaseModel):
    phase_id: str
    step: int
    title: str
    objective: str
    actions: list[PipelineAction] = Field(default_factory=list)
    gate_to_clear: str | None = None
    success_artifacts: list[str] = Field(default_factory=list)
    stop_conditions: list[str] = Field(default_factory=list)
    blocks_later_phases: bool = False
    requires_llm_count: int = 0
    requires_user_confirmation_count: int = 0


class IterationPlan(BaseModel):
    project_id: str
    status: str
    summary: str
    phases: list[IterationPhase] = Field(default_factory=list)
    next_phase_id: str | None = None
    requires_llm_count: int = 0
    requires_user_confirmation_count: int = 0


_PHASES = {
    "input_profile": {
        "step": 1,
        "title": "Prepare input, sections, and project profile",
        "objective": "Persist the bid Markdown, source TOC, section files, and project profile before any factual generation.",
        "stages": {"input", "profile"},
        "gate": "profile",
        "artifacts": [
            "inputs/bid.normalized.md",
            "inputs/sections.json",
            "inputs/toc.json",
            "profile/project_profile.json",
        ],
    },
    "outline_detail": {
        "step": 2,
        "title": "Repair editable outline and detail budget",
        "objective": "Create a project-owned outline, add missing source-derived topics, split dense craft nodes, and set word-count targets.",
        "stages": {"outline", "coverage", "detail"},
        "gate": "detail",
        "artifacts": [
            "outline/generated_outline.json",
            "control/generation_control_plan.json",
            "outline/word_count_targets.json",
        ],
    },
    "mapping_generation": {
        "step": 3,
        "title": "Map sources and generate chapter versions",
        "objective": "Map every active outline node to real source sections, extract evidence, then generate validated chapter Markdown versions.",
        "stages": {"mapping", "generation"},
        "gate": "generation",
        "artifacts": [
            "mapping/{node_id}.json",
            "chapters/{node_id}.md",
            "runs/{run_id}/validation.json",
        ],
    },
    "revision": {
        "step": 4,
        "title": "Revise failed or weak chapters",
        "objective": "Use revision decisions to repair format, remap sources, split subsections, regenerate, or request human input.",
        "stages": {"revision"},
        "gate": "revision",
        "artifacts": [
            "control/revision_decisions.json",
            "outline proposals",
            "new chapter_versions",
        ],
    },
    "quality_feedback": {
        "step": 5,
        "title": "Apply quality and organization feedback",
        "objective": "Convert quality-audit gaps into outline repair, evidence remapping, detail-budget updates, and regeneration context.",
        "stages": {"quality_feedback"},
        "gate": "quality_feedback",
        "artifacts": [
            "control/quality_feedback_plan.json",
            "control/generation_control_plan.json",
            "outline proposals",
        ],
    },
    "version_review": {
        "step": 6,
        "title": "Review selected versions, evidence, and generated subsections",
        "objective": "Resolve selected-version evidence audits, generated subsection revision plans, local writing-pattern metadata, and version selection before final merge.",
        "stages": {"version"},
        "gate": "version",
        "artifacts": [
            "chapter_versions",
            "chapters/{node_id}/versions/{version_id}.evidence_audit.json",
            "chapters/{node_id}/versions/{version_id}.content_revision_plan.json",
            "chapters/{node_id}/versions/{version_id}.generation_metadata.json",
        ],
    },
    "version_merge": {
        "step": 7,
        "title": "Merge final document",
        "objective": "Merge only validated, user-selected Markdown into the final document.",
        "stages": {"merge"},
        "gate": "merge",
        "artifacts": [
            "final.md",
        ],
    },
}


def build_iteration_plan(
    *,
    project_id: str,
    action_plan: PipelineActionPlan,
    quality_feedback: dict | None = None,
    revision_decisions: list[dict] | None = None,
) -> IterationPlan:
    actions_by_phase: dict[str, list[PipelineAction]] = defaultdict(list)
    for action in action_plan.actions:
        actions_by_phase[_phase_for_stage(action.stage)].append(action)

    phases: list[IterationPhase] = []
    for phase_id, config in sorted(_PHASES.items(), key=lambda item: int(item[1]["step"])):
        actions = _sorted_actions(actions_by_phase.get(phase_id, []))
        if not actions and not _include_empty_phase(phase_id, action_plan, quality_feedback, revision_decisions):
            continue
        phase = IterationPhase(
            phase_id=phase_id,
            step=int(config["step"]),
            title=str(config["title"]),
            objective=str(config["objective"]),
            actions=actions,
            gate_to_clear=str(config["gate"]),
            success_artifacts=list(config["artifacts"]),
            stop_conditions=_stop_conditions(phase_id, actions),
            blocks_later_phases=any(action.requires_user_confirmation for action in actions),
            requires_llm_count=sum(1 for action in actions if action.requires_llm),
            requires_user_confirmation_count=sum(1 for action in actions if action.requires_user_confirmation),
        )
        phases.append(phase)

    requires_llm = sum(phase.requires_llm_count for phase in phases)
    requires_user = sum(phase.requires_user_confirmation_count for phase in phases)
    next_phase = next((phase.phase_id for phase in phases if phase.actions), None)
    return IterationPlan(
        project_id=project_id,
        status=_status(action_plan, phases),
        summary=_summary(action_plan, phases, quality_feedback, revision_decisions),
        phases=phases,
        next_phase_id=next_phase,
        requires_llm_count=requires_llm,
        requires_user_confirmation_count=requires_user,
    )


def render_iteration_plan_markdown(plan: IterationPlan) -> str:
    lines = [
        "# Iteration Plan",
        "",
        f"- project_id: `{plan.project_id}`",
        f"- status: `{plan.status}`",
        f"- next_phase_id: `{plan.next_phase_id or '-'}`",
        f"- requires_llm_count: {plan.requires_llm_count}",
        f"- requires_user_confirmation_count: {plan.requires_user_confirmation_count}",
        "",
        plan.summary,
        "",
    ]
    for phase in plan.phases:
        lines.extend(
            [
                f"## {phase.step}. {phase.title}",
                "",
                phase.objective,
                "",
                f"- phase_id: `{phase.phase_id}`",
                f"- gate_to_clear: `{phase.gate_to_clear or '-'}`",
                f"- blocks_later_phases: `{str(phase.blocks_later_phases).lower()}`",
                "",
                "Success artifacts:",
                *[f"- `{item}`" for item in phase.success_artifacts],
                "",
            ]
        )
        if phase.stop_conditions:
            lines.extend(["Stop conditions:", *[f"- {item}" for item in phase.stop_conditions], ""])
        if phase.actions:
            lines.append("Actions:")
            for action in phase.actions:
                endpoint = f" `{action.method or 'GET'} {action.endpoint}`" if action.endpoint else ""
                markers = []
                if action.requires_user_confirmation:
                    markers.append("requires user confirmation")
                if action.requires_llm:
                    markers.append("requires LLM")
                marker_text = f" ({'; '.join(markers)})" if markers else ""
                target = f" target=`{action.target_id}`" if action.target_id else ""
                lines.append(f"- `{action.action_id}` [{action.priority}] {action.title}{endpoint}{target}{marker_text}")
                if action.reason:
                    lines.append(f"  - reason: {action.reason}")
            lines.append("")
        else:
            lines.extend(["Actions:", "- No action is currently required for this phase.", ""])
    return "\n".join(lines).strip() + "\n"


def _phase_for_stage(stage: str) -> str:
    for phase_id, config in _PHASES.items():
        if stage in config["stages"]:
            return phase_id
    return "quality_feedback"


def _include_empty_phase(
    phase_id: str,
    action_plan: PipelineActionPlan,
    quality_feedback: dict | None,
    revision_decisions: list[dict] | None,
) -> bool:
    if action_plan.overall_status in {"pending", "blocked"} and phase_id == "input_profile":
        return True
    if quality_feedback and phase_id == "quality_feedback":
        return True
    if revision_decisions and phase_id == "revision":
        return True
    return action_plan.overall_status == "passed" and phase_id == "version_merge"


def _sorted_actions(actions: list[PipelineAction]) -> list[PipelineAction]:
    priority_order = {"critical": 0, "high": 1, "normal": 2, "low": 3}
    return sorted(actions, key=lambda item: (priority_order.get(item.priority, 2), item.action_id))


def _stop_conditions(phase_id: str, actions: list[PipelineAction]) -> list[str]:
    conditions: list[str] = []
    if any(action.requires_user_confirmation for action in actions):
        conditions.append("Pause after creating proposals or estimates until the user reviews and applies them.")
    if phase_id in {"mapping_generation", "revision", "quality_feedback"} and any(action.requires_llm for action in actions):
        conditions.append("Persist prompts, responses, mappings, evidence, and validation results before continuing.")
    if phase_id == "outline_detail":
        conditions.append("Do not generate factual chapter text until outline repair and dense-node split decisions are accepted.")
    if phase_id == "version_merge":
        conditions.append("Merge only selected chapter versions; never merge transient draft text.")
    if phase_id == "version_review":
        conditions.append("Do not merge while selected versions still have evidence, metadata, or subsection revision actions.")
    return conditions


def _status(action_plan: PipelineActionPlan, phases: list[IterationPhase]) -> str:
    if action_plan.overall_status == "blocked":
        return "blocked"
    if any(phase.blocks_later_phases for phase in phases):
        return "waiting_for_user"
    if any(phase.actions for phase in phases):
        return "action_required"
    if action_plan.overall_status == "passed":
        return "ready_to_merge_or_complete"
    return action_plan.overall_status or "pending"


def _summary(
    action_plan: PipelineActionPlan,
    phases: list[IterationPhase],
    quality_feedback: dict | None,
    revision_decisions: list[dict] | None,
) -> str:
    action_count = sum(len(phase.actions) for phase in phases)
    feedback_text = " Quality feedback is loaded and will affect outline/detail/mapping actions." if quality_feedback else ""
    revision_count = len(revision_decisions or [])
    revision_text = f" {revision_count} revision decision(s) are available." if revision_count else ""
    if action_count == 0:
        return f"No pipeline action is currently required; overall gate status is `{action_plan.overall_status}`.{feedback_text}{revision_text}".strip()
    return (
        f"The plan groups {action_count} pending pipeline action(s) into {len(phases)} phase(s). "
        f"Execute phases in order and stop at user-confirmation gates before LLM regeneration.{feedback_text}{revision_text}"
    ).strip()
