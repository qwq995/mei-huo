from __future__ import annotations

from typing import Protocol

from coalplan.domain.documents import MarkdownSection


class MarkdownParser(Protocol):
    def canonicalize(self, text: str) -> str:
        """Normalize markdown before section splitting."""

    def split_sections(self, text: str, *, source_file: str) -> list[MarkdownSection]:
        """Split normalized markdown into searchable sections."""

