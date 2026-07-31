from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class WritingUnitSpec(BaseModel):
    unit_id: str
    title: str
    objective: str = ""
    target_word_count: int = 600
    writing_topics: list[str] = Field(default_factory=list)
    evidence_terms: list[str] = Field(default_factory=list)
    content_functions: list[str] = Field(default_factory=list)
    sequence: int = 1


class WritingUnitTrace(BaseModel):
    unit_id: str
    title: str
    target_word_count: int
    source_section_ids: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)
    reference_atom_ids: list[str] = Field(default_factory=list)
    writing_skill_keys: list[str] = Field(default_factory=list)
    prompt_source_roles: list[str] = Field(
        default_factory=lambda: ["bid_evidence", "reference_atoms", "writing_skills"]
    )


class ChapterRollingSummary(BaseModel):
    node_id: str
    title: str
    status: Literal["planned", "generated", "needs_repair"] = "planned"
    overview: str = ""
    established_facts: list[str] = Field(default_factory=list)
    decisions: list[str] = Field(default_factory=list)
    interfaces: list[str] = Field(default_factory=list)
    terminology: list[str] = Field(default_factory=list)
    unresolved_items: list[str] = Field(default_factory=list)
    source_section_ids: list[str] = Field(default_factory=list)
    reference_atom_ids: list[str] = Field(default_factory=list)
    writing_unit_ids: list[str] = Field(default_factory=list)
    updated_at: str = Field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))


class GenerationContextState(BaseModel):
    project_overview: str = ""
    construction_scope: list[str] = Field(default_factory=list)
    confirmed_global_facts: list[str] = Field(default_factory=list)
    terminology: list[str] = Field(default_factory=list)
    construction_interfaces: list[str] = Field(default_factory=list)
    unresolved_items: list[str] = Field(default_factory=list)
    chapter_summaries: dict[str, ChapterRollingSummary] = Field(default_factory=dict)
    generated_node_order: list[str] = Field(default_factory=list)
    updated_at: str = Field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))
