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
