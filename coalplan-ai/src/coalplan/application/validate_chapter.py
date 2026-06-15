from __future__ import annotations

from coalplan.domain.generation import ChapterDraft
from coalplan.domain.enums import TaskStatus
from coalplan.infrastructure.validation.markdown_contract import MarkdownContractValidator


def validate_chapter(draft: ChapterDraft, *, expected_title: str, source_count: int) -> ChapterDraft:
    result = MarkdownContractValidator().validate(
        draft.markdown,
        expected_title=expected_title,
        source_count=source_count,
        missing_items=draft.missing_items,
    )
    draft.validation_status = TaskStatus.passed if result.passed else TaskStatus.failed
    draft.validation_issues = result.issues
    return draft

