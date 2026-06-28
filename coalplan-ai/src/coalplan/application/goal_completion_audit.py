from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from coalplan.application.pattern_library_coverage import (
    PatternLibraryCoverageReport,
    audit_pattern_library_coverage,
)
from coalplan.application.pipeline_blueprint import PipelineBlueprint, build_pipeline_blueprint
from coalplan.application.pipeline_stage_gates import PipelineGateReport
from coalplan.application.writing_pattern_library import WritingPatternLibrary, load_writing_pattern_library
from coalplan.application.writing_pattern_requirements import REQUIRED_PATTERN_KEYS


AuditStatus = Literal["passed", "warning", "blocked"]


class GoalRequirementAudit(BaseModel):
    requirement_id: str
    title: str
    status: AuditStatus
    evidence: list[str] = Field(default_factory=list)
    gaps: list[str] = Field(default_factory=list)
    next_actions: list[str] = Field(default_factory=list)


class GenerationGoalAuditReport(BaseModel):
    status: AuditStatus
    summary: str
    requirement_audits: list[GoalRequirementAudit] = Field(default_factory=list)
    metrics: dict[str, Any] = Field(default_factory=dict)
    recommendations: list[str] = Field(default_factory=list)


def audit_generation_goal(
    *,
    blueprint: PipelineBlueprint | None = None,
    pattern_library: WritingPatternLibrary | dict | None = None,
    pattern_coverage: PatternLibraryCoverageReport | dict | None = None,
    project_gate_report: PipelineGateReport | dict | None = None,
) -> GenerationGoalAuditReport:
    """Audit reusable pipeline readiness against the thread's construction-org generation goal.

    This is intentionally a meta-audit: it checks that the reusable controls exist and,
    when a project gate report is supplied, whether a concrete run has satisfied them.
    It does not mark the user's broader goal complete by itself.
    """

    parsed_blueprint = blueprint or build_pipeline_blueprint()
    parsed_library = _parse_library(pattern_library)
    parsed_pattern_coverage = _parse_pattern_coverage(pattern_coverage, parsed_library)
    parsed_gate_report = _parse_gate_report(project_gate_report)

    audits = [
        _audit_layered_outline(parsed_blueprint),
        _audit_source_mapping(parsed_blueprint),
        _audit_detail_design(parsed_blueprint),
        _audit_revision_control(parsed_blueprint),
        _audit_local_pattern_skill(parsed_library, parsed_pattern_coverage),
        _audit_persistence_and_traceability(parsed_blueprint),
        _audit_project_gate_if_available(parsed_gate_report),
    ]
    blocked = [item for item in audits if item.status == "blocked"]
    warnings = [item for item in audits if item.status == "warning"]
    status: AuditStatus = "blocked" if blocked else "warning" if warnings else "passed"
    metrics = {
        "requirement_count": len(audits),
        "passed_count": sum(1 for item in audits if item.status == "passed"),
        "warning_count": len(warnings),
        "blocked_count": len(blocked),
        "blueprint_stage_count": len(parsed_blueprint.stages),
        "pattern_count": len(parsed_library.patterns),
        "required_pattern_count": len(REQUIRED_PATTERN_KEYS),
    }
    recommendations = _build_recommendations(audits, parsed_gate_report)
    return GenerationGoalAuditReport(
        status=status,
        summary=_summary(status, metrics),
        requirement_audits=audits,
        metrics=metrics,
        recommendations=recommendations,
    )


