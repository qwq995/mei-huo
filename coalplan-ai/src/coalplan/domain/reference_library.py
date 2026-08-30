from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


class ReferenceDocumentKind(str, Enum):
    construction_organization = "construction_organization"
    special_plan = "special_plan"
    bid_document = "bid_document"
    tender_document = "tender_document"
    contract = "contract"
    approval_review = "approval_review"
    standard_guideline = "standard_guideline"
    design_drawing = "design_drawing"
    quantity_price = "quantity_price"
    project_support = "project_support"
    unknown = "unknown"


class KnowledgeRole(str, Enum):
    project_evidence = "project_evidence"
    reference_atom_source = "reference_atom_source"
    writing_guidance = "writing_guidance"
    quality_feedback = "quality_feedback"
    excluded = "excluded"
    unclassified = "unclassified"


class ReferenceReviewStatus(str, Enum):
    imported = "imported"
    ai_candidate = "ai_candidate"
    reviewed = "reviewed"
    published = "published"
    rejected = "rejected"


class ReferenceDocumentEntry(BaseModel):
    document_id: str
    content_hash: str
    absolute_path: str
    relative_path: str
    file_name: str
    project_name: str
    project_type: str
    document_kind: ReferenceDocumentKind
    knowledge_role: KnowledgeRole
    classification_source: str = "rules"
    classification_reasons: list[str] = Field(default_factory=list)
    size_bytes: int
    char_count: int = 0
    line_count: int = 0
    heading_count: int = 0
    table_line_count: int = 0
    image_reference_count: int = 0
    replacement_char_count: int = 0
    quality_tier: str = "D"
    atom_candidate: bool = False
    exact_duplicate_of: str | None = None
    exclusion_reasons: list[str] = Field(default_factory=list)


class ReferenceCorpusCatalog(BaseModel):
    source_root: str
    generated_at: str
    document_count: int
    unique_document_count: int
    exact_duplicate_count: int
    atom_candidate_count: int
    documents: list[ReferenceDocumentEntry] = Field(default_factory=list)
    counts_by_project: dict[str, int] = Field(default_factory=dict)
    counts_by_project_type: dict[str, int] = Field(default_factory=dict)
    counts_by_document_kind: dict[str, int] = Field(default_factory=dict)
    counts_by_knowledge_role: dict[str, int] = Field(default_factory=dict)
    counts_by_quality_tier: dict[str, int] = Field(default_factory=dict)


class ReferenceDocument(BaseModel):
    id: str
    content_hash: str
    source_path: str
    file_name: str
    project_name: str
    project_type: str
    document_kind: ReferenceDocumentKind
    status: ReferenceReviewStatus = ReferenceReviewStatus.imported
    version: int = 1


class ReferenceChapter(BaseModel):
    id: str
    document_id: str
    title_path: list[str] = Field(default_factory=list)
    start_line: int
    end_line: int
    sort_order: int = 0


class ReferenceBlock(BaseModel):
    block_id: str
    title_path: list[str] = Field(default_factory=list)
    content: str
    start_line: int
    end_line: int


class ReferenceFactVariable(BaseModel):
    name: str
    value: str
    variable_type: str = "project_specific"
    migration_policy: str = "不得直接迁移；仅在当前项目证据支持时使用"


class ReferenceAtom(BaseModel):
    id: str
    document_id: str
    project_name: str
    project_type: str
    title_path: list[str] = Field(default_factory=list)
    content: str
    source_block_ids: list[str] = Field(default_factory=list)
    start_line: int
    end_line: int
    engineering_object: str = ""
    specialty: str = ""
    work_item: str = ""
    process: str = ""
    process_stage: str = ""
    chapter_type: str = ""
    content_functions: list[str] = Field(default_factory=list)
    applicability: list[str] = Field(default_factory=list)
    prohibited_scenarios: list[str] = Field(default_factory=list)
    fact_variables: list[ReferenceFactVariable] = Field(default_factory=list)
    quality_score: float = 0.0
    confidence: float = 0.0
    reference_value: str = "high"
    value_reason: str = ""
    reuse_scope: list[str] = Field(default_factory=list)
    migration_warning: list[str] = Field(default_factory=list)
    dedup_group: str = ""
    status: ReferenceReviewStatus = ReferenceReviewStatus.ai_candidate
    version: int = 1


class AtomRetrievalQuery(BaseModel):
    project_name: str
    project_type: str
    chapter_title: str
    parent_titles: list[str] = Field(default_factory=list)
    evidence_summary: str = ""
    writing_topics: list[str] = Field(default_factory=list)
    top_k: int = 5
    excluded_project_names: list[str] = Field(default_factory=list)


class AtomRetrievalResult(BaseModel):
    atom_id: str
    score: float
    match_reason: str
    prompt_use: str
    atom: ReferenceAtom


class AtomLeakageIssue(BaseModel):
    atom_id: str
    value: str
    reason: str


class ChapterAtomUsage(BaseModel):
    id: str
    project_id: str
    node_id: str
    chapter_version_id: str | None = None
    atom_id: str
    retrieval_score: float
    match_reason: str = ""
    prompt_use: str = ""
    decision: str = "selected"
