from __future__ import annotations

from typing import Protocol

from coalplan.domain.templates import TemplateTree


class TemplateLoader(Protocol):
    def load(self, template_id: str) -> TemplateTree:
        """Load a generation template tree."""

