from __future__ import annotations

from pydantic import BaseModel, Field


class ProjectCreateRequest(BaseModel):
    name: str = Field(default="宁夏煤火北一火区")
    template_id: str = Field(default="coal_fire")


class ProjectTemplateUpdateRequest(BaseModel):
    template_id: str = Field(default="coal_fire")


class BidMarkdownUploadRequest(BaseModel):
    file_name: str = Field(default="投标技术文件.md")
    content: str


class OutlineNodeCreateRequest(BaseModel):
    title: str
    parent_id: str | None = None
    level: int = 3
    sort_order: int | None = None
    enabled: bool = True
    source_rules: list[str] = Field(default_factory=list)
    auto_fill: list[str] = Field(default_factory=list)
    manual_fill: list[str] = Field(default_factory=list)
    special_notes: list[str] = Field(default_factory=list)
    target_word_count: int | None = None


class OutlineNodeUpdateRequest(BaseModel):
    title: str | None = None
    parent_id: str | None = None
    level: int | None = None
    sort_order: int | None = None
    enabled: bool | None = None
    source_rules: list[str] | None = None
    auto_fill: list[str] | None = None
    manual_fill: list[str] | None = None
    special_notes: list[str] | None = None
    target_word_count: int | None = None


class SupplementRequest(BaseModel):
    kind: str = "text"
    title: str = ""
    content: str = ""
    must_include: bool = False
    sort_order: int | None = None


class ManualVersionRequest(BaseModel):
    title: str
    markdown: str
    select: bool = True


class ContentNodeUpdateRequest(BaseModel):
    markdown: str
    select: bool = True


class SelectVersionRequest(BaseModel):
    version_id: str


class AIEditProposalRequest(BaseModel):
    suggestion: str
    base_markdown: str | None = None


class RevisionActionRequest(BaseModel):
    action: str | None = None


class ChildChapterGenerateRequest(BaseModel):
    recursive: bool = False
    only_pending: bool = False
    limit: int | None = None


class OutlineAIProposalRequest(BaseModel):
    suggestion: str
    preview_nodes: list[dict] | None = None


class WordCountEstimateRequest(BaseModel):
    reference_markdown: str | None = None


class PreGenerationOutlineRefineRequest(BaseModel):
    mode: str = "balanced"
    use_local_corpus: bool = True
    use_human_reference: bool = False
    human_reference_markdown: str | None = None
    project_type: str = "auto"


class QualityFeedbackApplyRequest(BaseModel):
    report: dict
    trace_diagnostics: dict | None = None


class QualityAuditRunRequest(BaseModel):
    source_markdown: str | None = None
    human_reference_markdown: str | None = None
    apply_feedback: bool = False


class QualityAuditTargetExecuteRequest(BaseModel):
    action: str | None = None


class QualityAuditTargetsExecuteRequest(BaseModel):
    include_user_confirmation: bool = False
    limit: int = 10


class GenerationReadinessBatchExecuteRequest(BaseModel):
    group_id: str | None = None
    include_user_confirmation: bool = False
    limit: int = 10
    respect_execution_window: bool = True


class QualityIterationRunRequest(BaseModel):
    max_rounds: int = 1
    include_user_confirmation: bool = False
    limit_per_round: int = 10
    source_markdown: str | None = None
    human_reference_markdown: str | None = None


class PatternLibraryAnalyzeRequest(BaseModel):
    corpus_dir: str | None = None
    output_dir: str | None = None


class PatternLibraryBuildSkillRequest(BaseModel):
    corpus_dir: str | None = None
    output_dir: str | None = None
    skill_name: str = "construction-org-writing-patterns"
    include_source_excerpts: bool = False
    max_source_chars: int = 250_000


class PatternLibraryApplyRequest(BaseModel):
    generated_path: str | None = None


class PatternLibraryLearningRequest(BaseModel):
    project_id: str | None = None
    learning_report_path: str | None = None
    learning_report: dict | None = None
    selected_suggestion_indexes: list[int] | None = None
    output_dir: str | None = None


class PatternLibraryAuditRequest(BaseModel):
    generated_path: str | None = None
    library: dict | None = None
    corpus_dir: str | None = None
    output_dir: str | None = None


