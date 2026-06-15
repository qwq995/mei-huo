from __future__ import annotations

from coalplan.domain.documents import MarkdownSection

from .canonicalizer import MarkdownCanonicalizer
from .section_splitter import MarkdownSectionSplitter


class MarkdownDocumentParser:
    def __init__(self) -> None:
        self.canonicalizer = MarkdownCanonicalizer()
        self.splitter = MarkdownSectionSplitter()

    def canonicalize(self, text: str) -> str:
        return self.canonicalizer.canonicalize(text)

    def split_sections(self, text: str, *, source_file: str) -> list[MarkdownSection]:
        return self.splitter.split_sections(text, source_file=source_file)

