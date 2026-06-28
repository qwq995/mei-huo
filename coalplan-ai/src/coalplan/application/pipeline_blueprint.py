from __future__ import annotations

from pydantic import BaseModel, Field


class PipelineStageBlueprint(BaseModel):
    stage_id: str
    title: str
    purpose: str
    inputs: list[str] = Field(default_factory=list)
    outputs: list[str] = Field(default_factory=list)
    persisted_artifacts: list[str] = Field(default_factory=list)
    gate_checks: list[str] = Field(default_factory=list)
    llm_role: str | None = None
    user_controls: list[str] = Field(default_factory=list)
    failure_routes: list[str] = Field(default_factory=list)
    related_actions: list[str] = Field(default_factory=list)


class PipelineBlueprint(BaseModel):
    blueprint_id: str = "construction_org_generation_pipeline"
    version: str = "1.0"
    scope: str = "Reusable source-grounded construction organization generation pipeline."
    invariants: list[str] = Field(default_factory=list)
    stages: list[PipelineStageBlueprint] = Field(default_factory=list)


def build_pipeline_blueprint() -> PipelineBlueprint:
    return PipelineBlueprint(
        invariants=[
            "Source mapping is a gate before factual chapter generation.",
            "Local corpus writing patterns are structural controls, not project facts.",
            "Target word count is a detail budget, not permission to invent unsupported content.",
            "Dense craft chapters are split into source-derived subchapters before long-form writing.",
            "LLM revision retries must carry reasons, missing evidence, omitted facts, and required changes.",
            "Final merge uses only validated and user-selected chapter versions.",
        ],
        stages=[
            PipelineStageBlueprint(
                stage_id="input",
                title="Input Normalize And Split",
                purpose="Normalize bid markdown, split it into source sections, and persist a stable source index.",
                inputs=["Uploaded bid markdown", "File metadata"],
                outputs=["MarkdownSection[]", "SourceToc"],
                persisted_artifacts=[
                    "inputs/bid.md",
                    "inputs/bid.normalized.md",
                    "inputs/sections.json",
                    "inputs/toc.json",
                    "inputs/toc.md",
                    "inputs/sections/{section_id}.md",
                ],
                gate_checks=["source_documents exist", "sections exist", "source_toc exists"],
                failure_routes=["upload_bid_markdown", "normalize_markdown"],
                related_actions=["input.upload_bid_markdown"],
            ),
            PipelineStageBlueprint(
                stage_id="profile",
                title="Project Profile Extraction",
                purpose="Extract project identity, scope, methods, quantities, targets, risks, and missing items from source text.",
                inputs=["SourceToc", "High-relevance MarkdownSection[]"],
                outputs=["ProjectProfile"],
                persisted_artifacts=["profile/project_profile.json", "profile/project_profile.md"],
                gate_checks=["required profile fields are populated", "source_section_ids are valid", "fallback markers are absent"],
                llm_role="structured extraction with strict JSON schema",
                failure_routes=["repair_profile", "prepare_directory"],
                related_actions=["profile.prepare_directory"],
            ),
            PipelineStageBlueprint(
                stage_id="outline",
                title="Editable Outline Planning",
                purpose="Copy the selected template into a project-editable outline and keep AI changes as proposals until applied.",
                inputs=["TemplateTree", "ProjectProfile", "SourceToc"],
                outputs=["Project outline nodes", "TemplateOutlinePlan", "Generation steps"],
                persisted_artifacts=["outline/generated_outline.json", "outline/generated_outline.md", "database:project_outline_nodes"],
                gate_checks=["template tree exists", "effective nodes exist", "editable outline exists"],
                llm_role="optional outline proposal; never directly overwrites user outline",
                user_controls=["add node", "rename node", "disable node", "reorder node", "apply/reject proposal"],
                failure_routes=["prepare_directory", "propose_outline_repair"],
                related_actions=["outline.prepare_directory", "outline.control_plan_proposal"],
            ),
            PipelineStageBlueprint(
                stage_id="coverage",
                title="Source Coverage Audit",
                purpose="Compare source TOC topics and common construction organization topics against the current outline.",
                inputs=["SourceToc", "TemplateTree or editable outline", "Local corpus topic patterns"],
                outputs=["OutlineCoverageItem[]"],
                persisted_artifacts=["control/generation_control_plan.json", "control/generation_control_plan.md"],
                gate_checks=["missing source-backed topics", "partial source-backed topics", "template-only unsupported topics"],
                failure_routes=["outline_repair_proposal", "disable_unsupported_node", "request_human_input"],
                related_actions=["outline.control_plan_proposal", "quality_feedback.outline_repair_proposal"],
            ),
            PipelineStageBlueprint(
                stage_id="detail",
                title="Detail Budget And Subsection Design",
                purpose="Compute target word count, detail level, source/evidence budgets, and split decisions for every chapter node.",
                inputs=["Outline nodes", "SourceToc", "WritingPatternPromptCard[]", "Optional reference markdown"],
                outputs=["ChapterGenerationPolicy[]", "Subsection proposal nodes"],
                persisted_artifacts=["control/generation_control_plan.json", "database:project_outline_nodes.target_word_count"],
                gate_checks=["target_word_count exists", "dense craft split_required is handled", "pattern facts are available as mapping requirements"],
                user_controls=["edit word count", "apply/reject subsection proposal"],
                failure_routes=["estimate_word_counts", "propose_subsections", "request_human_input"],
                related_actions=["detail.estimate_word_counts", "detail.subsection_proposals"],
            ),
            PipelineStageBlueprint(
                stage_id="mapping",
                title="Chapter Source Mapping And Evidence Extraction",
                purpose="Map each chapter to source sections, extract evidence spans, and attach evidence ids before writing.",
                inputs=["ProjectProfile", "SourceToc", "TemplateNode", "ChapterGenerationPolicy", "Quality feedback mapping context"],
                outputs=["SourceMappingResult", "SourceEvidenceSpan[]", "SourceMatch[]"],
                persisted_artifacts=["mapping/{node_id}.json", "mapping/{node_id}.evidence.md"],
                gate_checks=["section_id exists", "matches are reliable or explicitly missing", "evidence spans support required source facts"],
                llm_role="structured source selection; fallback keyword mapper may run without LLM",
                failure_routes=["remap_sources", "increase_evidence_budget", "request_human_input", "disable_node"],
                related_actions=["mapping.generate", "quality_feedback.remap_and_regenerate"],
            ),
            PipelineStageBlueprint(
                stage_id="generation",
                title="Chapter Generation",
                purpose="Generate one chapter or subsection at a time using mapped evidence, user supplements, pattern cards, and detail policy.",
                inputs=["ProjectProfile", "TemplateNode", "Selected source sections", "SourceEvidenceSpan[]", "ChapterGenerationPolicy", "User supplements"],
                outputs=["ChapterDraft", "Chapter version"],
                persisted_artifacts=["chapters/{node_id}.md", "database:chapter_versions", "llm_traces/*"],
                gate_checks=["Markdown contract passes", "main source summary cites section/evidence ids", "source facts are used or explained"],
                llm_role="strict Markdown chapter writing under fixed contract",
                user_controls=["add supplements", "upload attachment notes", "manual save version", "select version"],
                failure_routes=["repair_format", "regenerate", "remap_sources", "request_human_input"],
                related_actions=["generation.generate"],
            ),
            PipelineStageBlueprint(
                stage_id="revision",
                title="Chapter Revision Decision",
                purpose="Decide whether each draft is accepted, repaired, remapped, split, regenerated, routed to human input, or disabled.",
                inputs=["ChapterDraft", "ValidationResult", "EvidenceUtilizationAudit", "ChapterGenerationPolicy"],
                outputs=["ChapterRevisionDecision[]", "Revision prompt context"],
                persisted_artifacts=["control/revision_decisions.json", "control/revision_decisions.md", "runs/{run_id}/validation.json"],
                gate_checks=["format issues", "source grounding issues", "omitted required facts", "missing evidence", "specificity/detail gaps"],
                failure_routes=["repair_format", "remap_sources", "expand_subsections", "regenerate", "request_human_input", "disable_node"],
                related_actions=["revision.{node_id}.regenerate", "revision.{node_id}.remap_sources", "revision.{node_id}.expand_subsections"],
            ),
            PipelineStageBlueprint(
                stage_id="quality_feedback",
                title="Post Generation Quality Feedback",
                purpose="Compare generated outputs against source markdown, human references, and LLM traces; convert findings into next-run controls.",
                inputs=["Final/generated markdown", "Source markdown", "Optional human reference", "LLM trace diagnostics"],
                outputs=["QualityFeedbackPlan", "Adjusted GenerationControlPlan", "Outline repair proposals"],
                persisted_artifacts=["control/quality_feedback_plan.json", "control/quality_feedback_plan.md", "control/base_generation_control_plan.json"],
                gate_checks=["word ratio", "heading coverage", "source fact absorption", "trace not_prompted/prompted_but_omitted facts"],
                failure_routes=["increase_detail_budget", "repair_outline_coverage", "strengthen_evidence_utilization", "remap_and_regenerate"],
                related_actions=["quality_feedback.apply_audit_report", "quality_feedback.outline_repair_proposal", "quality_feedback.remap_and_regenerate"],
            ),
            PipelineStageBlueprint(
                stage_id="version",
                title="Selected Version Review",
                purpose="Review selected chapter versions, evidence utilization, generated content subsections, and local writing-pattern metadata before final merge.",
                inputs=[
                    "Chapter versions",
                    "Selected version ids",
                    "EvidenceUtilizationAudit",
                    "Generated content tree source links",
                    "Content revision plan",
                    "Generation metadata organization audit",
                ],
                outputs=[
                    "Selected chapter versions",
                    "Evidence-utilization revision actions",
                    "Content tree source status",
                    "Subsection-level revision actions",
                    "Generation metadata revision actions",
                ],
                persisted_artifacts=[
                    "database:chapter_versions",
                    "database:chapter_supplements",
                    "database:chapter_attachments",
                    "chapters/{node_id}/versions/{version_id}.evidence_audit.json",
                    "chapters/{node_id}/versions/{version_id}.content_tree.json",
                    "chapters/{node_id}/versions/{version_id}.content_revision_plan.json",
                    "chapters/{node_id}/versions/{version_id}.generation_metadata.json",
                ],
                gate_checks=[
                    "selected_version_id exists",
                    "evidence audit exists and has no actionable omitted required facts",
                    "content tree subsection source links are not missing/weak",
                    "content revision plan has no unresolved remap/rewrite/human-input actions",
                    "generation metadata audit has no unresolved organization repair actions",
                ],
                user_controls=[
                    "select version",
                    "manual edit",
                    "save version",
                    "review evidence utilization",
                    "review subsection source links",
                    "review subsection revision actions",
                    "review generation metadata",
                ],
                failure_routes=[
                    "select_versions",
                    "review_evidence_utilization",
                    "review_content_tree_sources",
                    "review_generation_metadata",
                    "manual_edit",
                ],
                related_actions=[
                    "version.select_versions",
                    "version.review_evidence_utilization",
                    "version.review_content_tree_sources",
                    "version.review_generation_metadata",
                ],
            ),
            PipelineStageBlueprint(
                stage_id="merge",
                title="Final Merge",
                purpose="Merge selected chapter versions in outline order only after version review, evidence utilization, content revision, and metadata gates are clear.",
                inputs=["TemplateTree or editable outline", "Selected ChapterDraft[]"],
                outputs=["final.md"],
                persisted_artifacts=["final/final.md"],
                gate_checks=["all required prior gates pass", "version gate is passed", "final artifact exists"],
                user_controls=["download final markdown", "review final output"],
                failure_routes=["merge_final", "return_to_version_review", "return_to_revision"],
                related_actions=["merge.final"],
            ),
        ],
    )


def render_pipeline_blueprint_markdown(blueprint: PipelineBlueprint | None = None) -> str:
    blueprint = blueprint or build_pipeline_blueprint()
    lines = [
        f"# Pipeline Blueprint: {blueprint.blueprint_id}",
        "",
        f"- version: {blueprint.version}",
        f"- scope: {blueprint.scope}",
        "",
        "## Invariants",
    ]
    lines.extend(f"- {item}" for item in blueprint.invariants)
    lines.extend(["", "## Stages"])
    for stage in blueprint.stages:
        lines.extend(
            [
                "",
                f"### {stage.stage_id}: {stage.title}",
                "",
                f"- purpose: {stage.purpose}",
                _line("inputs", stage.inputs),
                _line("outputs", stage.outputs),
                _line("persisted_artifacts", stage.persisted_artifacts),
                _line("gate_checks", stage.gate_checks),
                f"- llm_role: {stage.llm_role or 'none'}",
                _line("user_controls", stage.user_controls),
                _line("failure_routes", stage.failure_routes),
                _line("related_actions", stage.related_actions),
            ]
        )
    return "\n".join(lines).strip() + "\n"


def _line(label: str, items: list[str]) -> str:
    return f"- {label}: " + ("; ".join(items) if items else "-")
