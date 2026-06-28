export type TemplateNode = {
  id: string;
  node_id?: string;
  parent_id?: string | null;
  title: string;
  level: number;
  sort_order?: number;
  enabled?: boolean;
  source_rules: string[];
  auto_fill: string[];
  manual_fill: string[];
  special_notes: string[];
  target_word_count?: number | null;
  selected_version_id?: string | null;
  children: TemplateNode[];
};

export type OutlineNode = Omit<TemplateNode, "children"> & { node_id: string; children?: TemplateNode[] };

export type TemplateSummary = {
  template_id: string;
  name: string;
  path?: string | null;
};

export type ProjectResponse = {
  id: string;
  project_id: string;
  name: string;
  template_id: string;
  source_document_count: number;
  section_count: number;
  run_count: number;
};

export type SourceTocItem = {
  section_id: string;
  title_path: string[];
  level: number;
  char_count: number;
  snippet: string;
};

export type SourceSection = {
  section_id: string;
  title_path: string[];
  level: number;
  content: string;
  source_file: string;
  artifact_path?: string | null;
};

export type SourceMatch = {
  section_id: string;
  title_path: string[];
  snippet: string;
  score: number;
};

export type SourceEvidenceSpan = {
  evidence_id: string;
  section_id: string;
  title_path: string[];
  start_line?: number | null;
  end_line?: number | null;
  usage: string;
  template_module: string;
  matched_terms: string[];
  quote: string;
  summary: string;
  reason: string;
  confidence: number;
};

export type SourceMappingMatch = {
  section_id: string;
  title_path: string[];
  usage: string;
  reason: string;
  confidence: number;
  evidence_ids: string[];
};

export type SourceMappingResult = {
  node_id: string;
  matches: SourceMappingMatch[];
  evidence: SourceEvidenceSpan[];
  missing_evidence: string[];
  validation_issues: string[];
  artifact_path?: string | null;
  evidence_artifact_path?: string | null;
};

export type GeneratedContentSourceLink = {
  evidence_id?: string | null;
  section_id: string;
  title_path: string[];
  confidence: number;
  reason: string;
  matched_terms: string[];
};

export type GeneratedContentNode = {
  id: string;
  title: string;
  level: number;
  title_path: string[];
  start_line: number;
  end_line: number;
  markdown: string;
  body: string;
  source_links: GeneratedContentSourceLink[];
  source_status?: "covered" | "weak" | "missing" | "not_required" | "unknown" | string;
  mapping_issues?: string[];
  children: GeneratedContentNode[];
};

export type GeneratedContentTree = {
  version_id?: string | null;
  node_id: string;
  title: string;
  markdown_line_count: number;
  nodes: GeneratedContentNode[];
  artifact_path?: string | null;
};

export type ContentNodeRevisionItem = {
  content_node_id: string;
  title: string;
  title_path: string[];
  source_status: string;
  word_count: number;
  action: string;
  severity: "info" | "warning" | "error" | string;
  reason: string;
  requires_llm: boolean;
  requires_user_confirmation: boolean;
  source_section_ids: string[];
  evidence_ids: string[];
  next_steps: string[];
};

export type ContentRevisionPlan = {
  node_id: string;
  version_id?: string | null;
  title: string;
  status: "passed" | "warning" | "blocked" | string;
  metrics: Record<string, number>;
  items: ContentNodeRevisionItem[];
  artifact_path?: string | null;
};

export type GenerationMetadataAudit = {
  status: "passed" | "warning" | "blocked" | string;
  issues: string[];
  next_actions: string[];
  metrics: Record<string, number>;
  pattern_audits: Array<Record<string, unknown>>;
};

export type GenerationMetadataResponse = {
  selected_pattern_keys?: string[];
  writing_guidance?: Record<string, unknown>;
  local_pattern_matches?: Array<Record<string, unknown>>;
  generation_policy?: Record<string, unknown>;
  pattern_evidence_scope?: string;
  non_factual_pattern_rules?: string[];
  organization_audit: GenerationMetadataAudit;
};

export type EvidenceAuditResponse = {
  node_id: string;
  version_id?: string | null;
  title: string;
  evidence_count: number;
  required_source_facts: Array<Record<string, unknown>>;
  omitted_required_fact_ids: string[];
  feedback_required_fact_hints: string[];
  omitted_feedback_fact_hints: string[];
  used_evidence_ids: string[];
  unused_high_value_evidence_ids: string[];
  coverage_ratio?: number | null;
  manual_items_with_source_support: string[];
  issues: Array<Record<string, unknown>>;
  artifact_path?: string | null;
};