class PatternLibrarySkillExportRequest(BaseModel):
    generated_path: str | None = None
    output_path: str | None = None
    output_dir: str | None = None


class ProjectSummaryResponse(BaseModel):
    id: str
    project_id: str
    name: str
    template_id: str
    source_document_count: int
    section_count: int
    run_count: int


class GenerateResponse(BaseModel):
    id: str
    run_id: str
    status: str
    task_count: int
    passed_count: int
    failed_count: int
    final_artifact_path: str | None = None
    logs: list[str]


class ChapterResponse(BaseModel):
    node_id: str
    title: str
    status: str
    markdown: str = ""
    draft_path: str | None = None
    source_matches: list[dict] = Field(default_factory=list)
    source_mapping: dict | None = None
    version: dict | None = None


class TemplateSummaryResponse(BaseModel):
    template_id: str
    name: str
    path: str | None = None


class TemplateTreeResponse(BaseModel):
    template_id: str
    name: str
    nodes: list[dict]


class SourceTocResponse(BaseModel):
    items: list[dict]
    artifact_json_path: str | None = None
    artifact_markdown_path: str | None = None


class SectionResponse(BaseModel):
    section_id: str
    title_path: list[str]
    level: int
    content: str
    source_file: str
    artifact_path: str | None = None


class ProjectProfileResponse(BaseModel):
    profile: dict | None
    artifact_json_path: str | None = None
    artifact_markdown_path: str | None = None


class OutlinePlanResponse(BaseModel):
    outline: dict | None
    artifact_json_path: str | None = None
    artifact_markdown_path: str | None = None


class GenerationControlPlanResponse(BaseModel):
    plan: dict | None
    artifact_json_path: str | None = None
    artifact_markdown_path: str | None = None


class RevisionDecisionsResponse(BaseModel):
    decisions: list[dict] = Field(default_factory=list)
    artifact_json_path: str | None = None
    artifact_markdown_path: str | None = None


class PipelineGateReportResponse(BaseModel):
    project_id: str
    overall_status: str
    gates: list[dict] = Field(default_factory=list)


class PipelineActionPlanResponse(BaseModel):
    project_id: str
    overall_status: str
    actions: list[dict] = Field(default_factory=list)


class GenerationReadinessResponse(BaseModel):
    project_id: str
    status: str
    summary: str
    nodes: list[dict] = Field(default_factory=list)
    batches: list[dict] = Field(default_factory=list)
    metrics: dict = Field(default_factory=dict)
    artifact_json_path: str | None = None
    artifact_markdown_path: str | None = None


class OutlineGenerationStepProgressResponse(BaseModel):
    project_id: str
    status: str
    summary: str
    steps: list[dict] = Field(default_factory=list)
    artifact_json_path: str | None = None


class OutlineGenerationStepRunResponse(BaseModel):
    project_id: str
    step_id: str
    status: str
    generated: list[dict] = Field(default_factory=list)
    skipped: list[dict] = Field(default_factory=list)
    failed: list[dict] = Field(default_factory=list)
    progress: dict = Field(default_factory=dict)
    artifact_json_path: str | None = None


class IterationPlanResponse(BaseModel):
    project_id: str
    status: str
    summary: str
    phases: list[dict] = Field(default_factory=list)
    next_phase_id: str | None = None
    requires_llm_count: int = 0
    requires_user_confirmation_count: int = 0
    artifact_json_path: str | None = None
    artifact_markdown_path: str | None = None


class CurrentExecutionWindowResponse(BaseModel):
    project_id: str
    status: str
    current_phase_id: str | None = None
    current_phase_title: str | None = None
    blocking_reason: str = ""
    allowed_actions: list[dict] = Field(default_factory=list)
    deferred_actions: list[dict] = Field(default_factory=list)
    requires_llm_count: int = 0
    requires_user_confirmation_count: int = 0
    artifact_json_path: str | None = None
    artifact_markdown_path: str | None = None


