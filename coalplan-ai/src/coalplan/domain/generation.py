from __future__ import annotations

from datetime import datetime
from uuid import uuid4

from pydantic import BaseModel, Field

from .documents import MarkdownSection, SourceDocument, SourceToc
from .enums import RunStatus, TaskStatus
from .generation_control import EvidenceUtilizationAudit
from .generation_context import GenerationContextState
from .outline import SourceMappingResult, TemplateOutlinePlan
from .profile import ProjectProfile
from .templates import TemplateTree
from .validation import ValidationIssue


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex[:12]}"


class SourceMatch(BaseModel):
    section_id: str
    title_path: list[str]
    snippet: str
    score: float


class ChapterTask(BaseModel):
    node_id: str
    title: str
    target_word_count: int | None = None
    status: TaskStatus = TaskStatus.pending
    source_matches: list[SourceMatch] = Field(default_factory=list)
    source_mapping: SourceMappingResult | None = None
    draft_id: str | None = None
    error_message: str | None = None


class ChapterDraft(BaseModel):
    id: str = Field(default_factory=lambda: new_id("draft"))
    node_id: str
    title: str
    markdown: str
    source_section_ids: list[str] = Field(default_factory=list)
    source_mapping: SourceMappingResult | None = None
    missing_items: list[str] = Field(default_factory=list)
    validation_status: TaskStatus = TaskStatus.pending
    validation_issues: list[ValidationIssue] = Field(default_factory=list)
    evidence_audit: EvidenceUtilizationAudit | None = None
    generation_metadata: dict = Field(default_factory=dict)
    artifact_path: str | None = None


class GenerationRun(BaseModel):
    id: str = Field(default_factory=lambda: new_id("run"))
    project_name: str
    template_id: str
    status: RunStatus = RunStatus.created
    chapter_tasks: list[ChapterTask] = Field(default_factory=list)
    final_artifact_path: str | None = None
    created_at: str = Field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))
    logs: list[str] = Field(default_factory=list)


class Project(BaseModel):
    id: str = Field(default_factory=lambda: new_id("project"))
    name: str
    template_id: str = "coal_fire"
    project_tags: list[str] = Field(default_factory=list)
    selected_outline_template_id: str | None = None
    source_documents: list[SourceDocument] = Field(default_factory=list)
    sections: list[MarkdownSection] = Field(default_factory=list)
    source_toc: SourceToc | None = None
    project_profile: ProjectProfile | None = None
    outline_plan: TemplateOutlinePlan | None = None
    generation_context: GenerationContextState = Field(default_factory=GenerationContextState)
    # Chapter-scoped user choices for generation basis. Kept in project state so
    # existing databases do not need a schema migration.
    chapter_basis_preferences: dict[str, dict] = Field(default_factory=dict)
    template_tree: TemplateTree | None = None
    runs: list[GenerationRun] = Field(default_factory=list)
    created_at: str = Field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))