export type QualityAuditResponse = {
  project_id: string;
  report: Record<string, unknown>;
  artifact_paths: Record<string, string>;
  revision_targets?: QualityAuditRevisionTargets | null;
  feedback?: Record<string, unknown> | null;
};

export type QualityAuditRevisionTargets = {
  project_id: string;
  status: "passed" | "warning" | "blocked" | string;
  summary: string;
  targets: Array<Record<string, unknown>>;
  artifact_json_path?: string | null;
  artifact_markdown_path?: string | null;
};

export type ChapterTask = {
  node_id: string;
  title: string;
  target_word_count?: number | null;
  status: string;
  source_matches: SourceMatch[];
  source_mapping?: SourceMappingResult | null;
  draft_id?: string | null;
  error_message?: string | null;
};

export type OutlineCoverageItem = {
  topic: string;
  status: "covered" | "partial" | "missing" | "not_applicable";
  matched_node_ids: string[];
  matched_source_section_ids: string[];
  reason: string;
};

export type ChapterGenerationPolicy = {
  node_id: string;
  title: string;
  detail_level: "brief" | "normal" | "deep" | "subsection_required";
  target_word_count?: number | null;
  split_required: boolean;
  max_source_matches: number;
  max_evidence_spans: number;
  generate_when_no_source: boolean;
  required_subtopics: string[];
  reason: string;
};

export type RevisionTrigger = {
  node_id: string;
  title: string;
  action: string;
  severity: "info" | "warning" | "error";
  reason: string;
  evidence: string[];
};

export type ChapterRevisionDecision = {
  node_id: string;
  title: string;
  decision: string;
  severity: "info" | "warning" | "error";
  reasons: string[];
  required_changes: string[];
  missing_evidence: string[];
  validation_issue_codes: string[];
  source_section_ids: string[];
  target_word_count?: number | null;
  actual_word_count?: number | null;
};

export type GenerationControlPlan = {
  project_id?: string | null;
  outline_coverage: OutlineCoverageItem[];
  chapter_policies: ChapterGenerationPolicy[];
  revision_triggers: RevisionTrigger[];
};

export type WritingPattern = {
  key: string;
  aliases: string[];
  source_topics: string[];
  preferred_structure: string[];
  required_source_facts: string[];
  auto_writable_moves: string[];
  human_only_items: string[];
  revision_signals: string[];
  corpus_basis: string[];
};

export type WritingPatternLibrary = {
  version: string;
  corpus_scope: string;
  patterns: Record<string, WritingPattern>;
};

export type PatternLibraryResponse = {
  library: WritingPatternLibrary;
  active_path?: string | null;
  generated_path?: string | null;
  generated_available?: boolean | null;
};

export type PatternLibraryAnalyzeResponse = {
  analysis: Record<string, unknown>;
  generated_library: WritingPatternLibrary;
  corpus_dir: string;
  analysis_json_path: string;
  analysis_markdown_path: string;
  generated_path: string;
};

export type PatternLibraryBuildSkillResponse = {
  corpus_dir: string;
  output_dir: string;
  analysis: Record<string, unknown>;
  generated_library: WritingPatternLibrary;
  coverage_report: Record<string, unknown>;
  skill_package: PatternLibrarySkillResponse;
  analysis_json_path: string;
  analysis_markdown_path: string;
  generated_path: string;
  coverage_json_path: string;
  coverage_markdown_path: string;
  skill_package_dir: string;
  skill_manifest_path: string;
};

export type PatternLibraryLearningChange = {
  suggestion_index: number;
  pattern_key: string;
  suggestion_type: string;
  reason?: string | null;
  evidence: string[];
  added_fields: string[];
  added_items: Record<string, string[]>;
};

export type PatternLibraryLearningResponse = {
  learning_report: Record<string, unknown>;
  generated_library: WritingPatternLibrary;
  changes: PatternLibraryLearningChange[];
  selected_suggestion_indexes?: number[] | null;
  source: string;
  generated_path: string;
  learning_report_path: string;
  learning_candidate_markdown_path: string;
};

export type PatternLibraryAuditResponse = {
  report: {
    status: "passed" | "warning" | "blocked" | string;
    summary: string;
    metrics: Record<string, unknown>;
    pattern_audits: Array<Record<string, unknown>>;
    issues: Array<Record<string, unknown>>;
    recommendations: string[];
  };
  library: WritingPatternLibrary;
  source_path?: string | null;
  corpus_dir?: string | null;
  artifact_json_path: string;
  artifact_markdown_path: string;
};

export type PatternLibrarySkillResponse = {
  library: WritingPatternLibrary;
  markdown: string;
  validation_issues: Array<Record<string, unknown>>;
  coverage_report?: Record<string, unknown> | null;
  output_path?: string | null;
  output_dir?: string | null;
  package_paths?: Record<string, string> | null;
  manifest?: Record<string, unknown> | null;
};

