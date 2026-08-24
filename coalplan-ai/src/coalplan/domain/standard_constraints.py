from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


class StandardDocumentStatus(str, Enum):
    imported = "imported"
    processing = "processing"
    ready = "ready"
    partial = "partial"
    failed = "failed"
    excluded = "excluded"


class ConstraintReviewStatus(str, Enum):
    ai_candidate = "ai_candidate"
    published = "published"
    rejected = "rejected"


class ConstraintSeverity(str, Enum):
    blocking = "blocking"
    warning = "warning"
    advisory = "advisory"


class FindingStatus(str, Enum):
    open = "open"
    pending_recheck = "pending_recheck"
    ai_resolved = "ai_resolved"
    manually_resolved = "manually_resolved"
    not_applicable = "not_applicable"
    accepted_risk = "accepted_risk"


class StandardDocument(BaseModel):
    id: str
    standard_code: str = ""
    name: str
    category: str = "其他"
    disciplines: list[str] = Field(default_factory=list)
    project_types: list[str] = Field(default_factory=list)
    source_path: str = ""
    file_name: str
    content_hash: str
    status: StandardDocumentStatus = StandardDocumentStatus.imported
    version: int = 1
    atom_count: int = 0
    warning_count: int = 0


class ConstraintAtom(BaseModel):
    id: str
    document_id: str
    standard_code: str = ""
    standard_name: str
    clause_no: str = ""
    title_path: list[str] = Field(default_factory=list)
    source_text: str
    normalized_requirement: str
    constraint_type: str
    review_method: str = "semantic_review"
    severity: ConstraintSeverity = ConstraintSeverity.warning
    disciplines: list[str] = Field(default_factory=list)
    project_types: list[str] = Field(default_factory=list)
    chapter_scopes: list[str] = Field(default_factory=list)
    keywords: list[str] = Field(default_factory=list)
    applicability: list[str] = Field(default_factory=list)
    exceptions: list[str] = Field(default_factory=list)
    evidence_required: list[str] = Field(default_factory=list)
    ai_fixable: bool = False
    repair_instruction: str = ""
    start_line: int
    end_line: int
    confidence: float = 0.0
    status: ConstraintReviewStatus = ConstraintReviewStatus.ai_candidate


class StandardMatch(BaseModel):
    document_id: str
    score: float
    match_reason: str
    decision: str = "selected"


class ConstraintMatch(BaseModel):
    run_id: str = ""
    atom_id: str
    document_id: str
    node_id: str = ""
    score: float
    match_reason: str


class ComplianceReviewRun(BaseModel):
    id: str
    project_id: str
    status: str = "running"
    chapter_count: int = 0
    matched_document_count: int = 0
    candidate_constraint_count: int = 0
    finding_count: int = 0
    warnings: list[str] = Field(default_factory=list)
    summary: dict = Field(default_factory=dict)


class ComplianceFinding(BaseModel):
    id: str
    run_id: str = ""
    project_id: str
    node_id: str
    chapter_title: str
    chapter_version_id: str | None = None
    atom_id: str
    document_id: str
    standard_code: str = ""
    standard_name: str
    clause_no: str = ""
    constraint_text: str
    severity: ConstraintSeverity
    verdict: str
    explanation: str
    evidence_quote: str = ""
    ai_fixable: bool = False
    suggested_fix: str = ""
    status: FindingStatus = FindingStatus.open
    resolution_note: str = ""
    resolved_version_id: str | None = None