class TargetedRevisionPlanResponse(BaseModel):
    source_output_root: str | None = None
    source_model: str | None = None
    comparison_verdict: str | None = None
    project_count: int = 0
    action_count: int = 0
    action_counts: dict = Field(default_factory=dict)
    priority_counts: dict = Field(default_factory=dict)
    rerun_policy: str
    projects: list[dict] = Field(default_factory=list)
    artifact_json_path: str | None = None
    artifact_markdown_path: str | None = None


class PipelineBlueprintResponse(BaseModel):
    blueprint: dict
    markdown: str


class DirectoryResponse(BaseModel):
    project: ProjectSummaryResponse
    template: TemplateTreeResponse | None = None
    source_toc: SourceTocResponse | None = None
    outline: OutlinePlanResponse | None = None
    generation_control: GenerationControlPlanResponse | None = None
    revision_decisions: RevisionDecisionsResponse | None = None
    chapter_tasks: list[dict] = Field(default_factory=list)
    profile_status: str = "not_ready"
    outline_status: str = "not_run"
    outline_source: str = "template"
    warnings: list[str] = Field(default_factory=list)


class PatternLibraryResponse(BaseModel):
    library: dict
    active_path: str | None = None
    generated_path: str | None = None
    generated_available: bool | None = None


class PatternLibraryAnalyzeResponse(BaseModel):
    analysis: dict
    generated_library: dict
    corpus_dir: str
    analysis_json_path: str
    analysis_markdown_path: str
    generated_path: str


class PatternLibraryBuildSkillResponse(BaseModel):
    corpus_dir: str
    output_dir: str
    analysis: dict
    generated_library: dict
    coverage_report: dict
    skill_package: dict
    analysis_json_path: str
    analysis_markdown_path: str
    generated_path: str
    coverage_json_path: str
    coverage_markdown_path: str
    skill_package_dir: str
    skill_manifest_path: str


class PatternLibraryLearningResponse(BaseModel):
    learning_report: dict
    generated_library: dict
    changes: list[dict] = Field(default_factory=list)
    selected_suggestion_indexes: list[int] | None = None
    source: str
    generated_path: str
    learning_report_path: str
    learning_candidate_markdown_path: str


class PatternLibraryAuditResponse(BaseModel):
    report: dict
    library: dict
    source_path: str | None = None
    corpus_dir: str | None = None
    artifact_json_path: str
    artifact_markdown_path: str


class PatternLibraryApplyResponse(BaseModel):
    applied: bool
    applied_at: str | None = None
    active_path: str
    generated_path: str
    backup_path: str | None = None
    apply_log_path: str | None = None
    apply_history_path: str | None = None
    apply_history_count: int | None = None
    coverage_status: str | None = None
    coverage_issue_count: int | None = None
    coverage_report: dict | None = None
    library: dict


class PatternLibraryApplyHistoryResponse(BaseModel):
    history: list[dict] = Field(default_factory=list)
    apply_history_path: str


class PatternLibrarySkillResponse(BaseModel):
    library: dict
    markdown: str
    validation_issues: list[dict] = Field(default_factory=list)
    coverage_report: dict | None = None
    output_path: str | None = None
    output_dir: str | None = None
    package_paths: dict | None = None
    manifest: dict | None = None


class PatternLibraryPromptCardsResponse(BaseModel):
    version: str
    corpus_scope: str
    evidence_scope: str
    stage_usage: dict[str, list[str]]
    cards: dict[str, dict]
    coverage_report: dict | None = None
    source_path: str | None = None


def project_summary(project) -> ProjectSummaryResponse:
    return ProjectSummaryResponse(
        id=project.id,
        project_id=project.id,
        name=project.name,
        template_id=project.template_id,
        source_document_count=len(project.source_documents),
        section_count=len(project.sections),
        run_count=len(project.runs),
    )


def run_summary(run) -> GenerateResponse:
    passed = sum(1 for task in run.chapter_tasks if task.status.value == "passed")
    failed = sum(1 for task in run.chapter_tasks if task.status.value == "failed")
    return GenerateResponse(
        id=run.id,
        run_id=run.id,
        status=run.status.value,
        task_count=len(run.chapter_tasks),
        passed_count=passed,
        failed_count=failed,
        final_artifact_path=run.final_artifact_path,
        logs=run.logs,
    )