export type PatternLibraryPromptCardsResponse = {
  version: string;
  corpus_scope: string;
  evidence_scope: string;
  stage_usage: Record<string, string[]>;
  cards: Record<string, Record<string, unknown>>;
  coverage_report?: Record<string, unknown> | null;
  source_path?: string | null;
};

export type PatternLibraryApplyHistoryResponse = {
  history: Array<Record<string, unknown>>;
  apply_history_path: string;
};

export type PipelineAction = {
  action_id: string;
  stage: string;
  action: string;
  priority: "critical" | "high" | "normal" | "low" | string;
  title: string;
  reason: string;
  target_id?: string | null;
  target_version_id?: string | null;
  target_content_node_id?: string | null;
  target_step_id?: string | null;
  method?: string | null;
  endpoint?: string | null;
  requires_llm: boolean;
  requires_user_confirmation: boolean;
  source_gate?: string | null;
  source_decision?: string | null;
};

export type PipelineActionPlanResponse = {
  project_id: string;
  overall_status: string;
  actions: PipelineAction[];
};

export type GenerationReadinessNode = {
  node_id: string;
  parent_node_id?: string | null;
  title: string;
  level: number;
  has_children: boolean;
  has_generation_contract: boolean;
  status: string;
  next_action: string;
  reason: string;
  target_word_count?: number | null;
  detail_level?: string | null;
  split_required: boolean;
  mapping_status: string;
  source_section_ids: string[];
  evidence_count: number;
  task_status?: string | null;
  selected_version_id?: string | null;
  revision_decision?: string | null;
  revision_severity?: string | null;
  revision_reasons: string[];
  required_changes: string[];
  requires_llm: boolean;
  requires_user_confirmation: boolean;
  endpoint?: string | null;
};

export type GenerationReadinessBatch = {
  group_id: string;
  title: string;
  execution_mode: "auto" | "user_confirmation" | "manual_review" | string;
  reason: string;
  items: Array<{
    node_id: string;
    title: string;
    status: string;
    next_action: string;
    requires_llm: boolean;
    requires_user_confirmation: boolean;
    endpoint?: string | null;
  }>;
};

export type GenerationReadinessResponse = {
  project_id: string;
  status: string;
  summary: string;
  nodes: GenerationReadinessNode[];
  batches: GenerationReadinessBatch[];
  metrics: Record<string, number>;
  artifact_json_path?: string | null;
  artifact_markdown_path?: string | null;
};

export type PipelineBlueprintStage = {
  stage_id: string;
  title: string;
  purpose: string;
  inputs: string[];
  outputs: string[];
  artifacts: string[];
  invariants: string[];
  failure_routes: string[];
  related_actions: string[];
};

export type PipelineBlueprintResponse = {
  blueprint: {
    blueprint_id: string;
    title: string;
    purpose: string;
    stages: PipelineBlueprintStage[];
    invariants: string[];
  };
  markdown: string;
};

export type IterationPhase = {
  phase_id: string;
  step: number;
  title: string;
  objective: string;
  actions: PipelineAction[];
  gate_to_clear?: string | null;
  success_artifacts: string[];
  stop_conditions: string[];
  blocks_later_phases: boolean;
  requires_llm_count: number;
  requires_user_confirmation_count: number;
};

export type IterationPlanResponse = {
  project_id: string;
  status: string;
  summary: string;
  phases: IterationPhase[];
  next_phase_id?: string | null;
  requires_llm_count: number;
  requires_user_confirmation_count: number;
  artifact_json_path?: string | null;
  artifact_markdown_path?: string | null;
};

export type ExecutionWindowAction = PipelineAction & {
  phase_id: string;
  proposal_id?: string | null;
  proposal_status?: string | null;
  proposal_created_at?: string | null;
  blocked_by_phase_id?: string | null;
  blocked_reason?: string | null;
};

export type CurrentExecutionWindowResponse = {
  project_id: string;
  status: string;
  current_phase_id?: string | null;
  current_phase_title?: string | null;
  blocking_reason: string;
  allowed_actions: ExecutionWindowAction[];
  deferred_actions: ExecutionWindowAction[];
  requires_llm_count: number;
  requires_user_confirmation_count: number;
  artifact_json_path?: string | null;
  artifact_markdown_path?: string | null;
};

export type TargetedRevisionAction = {
  action_id: string;
  project_key?: string | null;
  node_id?: string | null;
  title: string;
  status?: string | null;
  action: string;
  stage: string;
  priority: "critical" | "high" | "normal" | "low" | string;
  requires_llm: boolean;
  requires_user_confirmation: boolean;
  reason: string;
  error_message?: string | null;
  endpoint_hint?: string | null;
  next_prompt_context: string[];
};

