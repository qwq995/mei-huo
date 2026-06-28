from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


CoverageStatus = Literal["covered", "partial", "missing", "not_applicable"]
DetailLevel = Literal["brief", "normal", "deep", "subsection_required"]
RevisionAction = Literal[
    "accept",
    "repair_format",
    "remap_sources",
    "expand_subsections",
    "regenerate",
    "request_human_input",
    "disable_node",
]


class OutlineCoverageItem(BaseModel):
    topic: str
    status: CoverageStatus
    matched_node_ids: list[str] = Field(default_factory=list)
    matched_source_section_ids: list[str] = Field(default_factory=list)
    reason: str = ""


class ChapterGenerationPolicy(BaseModel):
    node_id: str
    title: str
    detail_level: DetailLevel = "normal"
    target_word_count: int | None = None
    split_required: bool = False
    max_source_matches: int = 8
    max_evidence_spans: int = 14
    generate_when_no_source: bool = False
    required_subtopics: list[str] = Field(default_factory=list)
    source_subtopics: list[str] = Field(default_factory=list)
    writing_pattern_key: str | None = None
    writing_pattern_matches: list[str] = Field(default_factory=list)
    pattern_required_source_facts: list[str] = Field(default_factory=list)
    pattern_human_only_items: list[str] = Field(default_factory=list)
    pattern_prompt_cards: list[dict] = Field(default_factory=list)
    reason: str = ""


class RevisionTrigger(BaseModel):
    node_id: str
    title: str
    action: RevisionAction
    severity: Literal["info", "warning", "error"] = "warning"
    reason: str
    evidence: list[str] = Field(default_factory=list)


class GenerationControlPlan(BaseModel):
    project_id: str | None = None
    outline_coverage: list[OutlineCoverageItem] = Field(default_factory=list)
    chapter_policies: list[ChapterGenerationPolicy] = Field(default_factory=list)
    revision_triggers: list[RevisionTrigger] = Field(default_factory=list)

    @property
    def has_blocking_issues(self) -> bool:
        return any(trigger.severity == "error" for trigger in self.revision_triggers)


class EvidenceUtilizationIssue(BaseModel):
    code: str
    severity: Literal["info", "warning", "error"] = "warning"
    message: str
    evidence_ids: list[str] = Field(default_factory=list)
    terms: list[str] = Field(default_factory=list)
    suggested_action: RevisionAction | None = None


class RequiredSourceFact(BaseModel):
    fact_id: str
    evidence_id: str
    section_id: str
    fact_type: Literal["quantity", "parameter", "date", "standard", "method", "other"] = "other"
    text: str
    tokens: list[str] = Field(default_factory=list)
    reason: str = ""


class EvidenceUtilizationAudit(BaseModel):
    node_id: str
    title: str
    evidence_count: int = 0
    required_source_facts: list[RequiredSourceFact] = Field(default_factory=list)
    omitted_required_fact_ids: list[str] = Field(default_factory=list)
    feedback_required_fact_hints: list[str] = Field(default_factory=list)
    omitted_feedback_fact_hints: list[str] = Field(default_factory=list)
    used_evidence_ids: list[str] = Field(default_factory=list)
    unused_high_value_evidence_ids: list[str] = Field(default_factory=list)
    coverage_ratio: float | None = None
    manual_items_with_source_support: list[str] = Field(default_factory=list)
    issues: list[EvidenceUtilizationIssue] = Field(default_factory=list)


class ChapterRevisionDecision(BaseModel):
    node_id: str
    title: str
    decision: RevisionAction
    severity: Literal["info", "warning", "error"] = "info"
    reasons: list[str] = Field(default_factory=list)
    required_changes: list[str] = Field(default_factory=list)
    missing_evidence: list[str] = Field(default_factory=list)
    validation_issue_codes: list[str] = Field(default_factory=list)
    source_section_ids: list[str] = Field(default_factory=list)
    target_word_count: int | None = None
    actual_word_count: int | None = None
    evidence_audit: EvidenceUtilizationAudit | None = None


QualityFeedbackActionKey = Literal[
    "increase_detail_budget",
    "repair_outline_coverage",
    "strengthen_evidence_utilization",
    "add_missing_common_topics",
    "improve_trace_archiving",
]
QualityFeedbackTarget = Literal["detail_budget", "outline", "evidence", "common_topics", "traceability"]


class ChapterPolicyAdjustment(BaseModel):
    node_id: str
    title: str
    current_target_word_count: int | None = None
    next_target_word_count: int | None = None
    current_detail_level: DetailLevel | None = None
    next_detail_level: DetailLevel | None = None
    next_max_source_matches: int | None = None
    next_max_evidence_spans: int | None = None
    split_required: bool | None = None
    reason: str = ""


class QualityFeedbackAction(BaseModel):
    action: QualityFeedbackActionKey
    target: QualityFeedbackTarget
    severity: Literal["info", "warning", "error"] = "warning"
    reason: str = ""
    source_metrics: dict[str, float | int | str | None] = Field(default_factory=dict)
    next_steps: list[str] = Field(default_factory=list)
    missing_heading_examples: list[str] = Field(default_factory=list)
    omitted_source_facts: list[str] = Field(default_factory=list)
    missing_common_topics: list[str] = Field(default_factory=list)
    policy_adjustments: list[ChapterPolicyAdjustment] = Field(default_factory=list)


class QualityFeedbackPlan(BaseModel):
    project_key: str | None = None
    actions: list[QualityFeedbackAction] = Field(default_factory=list)
    revision_triggers: list[RevisionTrigger] = Field(default_factory=list)

    @property
    def has_actions(self) -> bool:
        return bool(self.actions)