def render_generation_goal_audit_markdown(report: GenerationGoalAuditReport) -> str:
    lines = [
        "# Generation Goal Completion Audit",
        "",
        f"- status: `{report.status}`",
        f"- summary: {report.summary}",
        "",
        "## Metrics",
    ]
    for key, value in report.metrics.items():
        lines.append(f"- {key}: {value}")
    lines.extend(["", "## Requirements"])
    for item in report.requirement_audits:
        lines.extend(
            [
                "",
                f"### {item.requirement_id}: {item.title}",
                f"- status: `{item.status}`",
                "- evidence:",
            ]
        )
        lines.extend(f"  - {entry}" for entry in (item.evidence or ["-"]))
        lines.append("- gaps:")
        lines.extend(f"  - {entry}" for entry in (item.gaps or ["-"]))
        lines.append("- next_actions:")
        lines.extend(f"  - {entry}" for entry in (item.next_actions or ["-"]))
    lines.extend(["", "## Recommendations"])
    lines.extend(f"- {item}" for item in (report.recommendations or ["No extra recommendation."]))
    return "\n".join(lines).strip() + "\n"


def _audit_layered_outline(blueprint: PipelineBlueprint) -> GoalRequirementAudit:
    stage_ids = _stage_ids(blueprint)
    required = {"outline", "coverage", "detail"}
    missing = sorted(required - stage_ids)
    outline = _stage(blueprint, "outline")
    detail = _stage(blueprint, "detail")
    evidence = []
    if outline:
        evidence.append("outline stage persists editable project outline and generation steps")
    if detail:
        evidence.append("detail stage computes target word count and split decisions")
    gaps = [f"missing blueprint stage: {stage}" for stage in missing]
    if detail and not any("subsection" in route or "subsection" in action for route in detail.failure_routes for action in [route]):
        gaps.append("detail stage does not advertise subsection expansion route")
    return GoalRequirementAudit(
        requirement_id="directory_tree_layering",
        title="Directory tree can be generated, edited, and executed by layer.",
        status=_status_from_gaps(gaps),
        evidence=evidence,
        gaps=gaps,
        next_actions=["Keep outline proposals user-confirmed and generate layers through existing single-chapter pipeline."] if not gaps else ["Add missing outline/detail/coverage controls."],
    )


def _audit_source_mapping(blueprint: PipelineBlueprint) -> GoalRequirementAudit:
    mapping = _stage(blueprint, "mapping")
    generation = _stage(blueprint, "generation")
    gaps: list[str] = []
    evidence: list[str] = []
    if mapping is None:
        gaps.append("mapping stage is missing")
    else:
        evidence.append("mapping stage maps each chapter to source sections and extracts evidence ids")
        if not any("evidence" in output.lower() for output in mapping.outputs):
            gaps.append("mapping outputs do not include evidence spans")
        if not any("remap" in route or "mapping" in route for route in mapping.failure_routes):
            gaps.append("mapping stage lacks remap failure route")
    if generation is None:
        gaps.append("generation stage is missing")
    else:
        evidence.append("generation stage consumes mapped evidence and user supplements")
        if not any("section/evidence" in check or "source facts" in check for check in generation.gate_checks):
            gaps.append("generation gate does not require source or evidence use")
    return GoalRequirementAudit(
        requirement_id="source_mapping_before_writing",
        title="Every factual paragraph is gated by source-section mapping and evidence extraction.",
        status=_status_from_gaps(gaps),
        evidence=evidence,
        gaps=gaps,
        next_actions=["Preserve source mapping as a hard gate before factual Markdown generation."] if not gaps else ["Tighten mapping/generation gate checks."],
    )


def _audit_detail_design(blueprint: PipelineBlueprint) -> GoalRequirementAudit:
    detail = _stage(blueprint, "detail")
    gaps: list[str] = []
    evidence: list[str] = []
    if detail is None:
        gaps.append("detail stage is missing")
    else:
        evidence.append("detail stage owns target word counts, source budgets, evidence budgets, and split decisions")
        required_terms = ("target word count", "source/evidence budgets", "split decisions")
        text = " ".join([detail.purpose, *detail.outputs, *detail.gate_checks]).lower()
        for term in required_terms:
            if term not in text:
                gaps.append(f"detail design missing term: {term}")
    return GoalRequirementAudit(
        requirement_id="detail_budget_control",
        title="Content length and depth are designed before generation without inventing unsupported facts.",
        status=_status_from_gaps(gaps),
        evidence=evidence,
        gaps=gaps,
        next_actions=["Use target word count as a detail budget and split dense chapters before long generation."] if not gaps else ["Add explicit detail budget fields and gates."],
    )