export type TargetedRevisionPlanProject = {
  key: string;
  project_id: string;
  template_id?: string | null;
  run_status: string;
  generation_scope: string;
  task_count: number;
  passed_count: number;
  failed_count: number;
  pass_rate?: number | null;
  recommended_scope: string;
  actions: TargetedRevisionAction[];
};

export type TargetedRevisionPlanResponse = {
  source_output_root?: string | null;
  source_model?: string | null;
  comparison_verdict?: string | null;
  project_count: number;
  action_count: number;
  action_counts: Record<string, number>;
  priority_counts: Record<string, number>;
  rerun_policy: string;
  projects: TargetedRevisionPlanProject[];
  artifact_json_path?: string | null;
  artifact_markdown_path?: string | null;
};

export type OutlineGenerationStepProgress = {
  project_id: string;
  status: string;
  summary: string;
  steps: Array<{
    step_id: string;
    level: number;
    parent_node_id?: string | null;
    node_ids: string[];
    source_section_ids: string[];
    description: string;
    status: string;
    nodes: Array<Record<string, unknown>>;
  }>;
  artifact_json_path?: string | null;
};

export type OutlineGenerationStepRun = {
  project_id: string;
  step_id: string;
  status: string;
  generated: Array<Record<string, unknown>>;
  skipped: Array<Record<string, unknown>>;
  failed: Array<Record<string, unknown>>;
  progress: OutlineGenerationStepProgress;
  artifact_json_path?: string | null;
};

export type ChildChapterGenerationRun = {
  project_id: string;
  parent_node_id: string;
  recursive: boolean;
  only_pending: boolean;
  candidate_count: number;
  status: string;
  generated: Array<Record<string, unknown>>;
  skipped: Array<Record<string, unknown>>;
  failed: Array<Record<string, unknown>>;
  run_id?: string | null;
  artifact_json_path?: string | null;
};

export type ChapterSupplement = {
  id: string;
  kind: string;
  title: string;
  content: string;
  must_include: boolean;
  sort_order: number;
  created_at: string;
  updated_at: string;
};

export type ChapterAttachment = {
  id: string;
  file_name: string;
  content_type: string;
  artifact_path: string;
  description: string;
  created_at: string;
};

export type ChapterVersion = {
  id: string;
  node_id: string;
  version_no: number;
  source_type: string;
  title: string;
  markdown: string;
  artifact_path?: string | null;
  source_section_ids: string[];
  supplement_ids: string[];
  created_by: string;
  status: string;
  created_at: string;
  content_tree?: GeneratedContentTree;
  content_tree_path?: string | null;
  content_revision_plan?: ContentRevisionPlan;
  content_revision_plan_path?: string | null;
};

export type AIProposal = {
  id: string;
  target_type: string;
  target_id: string;
  suggestion: string;
  preview: Record<string, unknown>;
  status: string;
  created_at: string;
  applied_at?: string | null;
};

export type ChapterWorkspace = {
  outline_node: OutlineNode;
  supplements: ChapterSupplement[];
  attachments: ChapterAttachment[];
  versions: ChapterVersion[];
  selected_version_id?: string | null;
  proposals: AIProposal[];
};

export type DirectoryResponse = {
  project: ProjectResponse;
  template?: { template_id: string; name: string; nodes: TemplateNode[] } | null;
  source_toc?: { items: SourceTocItem[]; artifact_json_path?: string | null; artifact_markdown_path?: string | null } | null;
  outline?: { outline: unknown; artifact_json_path?: string | null; artifact_markdown_path?: string | null } | null;
  generation_control?: { plan: GenerationControlPlan | null; artifact_json_path?: string | null; artifact_markdown_path?: string | null } | null;
  revision_decisions?: { decisions: ChapterRevisionDecision[]; artifact_json_path?: string | null; artifact_markdown_path?: string | null } | null;
  chapter_tasks: ChapterTask[];
  profile_status: string;
  outline_status: string;
  outline_source: string;
  warnings: string[];
};

export type RunResponse = {
  id: string;
  run_id: string;
  status: string;
  task_count: number;
  passed_count: number;
  failed_count: number;
  final_artifact_path?: string | null;
  logs: string[];
};

export type ChapterResponse = {
  node_id: string;
  title: string;
  status: string;
  markdown: string;
  source_matches: SourceMatch[];
  source_mapping?: SourceMappingResult | null;
  version?: ChapterVersion | null;
};

