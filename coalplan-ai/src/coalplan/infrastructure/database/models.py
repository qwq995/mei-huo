from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


def now() -> datetime:
    return datetime.now()


class ProjectRecord(Base):
    __tablename__ = "projects"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    template_id: Mapped[str] = mapped_column(Text, nullable=False)
    state_json: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now, onupdate=now, nullable=False)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime)


class SourceDocumentRecord(Base):
    __tablename__ = "source_documents"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    file_name: Mapped[str] = mapped_column(Text, nullable=False)
    role: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    raw_artifact_path: Mapped[str | None] = mapped_column(Text)
    normalized_artifact_path: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now, nullable=False)


class SourceSectionRecord(Base):
    __tablename__ = "source_sections"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    section_id: Mapped[str] = mapped_column(Text, index=True)
    title_path_json: Mapped[str] = mapped_column(Text, nullable=False)
    level: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    keywords_json: Mapped[str] = mapped_column(Text, nullable=False)
    source_file: Mapped[str] = mapped_column(Text, nullable=False)
    start_line: Mapped[int | None] = mapped_column(Integer)
    end_line: Mapped[int | None] = mapped_column(Integer)
    char_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    snippet: Mapped[str] = mapped_column(Text, default="", nullable=False)

    __table_args__ = (UniqueConstraint("project_id", "section_id", name="uq_source_sections_project_section"),)


class TemplateCatalogRecord(Base):
    __tablename__ = "template_catalog"

    template_id: Mapped[str] = mapped_column(Text, primary_key=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    path: Mapped[str | None] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now, onupdate=now, nullable=False)


class ProjectOutlineNodeRecord(Base):
    __tablename__ = "project_outline_nodes"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    node_id: Mapped[str] = mapped_column(Text, index=True)
    parent_id: Mapped[str | None] = mapped_column(Text, index=True)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    level: Mapped[int] = mapped_column(Integer, nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    source_rules_json: Mapped[str] = mapped_column(Text, nullable=False)
    auto_fill_json: Mapped[str] = mapped_column(Text, nullable=False)
    manual_fill_json: Mapped[str] = mapped_column(Text, nullable=False)
    special_notes_json: Mapped[str] = mapped_column(Text, nullable=False)
    target_word_count: Mapped[int | None] = mapped_column(Integer)
    origin: Mapped[str] = mapped_column(Text, default="template", nullable=False)
    template_anchor_id: Mapped[str | None] = mapped_column(Text, index=True)
    source_hints_json: Mapped[str] = mapped_column(Text, default="[]", nullable=False)
    matched_skill_keys_json: Mapped[str] = mapped_column(Text, default="[]", nullable=False)
    chapter_summary_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)
    selected_version_id: Mapped[str | None] = mapped_column(Text, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now, onupdate=now, nullable=False)

    __table_args__ = (UniqueConstraint("project_id", "node_id", name="uq_outline_project_node"),)


class ChapterTaskRecord(Base):
    __tablename__ = "chapter_tasks"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    run_id: Mapped[str | None] = mapped_column(Text, index=True)
    node_id: Mapped[str] = mapped_column(Text, index=True)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    source_matches_json: Mapped[str] = mapped_column(Text, nullable=False)
    draft_id: Mapped[str | None] = mapped_column(Text)
    error_message: Mapped[str | None] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now, onupdate=now, nullable=False)


class ChapterSupplementRecord(Base):
    __tablename__ = "chapter_supplements"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    node_id: Mapped[str] = mapped_column(Text, index=True)
    kind: Mapped[str] = mapped_column(Text, nullable=False, default="text")
    title: Mapped[str] = mapped_column(Text, nullable=False, default="")
    content: Mapped[str] = mapped_column(Text, nullable=False, default="")
    must_include: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now, onupdate=now, nullable=False)


class ProjectMemoryRecord(Base):
    """Durable user-confirmed project facts reusable across chapters."""

    __tablename__ = "project_memories"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    topic: Mapped[str] = mapped_column(Text, nullable=False, default="")
    content: Mapped[str] = mapped_column(Text, nullable=False, default="")
    source_node_id: Mapped[str | None] = mapped_column(Text, index=True)
    source_supplement_id: Mapped[str | None] = mapped_column(Text, index=True)
    tags_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    status: Mapped[str] = mapped_column(Text, nullable=False, default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now, onupdate=now, nullable=False)


class SupplementBatchRecord(Base):
    __tablename__ = "supplement_batches"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    payload_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    status: Mapped[str] = mapped_column(Text, nullable=False, default="draft")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now, onupdate=now, nullable=False)


class ChapterAttachmentRecord(Base):
    __tablename__ = "chapter_attachments"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    node_id: Mapped[str] = mapped_column(Text, index=True)
    file_name: Mapped[str] = mapped_column(Text, nullable=False)
    content_type: Mapped[str] = mapped_column(Text, nullable=False, default="application/octet-stream")
    artifact_path: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now, nullable=False)


