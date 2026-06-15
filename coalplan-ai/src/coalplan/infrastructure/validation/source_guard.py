from __future__ import annotations

from coalplan.domain.generation import SourceMatch
from coalplan.domain.validation import ValidationIssue, ValidationResult


class SourceGuard:
    def validate_sources(self, matches: list[SourceMatch], *, allow_empty: bool = True) -> ValidationResult:
        if matches or allow_empty:
            return ValidationResult(passed=True, issues=[])
        return ValidationResult(
            passed=False,
            issues=[ValidationIssue(code="no_source", message="No source section matched this template node.")],
        )