export const API_BASE = import.meta.env.VITE_COALPLAN_API_BASE ?? "http://127.0.0.1:8010";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
    ...init
  });
  if (!response.ok) throw new Error((await response.text()) || `${response.status} ${response.statusText}`);
  return (await response.json()) as T;
}

export const listTemplates = () => request<TemplateSummary[]>("/templates");
export const getTemplateTree = async (templateId: string) => (await request<{ nodes: TemplateNode[] }>(`/templates/${templateId}`)).nodes;
export const listProjects = () => request<ProjectResponse[]>("/projects");
export const createProject = (name: string, templateId: string) => request<ProjectResponse>("/projects", { method: "POST", body: JSON.stringify({ name, template_id: templateId }) });
export const deleteProject = (projectId: string) => request<{ deleted: boolean }>(`/projects/${projectId}`, { method: "DELETE" });
export const uploadBidMarkdown = (projectId: string, fileName: string, content: string) => request<ProjectResponse>(`/projects/${projectId}/bid-markdown`, { method: "POST", body: JSON.stringify({ file_name: fileName, content }) });
export const getSourceSection = (projectId: string, sectionId: string) => request<SourceSection>(`/projects/${projectId}/sections/${encodeURIComponent(sectionId)}`);
export const generateDirectory = (projectId: string) => request<DirectoryResponse>(`/projects/${projectId}/directory`, { method: "POST" });
export const getDirectory = (projectId: string) => request<DirectoryResponse>(`/projects/${projectId}/directory`);
export const getGenerationControlPlan = (projectId: string) => request<{ plan: GenerationControlPlan | null; artifact_json_path?: string | null; artifact_markdown_path?: string | null }>(`/projects/${projectId}/generation-control-plan`);
export const getRevisionDecisions = (projectId: string) => request<{ decisions: ChapterRevisionDecision[]; artifact_json_path?: string | null; artifact_markdown_path?: string | null }>(`/projects/${projectId}/revision-decisions`);
export const getPipelineBlueprint = () => request<PipelineBlueprintResponse>("/pipeline-blueprint");
export const getPipelineActions = (projectId: string) => request<PipelineActionPlanResponse>(`/projects/${projectId}/pipeline-actions`);
export const getGenerationReadiness = (projectId: string) => request<GenerationReadinessResponse>(`/projects/${projectId}/generation-readiness`);
export const executeGenerationReadinessBatch = (projectId: string, groupId?: string | null, includeUserConfirmation = false, limit = 10, respectExecutionWindow = true) =>
  request<Record<string, unknown>>(`/projects/${projectId}/generation-readiness/execute`, {
    method: "POST",
    body: JSON.stringify({ group_id: groupId, include_user_confirmation: includeUserConfirmation, limit, respect_execution_window: respectExecutionWindow })
  });
export const getIterationPlan = (projectId: string) => request<IterationPlanResponse>(`/projects/${projectId}/iteration-plan`);
export const getCurrentExecutionWindow = (projectId: string) => request<CurrentExecutionWindowResponse>(`/projects/${projectId}/current-execution-window`);
export const getTargetedRevisionPlan = (projectId: string) => request<TargetedRevisionPlanResponse>(`/projects/${projectId}/targeted-revision-plan`);
export const getOutlineGenerationSteps = (projectId: string) => request<OutlineGenerationStepProgress>(`/projects/${projectId}/outline-generation-steps`);
export const generateOutlineStep = (projectId: string, stepId: string) => request<OutlineGenerationStepRun>(`/projects/${projectId}/outline-generation-steps/${encodeURIComponent(stepId)}/generate`, { method: "POST" });
export const getPatternLibrary = () => request<PatternLibraryResponse>("/pattern-library");
export const getGeneratedPatternLibrary = (generatedPath?: string | null) => request<PatternLibraryResponse>(`/pattern-library/generated${generatedPath ? `?generated_path=${encodeURIComponent(generatedPath)}` : ""}`);
export const getPatternLibraryApplyHistory = () => request<PatternLibraryApplyHistoryResponse>("/pattern-library/apply-history");
export const getPatternLibrarySkill = (generatedPath?: string | null) => request<PatternLibrarySkillResponse>(`/pattern-library/skill${generatedPath ? `?generated_path=${encodeURIComponent(generatedPath)}` : ""}`);
export const getPatternLibraryPromptCards = (generatedPath?: string | null) => request<PatternLibraryPromptCardsResponse>(`/pattern-library/prompt-cards${generatedPath ? `?generated_path=${encodeURIComponent(generatedPath)}` : ""}`);
export const analyzePatternLibrary = (corpusDir?: string | null, outputDir?: string | null) =>
  request<PatternLibraryAnalyzeResponse>("/pattern-library/analyze", { method: "POST", body: JSON.stringify({ corpus_dir: corpusDir, output_dir: outputDir }) });
