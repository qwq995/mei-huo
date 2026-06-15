from __future__ import annotations

from typing import Protocol

from coalplan.domain.documents import MarkdownSection
from coalplan.domain.generation import SourceMatch
from coalplan.domain.templates import TemplateNode


class SourceRetriever(Protocol):
    def retrieve(self, node: TemplateNode, sections: list[MarkdownSection], *, limit: int = 3) -> list[SourceMatch]:
        """Return source sections relevant to a template node."""

