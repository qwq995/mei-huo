from __future__ import annotations

from typing import Protocol

from coalplan.domain.generation import Project


class ProjectRepository(Protocol):
    def save(self, project: Project) -> Project:
        """Persist a project."""

    def get(self, project_id: str) -> Project:
        """Load a project by id."""

    def list(self) -> list[Project]:
        """List projects."""


class ArtifactRepository(Protocol):
    def write_text(self, project_id: str, relative_path: str, content: str) -> str:
        """Write a text artifact and return its absolute path."""

    def read_text(self, path: str) -> str:
        """Read a text artifact."""