export const buildPatternLibrarySkill = (payload: { corpus_dir?: string | null; output_dir?: string | null; skill_name?: string | null; include_source_excerpts?: boolean; max_source_chars?: number | null }) =>
  request<PatternLibraryBuildSkillResponse>("/pattern-library/build-skill", { method: "POST", body: JSON.stringify(payload) });
export const learnPatternLibraryFromQualityIteration = (payload: { project_id?: string | null; learning_report_path?: string | null; learning_report?: Record<string, unknown> | null; selected_suggestion_indexes?: number[] | null; output_dir?: string | null }) =>
  request<PatternLibraryLearningResponse>("/pattern-library/learn-from-quality-iteration", { method: "POST", body: JSON.stringify(payload) });
export const auditPatternLibrary = (generatedPath?: string | null, corpusDir?: string | null, outputDir?: string | null) =>
  request<PatternLibraryAuditResponse>("/pattern-library/audit", { method: "POST", body: JSON.stringify({ generated_path: generatedPath, corpus_dir: corpusDir, output_dir: outputDir }) });
export const applyGeneratedPatternLibrary = (generatedPath?: string | null) =>
  request<PatternLibraryResponse & { applied: boolean; applied_at?: string | null; backup_path?: string | null; apply_log_path?: string | null; apply_history_path?: string | null; apply_history_count?: number | null; coverage_status?: string | null; coverage_issue_count?: number | null; coverage_report?: Record<string, unknown> | null }>("/pattern-library/apply-generated", { method: "POST", body: JSON.stringify({ generated_path: generatedPath }) });
export const exportPatternLibrarySkill = (generatedPath?: string | null, outputPath?: string | null, outputDir?: string | null) =>
  request<PatternLibrarySkillResponse>("/pattern-library/skill/export", { method: "POST", body: JSON.stringify({ generated_path: generatedPath, output_path: outputPath, output_dir: outputDir }) });
export const listOutlineNodes = (projectId: string) => request<OutlineNode[]>(`/projects/${projectId}/outline-nodes`);
export const createOutlineNode = (projectId: string, payload: Partial<OutlineNode> & { title: string }) => request<OutlineNode>(`/projects/${projectId}/outline-nodes`, { method: "POST", body: JSON.stringify(payload) });
export const updateOutlineNode = (projectId: string, nodeId: string, payload: Partial<OutlineNode>) => request<OutlineNode>(`/projects/${projectId}/outline-nodes/${nodeId}`, { method: "PATCH", body: JSON.stringify(payload) });
export const deleteOutlineNode = (projectId: string, nodeId: string) => request<{ deleted: boolean }>(`/projects/${projectId}/outline-nodes/${nodeId}`, { method: "DELETE" });
export const proposeOutlineChange = (projectId: string, suggestion: string, preview?: Record<string, unknown>) => request<AIProposal>(`/projects/${projectId}/outline/propose-ai-change`, { method: "POST", body: JSON.stringify({ suggestion, preview }) });
export const proposeOutlineAIPlan = (projectId: string, suggestion: string) => request<AIProposal>(`/projects/${projectId}/outline/ai-plan`, { method: "POST", body: JSON.stringify({ suggestion }) });
export const proposeControlPlanOutlineRepair = (projectId: string) => request<AIProposal>(`/projects/${projectId}/outline/control-plan-proposal`, { method: "POST" });
export const proposePreGenerationOutlineRefine = (
  projectId: string,
  payload: { mode?: "balanced" | "conservative" | "aggressive"; use_local_corpus?: boolean; use_human_reference?: boolean; human_reference_markdown?: string | null; project_type?: string } = {}
) => request<AIProposal & { refine_summary?: Record<string, unknown>; artifact_json_path?: string | null; artifact_markdown_path?: string | null }>(`/projects/${projectId}/outline/pre-generation-refine`, { method: "POST", body: JSON.stringify(payload) });
export const estimateOutlineWordCounts = (projectId: string, referenceMarkdown?: string | null) => request<{ estimates: Array<Record<string, unknown>>; nodes: OutlineNode[] }>(`/projects/${projectId}/outline/word-counts/estimate`, { method: "POST", body: JSON.stringify({ reference_markdown: referenceMarkdown }) });
export const proposeProjectSubsections = (projectId: string) => request<AIProposal>(`/projects/${projectId}/outline/subsection-proposals`, { method: "POST" });
export const applyOutlineProposal = (projectId: string, proposalId: string) => request<AIProposal>(`/projects/${projectId}/outline/proposals/${proposalId}/apply`, { method: "POST" });
export const rejectOutlineProposal = (projectId: string, proposalId: string) => request<AIProposal>(`/projects/${projectId}/outline/proposals/${proposalId}/reject`, { method: "POST" });
export const getWorkspace = (projectId: string, nodeId: string) => request<ChapterWorkspace>(`/projects/${projectId}/chapters/${nodeId}/workspace`);
export const addSupplement = (projectId: string, nodeId: string, payload: Partial<ChapterSupplement>) => request<ChapterSupplement>(`/projects/${projectId}/chapters/${nodeId}/supplements`, { method: "POST", body: JSON.stringify(payload) });
export const updateSupplement = (projectId: string, nodeId: string, supplementId: string, payload: Partial<ChapterSupplement>) => request<ChapterSupplement>(`/projects/${projectId}/chapters/${nodeId}/supplements/${supplementId}`, { method: "PATCH", body: JSON.stringify(payload) });
export const deleteSupplement = (projectId: string, nodeId: string, supplementId: string) => request<{ deleted: boolean }>(`/projects/${projectId}/chapters/${nodeId}/supplements/${supplementId}`, { method: "DELETE" });
export const generateChapter = (projectId: string, nodeId: string) => request<ChapterResponse>(`/projects/${projectId}/chapters/${nodeId}/generate`, { method: "POST" });
export const generateChildChapters = (projectId: string, parentNodeId: string, recursive = false, onlyPending = false, limit?: number | null) =>
  request<ChildChapterGenerationRun>(`/projects/${projectId}/chapters/${parentNodeId}/children/generate`, {
    method: "POST",
    body: JSON.stringify({ recursive, only_pending: onlyPending, limit: limit ?? null })
  });
