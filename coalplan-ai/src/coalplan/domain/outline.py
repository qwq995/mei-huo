from __future__ import annotations

from pydantic import BaseModel, Field


class TemplateOutlineNode(BaseModel):
    node_id: str
    title: str
    level: int
    enabled: bool = True
    source_hints: list[str] = Field(default_factory=list)
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
