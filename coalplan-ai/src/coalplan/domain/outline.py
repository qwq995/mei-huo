from __future__ import annotations

from pydantic import BaseModel, Field


class OutlineProjectSummary(BaseModel):
    overview: str = ""
    construction_scope: list[str] = Field(default_factory=list)
    key_conditions: list[str] = Field(default_factory=list)
    key_methods: list[str] = Field(default_factory=list)
    key_risks: list[str] = Field(default_factory=list)
    source_section_ids: list[str] = Field(default_factory=list)


class ChapterSummary(BaseModel):
    overview: str = ""
    scope: list[str] = Field(default_factory=list)
    key_points: list[str] = Field(default_factory=list)
    source_basis: list[str] = Field(default_factory=list)
    missing_information: list[str] = Field(default_factory=list)
    generation_role: str = "leaf"
    coverage_status: str = "unknown"
    writing_unit_hints: list[str] = Field(default_factory=list)
    generated_overview: str = ""
    established_facts: list[str] = Field(default_factory=list)
    interfaces: list[str] = Field(default_factory=list)
    terminology: list[str] = Field(default_factory=list)
    unresolved_items: list[str] = Field(default_factory=list)
    reference_atom_ids: list[str] = Field(default_factory=list)
    updated_at: str = ""


class TemplateOutlineNode(BaseModel):
    node_id: str
    title: str
    level: int
    parent_node_id: str | None = None
    enabled: bool = True
    origin: str = "template"
    template_anchor_id: str | None = None
    source_hints: list[str] = Field(default_factory=list)
    source_toc_paths: list[str] = Field(default_factory=list)
    matched_skill_keys: list[str] = Field(default_factory=list)
    chapter_summary: ChapterSummary = Field(default_factory=ChapterSummary)
    main_sources: list[str] = Field(default_factory=list)
    auto_fill: list[str] = Field(default_factory=list)
    manual_fill: list[str] = Field(default_factory=list)
    special_notes: list[str] = Field(default_factory=list)
    target_word_count: int | None = None


class OutlineGenerationStep(BaseModel):
    step_id: str
    level: int
    parent_node_id: str | None = None
    node_ids: list[str] = Field(default_factory=list)
    source_section_ids: list[str] = Field(default_factory=list)
    description: str = ""


class TemplateOutlinePlan(BaseModel):
    template_id: str
    plan_source: str = "ai_plan"
    project_summary: OutlineProjectSummary = Field(default_factory=OutlineProjectSummary)
    nodes: list[TemplateOutlineNode] = Field(default_factory=list)
    generation_steps: list[OutlineGenerationStep] = Field(default_factory=list)
    artifact_json_path: str | None = None
    artifact_markdown_path: str | None = None


class SourceMappingMatch(BaseModel):
    section_id: str
    title_path: list[str] = Field(default_factory=list)
    usage: str = "fact"
    reason: str = ""
    confidence: float = 0.0
    evidence_ids: list[str] = Field(default_factory=list)


class SourceEvidenceSpan(BaseModel):
    evidence_id: str
    section_id: str
    title_path: list[str] = Field(default_factory=list)
    start_line: int | None = None
    end_line: int | None = None
    usage: str = "fact"
    template_module: str = "main_sources"
    matched_terms: list[str] = Field(default_factory=list)
    quote: str = ""
    summary: str = ""
    reason: str = ""
    confidence: float = 0.0


class SourceMappingResult(BaseModel):
    node_id: str
    matches: list[SourceMappingMatch] = Field(default_factory=list)
    evidence: list[SourceEvidenceSpan] = Field(default_factory=list)
    missing_evidence: list[str] = Field(default_factory=list)
    validation_issues: list[str] = Field(default_factory=list)
    artifact_path: str | None = None
    evidence_artifact_path: str | None = None