export const getChapter = (projectId: string, nodeId: string) => request<ChapterResponse>(`/projects/${projectId}/chapters/${nodeId}`);
export const createManualVersion = (projectId: string, nodeId: string, title: string, markdown: string, select = true) => request<ChapterVersion>(`/projects/${projectId}/chapters/${nodeId}/versions`, { method: "POST", body: JSON.stringify({ title, markdown, select }) });
export const listVersions = (projectId: string, nodeId: string) => request<ChapterVersion[]>(`/projects/${projectId}/chapters/${nodeId}/versions`);
export const getVersionContentTree = (projectId: string, nodeId: string, versionId: string) => request<GeneratedContentTree>(`/projects/${projectId}/chapters/${nodeId}/versions/${versionId}/content-tree`);
export const getVersionContentRevisionPlan = (projectId: string, nodeId: string, versionId: string) => request<ContentRevisionPlan>(`/projects/${projectId}/chapters/${nodeId}/versions/${versionId}/content-revision-plan`);
export const getVersionGenerationMetadata = (projectId: string, nodeId: string, versionId: string) => request<GenerationMetadataResponse>(`/projects/${projectId}/chapters/${nodeId}/versions/${versionId}/generation-metadata`);
export const getVersionEvidenceAudit = (projectId: string, nodeId: string, versionId: string) => request<EvidenceAuditResponse>(`/projects/${projectId}/chapters/${nodeId}/versions/${versionId}/evidence-audit`);
export const executeEvidenceUtilizationRevisionAction = (projectId: string, nodeId: string, versionId: string, action?: string | null) =>
  request<Record<string, unknown>>(`/projects/${projectId}/chapters/${nodeId}/versions/${versionId}/evidence-audit/revision-action`, { method: "POST", body: JSON.stringify({ action }) });
export const executeGenerationMetadataRevisionAction = (projectId: string, nodeId: string, versionId: string, action?: string | null) =>
  request<Record<string, unknown>>(`/projects/${projectId}/chapters/${nodeId}/versions/${versionId}/generation-metadata/revision-action`, { method: "POST", body: JSON.stringify({ action }) });
export const updateVersionContentNode = (projectId: string, nodeId: string, versionId: string, contentNodeId: string, markdown: string, select = true) => request<ChapterVersion>(`/projects/${projectId}/chapters/${nodeId}/versions/${versionId}/content-nodes/${contentNodeId}`, { method: "PATCH", body: JSON.stringify({ markdown, select }) });
export const executeContentRevisionAction = (projectId: string, nodeId: string, versionId: string, contentNodeId: string, action?: string | null) =>
  request<Record<string, unknown>>(`/projects/${projectId}/chapters/${nodeId}/versions/${versionId}/content-nodes/${contentNodeId}/revision-action`, { method: "POST", body: JSON.stringify({ action }) });
