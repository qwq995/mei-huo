from __future__ import annotations

from pydantic import BaseModel, Field


class GeneratedContentSourceLink(BaseModel):
    evidence_id: str | None = None
    section_id: str
    title_path: list[str] = Field(default_factory=list)
    confidence: float = 0.0
    reason: str = ""
    matched_terms: list[str] = Field(default_factory=list)


class GeneratedContentNode(BaseModel):
    id: str
    title: str
    level: int
    title_path: list[str] = Field(default_factory=list)
    start_line: int
    end_line: int
    markdown: str = ""
    body: str = ""
    source_links: list[GeneratedContentSourceLink] = Field(default_factory=list)
    children: list["GeneratedContentNode"] = Field(default_factory=list)


class GeneratedContentTree(BaseModel):
    version_id: str | None = None
    node_id: str
    title: str
    markdown_line_count: int
    nodes: list[GeneratedContentNode] = Field(default_factory=list)
    artifact_path: str | None = None
