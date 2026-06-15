from __future__ import annotations

from hashlib import sha1
from typing import Any

from pydantic import BaseModel, Field

from .enums import DocumentRole, ParseStatus


def stable_id(prefix: str, *parts: Any) -> str:
    text = "::".join(str(part) for part in parts)
    return f"{prefix}_{sha1(text.encode('utf-8')).hexdigest()[:12]}"


class SourceDocument(BaseModel):
    id: str
    file_name: str
    role: DocumentRole = DocumentRole.bid_markdown
    status: ParseStatus = ParseStatus.uploaded
    raw_artifact_path: str | None = None
    normalized_artifact_path: str | None = None
    notes: list[str] = Field(default_factory=list)


class MarkdownSection(BaseModel):
    id: str
    title_path: list[str]
    level: int
    content: str
    keywords: list[str] = Field(default_factory=list)
    source_file: str
    start_line: int | None = None
    end_line: int | None = None

    @property
    def title(self) -> str:
        return self.title_path[-1] if self.title_path else self.source_file

    @property
    def path_text(self) -> str:
        return " > ".join(self.title_path)


class SourceTocItem(BaseModel):
    section_id: str
    title_path: list[str]
    level: int
    start_line: int | None = None
    end_line: int | None = None
    keywords: list[str] = Field(default_factory=list)
    char_count: int = 0
    snippet: str = ""


class SourceToc(BaseModel):
    items: list[SourceTocItem] = Field(default_factory=list)
    artifact_json_path: str | None = None
    artifact_markdown_path: str | None = None