export const selectVersion = (projectId: string, nodeId: string, versionId: string) => request<ChapterVersion>(`/projects/${projectId}/chapters/${nodeId}/selected-version`, { method: "PATCH", body: JSON.stringify({ version_id: versionId }) });
export const proposeChapterEdit = (projectId: string, nodeId: string, suggestion: string, baseMarkdown?: string) => request<AIProposal>(`/projects/${projectId}/chapters/${nodeId}/propose-ai-edit`, { method: "POST", body: JSON.stringify({ suggestion, base_markdown: baseMarkdown }) });
export const proposeChapterSubsections = (projectId: string, nodeId: string) => request<AIProposal>(`/projects/${projectId}/chapters/${nodeId}/subsection-proposal`, { method: "POST" });
export const executeRevisionAction = (projectId: string, nodeId: string, action?: string | null) => request<Record<string, unknown>>(`/projects/${projectId}/chapters/${nodeId}/revision-action`, { method: "POST", body: JSON.stringify({ action }) });
export const runQualityAudit = (projectId: string, applyFeedback = true, humanReferenceMarkdown?: string | null) =>
  request<QualityAuditResponse>(`/projects/${projectId}/quality-audit`, { method: "POST", body: JSON.stringify({ apply_feedback: applyFeedback, human_reference_markdown: humanReferenceMarkdown }) });
export const getQualityAuditRevisionTargets = (projectId: string) => request<QualityAuditRevisionTargets>(`/projects/${projectId}/quality-audit/revision-targets`);
export const executeQualityAuditRevisionTarget = (projectId: string, targetIndex: number, action?: string | null) =>
  request<Record<string, unknown>>(`/projects/${projectId}/quality-audit/revision-targets/${targetIndex}/execute`, { method: "POST", body: JSON.stringify({ action }) });
export const executeQualityAuditRevisionTargets = (projectId: string, includeUserConfirmation = false, limit = 10) =>
  request<Record<string, unknown>>(`/projects/${projectId}/quality-audit/revision-targets/execute`, { method: "POST", body: JSON.stringify({ include_user_confirmation: includeUserConfirmation, limit }) });
export const runQualityIteration = (projectId: string, maxRounds = 1, includeUserConfirmation = false, limitPerRound = 10, humanReferenceMarkdown?: string | null) =>
  request<Record<string, unknown>>(`/projects/${projectId}/quality-iteration`, {
    method: "POST",
    body: JSON.stringify({
      max_rounds: maxRounds,
      include_user_confirmation: includeUserConfirmation,
      limit_per_round: limitPerRound,
      human_reference_markdown: humanReferenceMarkdown
    })
  });
export const getQualityIterationLearningReport = (projectId: string) => request<Record<string, unknown>>(`/projects/${projectId}/quality-iteration/learning-report`);
export const applyQualityFeedback = (projectId: string, report: Record<string, unknown>, traceDiagnostics?: Record<string, unknown> | null) =>
  request<Record<string, unknown>>(`/projects/${projectId}/quality-feedback`, { method: "POST", body: JSON.stringify({ report, trace_diagnostics: traceDiagnostics }) });
export const proposeQualityFeedbackOutlineRepair = (projectId: string) => request<AIProposal>(`/projects/${projectId}/quality-feedback/outline-proposal`, { method: "POST" });
export const applyChapterProposal = (projectId: string, nodeId: string, proposalId: string) => request<AIProposal>(`/projects/${projectId}/chapters/${nodeId}/proposals/${proposalId}/apply`, { method: "POST" });
export const rejectChapterProposal = (projectId: string, nodeId: string, proposalId: string) => request<AIProposal>(`/projects/${projectId}/chapters/${nodeId}/proposals/${proposalId}/reject`, { method: "POST" });
export const generateProject = (projectId: string) => request<RunResponse>(`/projects/${projectId}/generate`, { method: "POST" });
export const mergeProject = (projectId: string) => request<RunResponse>(`/projects/${projectId}/merge`, { method: "POST" });

export async function uploadAttachment(projectId: string, nodeId: string, file: File, description: string): Promise<ChapterAttachment> {
  const form = new FormData();
  form.append("file", file);
  form.append("description", description);
  const response = await fetch(`${API_BASE}/projects/${projectId}/chapters/${nodeId}/attachments`, { method: "POST", body: form });
  if (!response.ok) throw new Error(await response.text());
  return (await response.json()) as ChapterAttachment;
}

export const deleteAttachment = (projectId: string, nodeId: string, attachmentId: string) =>
  request<{ deleted: boolean }>(`/projects/${projectId}/chapters/${nodeId}/attachments/${attachmentId}`, { method: "DELETE" });

export async function getFinalMarkdown(projectId: string): Promise<string> {
  const response = await fetch(`${API_BASE}/projects/${projectId}/artifacts/final.md`);
  if (!response.ok) throw new Error(await response.text());
  return response.text();
}