def _audit_revision_control(blueprint: PipelineBlueprint) -> GoalRequirementAudit:
    revision = _stage(blueprint, "revision")
    quality = _stage(blueprint, "quality_feedback")
    version = _stage(blueprint, "version")
    required_routes = {"repair_format", "remap_sources", "expand_subsections", "regenerate", "request_human_input", "disable_node"}
    gaps: list[str] = []
    evidence: list[str] = []
    if revision is None:
        gaps.append("revision stage is missing")
    else:
        routes = set(revision.failure_routes)
        missing_routes = sorted(required_routes - routes)
        evidence.append("revision stage routes drafts to repair, remap, split, regenerate, human input, or disable")
        gaps.extend(f"revision route missing: {route}" for route in missing_routes)
    if quality is None:
        gaps.append("quality feedback stage is missing")
    else:
        evidence.append("quality feedback converts audits and trace diagnostics into next-run controls")
    if version is None:
        gaps.append("selected-version review stage is missing")
    else:
        evidence.append("version stage audits evidence utilization, content tree, and local writing-pattern metadata")
    return GoalRequirementAudit(
        requirement_id="llm_revision_decision_control",
        title="The pipeline decides when LLM should repair, remap, split, regenerate, or defer to human input.",
        status=_status_from_gaps(gaps),
        evidence=evidence,
        gaps=gaps,
        next_actions=["Keep all revision actions routed through persisted decisions, proposals, or new versions."] if not gaps else ["Complete missing revision routes or feedback gates."],
    )


def _audit_local_pattern_skill(
    library: WritingPatternLibrary,
    coverage: PatternLibraryCoverageReport,
) -> GoalRequirementAudit:
    missing = sorted(REQUIRED_PATTERN_KEYS - set(library.patterns))
    evidence = [
        f"pattern library has {len(library.patterns)} pattern(s)",
        f"coverage audit status is {coverage.status}",
    ]
    for key in sorted(REQUIRED_PATTERN_KEYS & set(library.patterns)):
        pattern = library.patterns[key]
        evidence.append(
            f"{key}: structure={len(pattern.preferred_structure)}, source_facts={len(pattern.required_source_facts)}, revision_signals={len(pattern.revision_signals)}"
        )
    gaps = [f"missing required writing pattern: {key}" for key in missing]
    gaps.extend(issue.message for issue in coverage.issues if issue.severity == "error")
    warning_gaps = [issue.message for issue in coverage.issues if issue.severity == "warning"]
    status: AuditStatus = "blocked" if gaps else "warning" if warning_gaps else "passed"
    return GoalRequirementAudit(
        requirement_id="local_corpus_pattern_skill",
        title="Reusable local construction-plan writing skill covers overview, craft, quality, safety, environment, deployment, and schedule/resource.",
        status=status,
        evidence=evidence,
        gaps=[*gaps, *warning_gaps[:10]],
        next_actions=coverage.recommendations,
    )


def _audit_persistence_and_traceability(blueprint: PipelineBlueprint) -> GoalRequirementAudit:
    persisted = "\n".join(item for stage in blueprint.stages for item in stage.persisted_artifacts)
    expected = [
        "inputs/toc.json",
        "inputs/sections.json",
        "mapping/{node_id}.json",
        "mapping/{node_id}.evidence.md",
        "database:chapter_versions",
        "llm_traces/*",
        "final/final.md",
    ]
    gaps = [f"missing persisted artifact contract: {item}" for item in expected if item not in persisted]
    evidence = [f"persisted artifact contract includes {item}" for item in expected if item in persisted]
    return GoalRequirementAudit(
        requirement_id="traceable_persistence",
        title="Inputs, mappings, prompts, versions, audits, and final output are persistable and inspectable.",
        status=_status_from_gaps(gaps),
        evidence=evidence,
        gaps=gaps,
        next_actions=["Keep prompt/response traces enabled for real LLM runs and compare runs through persisted artifacts."] if not gaps else ["Add missing persisted artifact contracts to pipeline blueprint and implementation."],
    )


