from __future__ import annotations

from pydantic import BaseModel, Field


class ProjectProfile(BaseModel):
    project_name: str | None = None
    project_type: str | None = None
    location: str | None = None
    construction_scope: list[str] = Field(default_factory=list)
    key_quantities: list[str] = Field(default_factory=list)
    main_methods: list[str] = Field(default_factory=list)
    schedule: list[str] = Field(default_factory=list)
    quality_safety_environment_targets: list[str] = Field(default_factory=list)
    risk_points: list[str] = Field(default_factory=list)
    missing_items: list[str] = Field(default_factory=list)
    source_section_ids: list[str] = Field(default_factory=list)
    artifact_json_path: str | None = None
    artifact_markdown_path: str | None = None