class ChapterVersionRecord(Base):
    __tablename__ = "chapter_versions"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    node_id: Mapped[str] = mapped_column(Text, index=True)
    version_no: Mapped[int] = mapped_column(Integer, nullable=False)
    source_type: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    markdown: Mapped[str] = mapped_column(Text, nullable=False)
    artifact_path: Mapped[str | None] = mapped_column(Text)
    prompt_trace_id: Mapped[str | None] = mapped_column(Text)
    source_section_ids_json: Mapped[str] = mapped_column(Text, nullable=False)
    supplement_ids_json: Mapped[str] = mapped_column(Text, nullable=False)
    created_by: Mapped[str] = mapped_column(Text, default="system", nullable=False)
    status: Mapped[str] = mapped_column(Text, default="candidate", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now, nullable=False)

    __table_args__ = (UniqueConstraint("project_id", "node_id", "version_no", name="uq_chapter_versions_number"),)


class AIChangeProposalRecord(Base):
    __tablename__ = "ai_change_proposals"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    target_type: Mapped[str] = mapped_column(Text, nullable=False)
    target_id: Mapped[str] = mapped_column(Text, nullable=False)
    suggestion: Mapped[str] = mapped_column(Text, nullable=False)
    preview_json: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, default="pending", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now, nullable=False)
    applied_at: Mapped[datetime | None] = mapped_column(DateTime)


class GenerationRunRecord(Base):
    __tablename__ = "generation_runs"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    project_name: Mapped[str] = mapped_column(Text, nullable=False)
    template_id: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    final_artifact_path: Mapped[str | None] = mapped_column(Text)
    logs_json: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now, nullable=False)


class GenerationJobRecord(Base):
    __tablename__ = "generation_jobs"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    job_type: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    status: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    stage: Mapped[str] = mapped_column(Text, nullable=False, default="queued")
    current: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    message: Mapped[str] = mapped_column(Text, nullable=False, default="")
    payload_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    result_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    error: Mapped[str | None] = mapped_column(Text)
    retried_from: Mapped[str | None] = mapped_column(Text, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now, onupdate=now, nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime)
    pause_requested: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class LLMTraceRecord(Base):
    __tablename__ = "llm_traces"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    project_id: Mapped[str | None] = mapped_column(Text, index=True)
    run_id: Mapped[str | None] = mapped_column(Text, index=True)
    node_id: Mapped[str | None] = mapped_column(Text, index=True)
    provider: Mapped[str | None] = mapped_column(Text)
    model: Mapped[str | None] = mapped_column(Text)
    trace_path: Mapped[str | None] = mapped_column(Text)
    prompt: Mapped[str | None] = mapped_column(Text)
    response: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now, nullable=False)


class ReferenceDocumentRecord(Base):
    __tablename__ = "reference_documents"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    content_hash: Mapped[str] = mapped_column(Text, unique=True, index=True)
    source_path: Mapped[str] = mapped_column(Text, nullable=False)
    file_name: Mapped[str] = mapped_column(Text, nullable=False)
    project_name: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    project_type: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    document_kind: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now, onupdate=now, nullable=False)


class ReferenceChapterRecord(Base):
    __tablename__ = "reference_chapters"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    document_id: Mapped[str] = mapped_column(ForeignKey("reference_documents.id", ondelete="CASCADE"), index=True)
    title_path_json: Mapped[str] = mapped_column(Text, nullable=False)
    start_line: Mapped[int] = mapped_column(Integer, nullable=False)
    end_line: Mapped[int] = mapped_column(Integer, nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)


class ReferenceAtomRecord(Base):
    __tablename__ = "reference_atoms"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    document_id: Mapped[str] = mapped_column(ForeignKey("reference_documents.id", ondelete="CASCADE"), index=True)
    project_name: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    project_type: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    title_path_json: Mapped[str] = mapped_column(Text, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    source_block_ids_json: Mapped[str] = mapped_column(Text, nullable=False)
    start_line: Mapped[int] = mapped_column(Integer, nullable=False)
    end_line: Mapped[int] = mapped_column(Integer, nullable=False)
    tags_json: Mapped[str] = mapped_column(Text, nullable=False)
    applicability_json: Mapped[str] = mapped_column(Text, nullable=False)
    prohibited_scenarios_json: Mapped[str] = mapped_column(Text, nullable=False)
    fact_variables_json: Mapped[str] = mapped_column(Text, nullable=False)
    quality_score: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now, onupdate=now, nullable=False)


