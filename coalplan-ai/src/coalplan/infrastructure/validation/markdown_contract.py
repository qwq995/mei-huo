from __future__ import annotations

import re

from coalplan.domain.validation import ValidationIssue, ValidationResult


REQUIRED_HEADINGS = ["## 主要来源摘要", "## 生成正文", "## 人工补充需补充"]
OPTIONAL_HEADINGS = ["## 特殊备注"]
ALLOWED_HEADINGS = set(REQUIRED_HEADINGS + OPTIONAL_HEADINGS)


class MarkdownContractValidator:
    def validate(self, markdown: str, *, expected_title: str, source_count: int, missing_items: list[str]) -> ValidationResult:
        issues: list[ValidationIssue] = []
        stripped = markdown.strip()
        if stripped.startswith("{") or stripped.startswith("["):
            issues.append(ValidationIssue(code="json_output", message="LLM output must be Markdown, not JSON."))
        if not re.search(rf"^#\s+{re.escape(expected_title)}\s*$", markdown, re.M):
            issues.append(ValidationIssue(code="missing_title", message=f"Missing first-level heading: {expected_title}"))
        for heading in REQUIRED_HEADINGS:
            if heading not in markdown:
                issues.append(ValidationIssue(code="missing_required_heading", message=f"Missing section: {heading}"))
        for heading in re.findall(r"^##\s+.+$", markdown, flags=re.M):
            if heading.strip() not in ALLOWED_HEADINGS:
                issues.append(ValidationIssue(code="unexpected_heading", message=f"Unexpected section heading: {heading.strip()}"))
        if source_count > 0 and not _has_source_summary_items(markdown):
            issues.append(ValidationIssue(code="missing_source_summary", message="Generated chapter must list source summaries."))
        if missing_items and not _has_manual_fill_items(markdown):
            issues.append(ValidationIssue(code="missing_manual_placeholder", message="Manual-fill items must remain as placeholders."))
        if re.search(r"(最终|实际|批准|确认).{0,12}(为|是)\s*\d", markdown):
            issues.append(ValidationIssue(code="possible_guessed_fact", message="Output appears to assert final factual parameters."))
        return ValidationResult(passed=not issues, issues=issues)


def _has_source_summary_items(markdown: str) -> bool:
    block = _heading_block(markdown, "主要来源摘要")
    return (
        "来源" in block
        or "section_id" in block
        or "evidence_id" in block
        or bool(re.search(r"^\s*[-*]\s+\S+", block, flags=re.M))
        or bool(re.search(r"^\s*\|.+\|\s*$", block, flags=re.M))
    )


def _has_manual_fill_items(markdown: str) -> bool:
    block = _heading_block(markdown, "人工补充需补充")
    return "【需人工补充" in block or bool(re.search(r"^\s*[-*]\s+\S+", block, flags=re.M)) or bool(re.search(r"^\s*\d+[.)、]\s+\S+", block, flags=re.M))


def _heading_block(markdown: str, heading: str) -> str:
    match = re.search(rf"^##\s+{re.escape(heading)}\s*$([\s\S]*?)(?=^##\s+|\Z)", markdown, flags=re.M)
    return match.group(1) if match else ""
