from __future__ import annotations

from coalplan.domain.documents import SourceDocument, stable_id
from coalplan.domain.enums import DocumentRole, ParseStatus
from coalplan.domain.generation import Project
from coalplan.ports.markdown_parser import MarkdownParser
from coalplan.ports.repository import ArtifactRepository

from .persist_source_index import persist_source_index


def ingest_bid_markdown(
    project: Project,
    *,
    file_name: str,
    content: str,
    parser: MarkdownParser,
    artifacts: ArtifactRepository,
) -> Project:
    raw_path = artifacts.write_text(project.id, "inputs/bid.md", content)
    normalized = parser.canonicalize(content)
    normalized_path = artifacts.write_text(project.id, "inputs/bid.normalized.md", normalized)
    sections = parser.split_sections(normalized, source_file=file_name)
    source_toc = persist_source_index(project.id, sections, artifacts)
    document = SourceDocument(
        id=stable_id("doc", project.id, file_name),
        file_name=file_name,
        role=DocumentRole.bid_markdown,
        status=ParseStatus.split,
        raw_artifact_path=raw_path,
        normalized_artifact_path=normalized_path,
    )
    project.source_documents = [doc for doc in project.source_documents if doc.role != DocumentRole.bid_markdown]
    project.source_documents.append(document)
    project.sections = sections
    project.source_toc = source_toc
    return project