def _audit_project_gate_if_available(report: PipelineGateReport | None) -> GoalRequirementAudit:
    if report is None:
        return GoalRequirementAudit(
            requirement_id="project_run_evidence",
            title="A concrete project run can prove the reusable controls end to end.",
            status="warning",
            evidence=["No project gate report was supplied for this meta-audit."],
            gaps=["Reusable design is auditable, but no concrete project run evidence was included."],
            next_actions=["Run a project through pipeline gates and pass that gate report into this audit."],
        )
    blocked = [gate for gate in report.gates if gate.status == "blocked"]
    warnings = [gate for gate in report.gates if gate.status == "warning"]
    status: AuditStatus = "blocked" if blocked else "warning" if warnings or report.overall_status != "passed" else "passed"
    evidence = [f"project gate report overall_status={report.overall_status}"]
    evidence.extend(f"{gate.name}: {gate.status} ({gate.summary})" for gate in report.gates)
    gaps = [f"{gate.name}: {'; '.join(gate.issues[:3])}" for gate in [*blocked, *warnings] if gate.issues]
    return GoalRequirementAudit(
        requirement_id="project_run_evidence",
        title="A concrete project run can prove the reusable controls end to end.",
        status=status,
        evidence=evidence,
        gaps=gaps,
        next_actions=["Resolve blocked or warning gates before claiming the concrete project is complete."] if gaps else ["Use the run as a baseline for real LLM quality comparisons."],
    )


def _parse_library(library: WritingPatternLibrary | dict | None) -> WritingPatternLibrary:
    if library is None:
        return load_writing_pattern_library()
    if isinstance(library, WritingPatternLibrary):
        return library
    return WritingPatternLibrary.model_validate(library)


def _parse_pattern_coverage(
    coverage: PatternLibraryCoverageReport | dict | None,
    library: WritingPatternLibrary,
) -> PatternLibraryCoverageReport:
    if coverage is None:
        return audit_pattern_library_coverage(library)
    if isinstance(coverage, PatternLibraryCoverageReport):
        return coverage
    return PatternLibraryCoverageReport.model_validate(coverage)


def _parse_gate_report(report: PipelineGateReport | dict | None) -> PipelineGateReport | None:
    if report is None:
        return None
    if isinstance(report, PipelineGateReport):
        return report
    return PipelineGateReport.model_validate(report)


def _stage_ids(blueprint: PipelineBlueprint) -> set[str]:
    return {stage.stage_id for stage in blueprint.stages}


def _stage(blueprint: PipelineBlueprint, stage_id: str):
    return next((stage for stage in blueprint.stages if stage.stage_id == stage_id), None)


def _status_from_gaps(gaps: list[str]) -> AuditStatus:
    return "blocked" if gaps else "passed"


def _build_recommendations(audits: list[GoalRequirementAudit], gate_report: PipelineGateReport | None) -> list[str]:
    recommendations: list[str] = []
    for audit in audits:
        if audit.status != "passed":
            recommendations.extend(audit.next_actions[:3])
    if gate_report is None:
        recommendations.append("Attach a real project gate report to distinguish architecture readiness from project-run completion.")
    return _dedupe(recommendations) or ["No extra recommendation."]


def _summary(status: AuditStatus, metrics: dict[str, Any]) -> str:
    if status == "passed":
        return "Reusable generation controls and supplied project evidence satisfy the audited goal requirements."
    if status == "blocked":
        return f"{metrics['blocked_count']} requirement(s) have blocking gaps before the pipeline can be called complete."
    return f"{metrics['warning_count']} requirement(s) need project-run evidence or review before completion can be claimed."


def _dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    output: list[str] = []
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        output.append(item)
    return output