class ChapterAtomUsageRecord(Base):
    __tablename__ = "chapter_atom_usages"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    project_id: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    node_id: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    chapter_version_id: Mapped[str | None] = mapped_column(Text, index=True)
    atom_id: Mapped[str] = mapped_column(ForeignKey("reference_atoms.id"), index=True)
    retrieval_score: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    match_reason: Mapped[str] = mapped_column(Text, nullable=False, default="")
    prompt_use: Mapped[str] = mapped_column(Text, nullable=False, default="")
    decision: Mapped[str] = mapped_column(Text, nullable=False, default="selected")
    prompt_snapshot_path: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now, nullable=False)


class StandardDocumentRecord(Base):
    __tablename__ = "standard_documents"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    standard_code: Mapped[str] = mapped_column(Text, nullable=False, default="", index=True)
    name: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    category: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    disciplines_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    project_types_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    source_path: Mapped[str] = mapped_column(Text, nullable=False, default="")
    file_name: Mapped[str] = mapped_column(Text, nullable=False)
    content_hash: Mapped[str] = mapped_column(Text, nullable=False, unique=True, index=True)
    status: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    atom_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    warning_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now, onupdate=now, nullable=False)


class ConstraintAtomRecord(Base):
    __tablename__ = "constraint_atoms"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    document_id: Mapped[str] = mapped_column(ForeignKey("standard_documents.id", ondelete="CASCADE"), index=True)
    standard_code: Mapped[str] = mapped_column(Text, nullable=False, default="", index=True)
    standard_name: Mapped[str] = mapped_column(Text, nullable=False)
    clause_no: Mapped[str] = mapped_column(Text, nullable=False, default="", index=True)
    title_path_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    source_text: Mapped[str] = mapped_column(Text, nullable=False)
    normalized_requirement: Mapped[str] = mapped_column(Text, nullable=False)
    constraint_type: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    review_method: Mapped[str] = mapped_column(Text, nullable=False, default="semantic_review")
    severity: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    disciplines_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    project_types_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    chapter_scopes_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    keywords_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    applicability_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    exceptions_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    check_method: Mapped[str] = mapped_column(Text, nullable=False, default="semantic_review")
    evidence_required_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    ai_fixable: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    repair_instruction: Mapped[str] = mapped_column(Text, nullable=False, default="")
    start_line: Mapped[int] = mapped_column(Integer, nullable=False)
    end_line: Mapped[int] = mapped_column(Integer, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    status: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now, onupdate=now, nullable=False)


class ProjectStandardMatchRecord(Base):
    __tablename__ = "project_standard_matches"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    document_id: Mapped[str] = mapped_column(ForeignKey("standard_documents.id", ondelete="CASCADE"), index=True)
    score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    match_reason: Mapped[str] = mapped_column(Text, nullable=False, default="")
    decision: Mapped[str] = mapped_column(Text, nullable=False, default="selected")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now, nullable=False)

    __table_args__ = (UniqueConstraint("project_id", "document_id", name="uq_project_standard_match"),)


class ComplianceFindingRecord(Base):
    __tablename__ = "compliance_findings"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    run_id: Mapped[str] = mapped_column(Text, nullable=False, default="", index=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    node_id: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    chapter_title: Mapped[str] = mapped_column(Text, nullable=False)
    chapter_version_id: Mapped[str | None] = mapped_column(Text, index=True)
    atom_id: Mapped[str] = mapped_column(ForeignKey("constraint_atoms.id"), index=True)
    document_id: Mapped[str] = mapped_column(ForeignKey("standard_documents.id"), index=True)
    standard_code: Mapped[str] = mapped_column(Text, nullable=False, default="")
    standard_name: Mapped[str] = mapped_column(Text, nullable=False)
    clause_no: Mapped[str] = mapped_column(Text, nullable=False, default="")
    constraint_text: Mapped[str] = mapped_column(Text, nullable=False)
    severity: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    verdict: Mapped[str] = mapped_column(Text, nullable=False)
    explanation: Mapped[str] = mapped_column(Text, nullable=False)
    evidence_quote: Mapped[str] = mapped_column(Text, nullable=False, default="")
    ai_fixable: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    suggested_fix: Mapped[str] = mapped_column(Text, nullable=False, default="")
    status: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    resolution_note: Mapped[str] = mapped_column(Text, nullable=False, default="")
    resolved_version_id: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now, onupdate=now, nullable=False)


class ComplianceReviewRunRecord(Base):
    __tablename__ = "compliance_review_runs"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    status: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    chapter_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    matched_document_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    candidate_constraint_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    finding_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    warnings_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    summary_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now, nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime)


class ComplianceConstraintMatchRecord(Base):
    __tablename__ = "compliance_constraint_matches"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("compliance_review_runs.id", ondelete="CASCADE"), index=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    node_id: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    chapter_version_id: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    atom_id: Mapped[str] = mapped_column(ForeignKey("constraint_atoms.id"), index=True)
    document_id: Mapped[str] = mapped_column(ForeignKey("standard_documents.id"), index=True)
    score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    match_reason: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now, nullable=False)
