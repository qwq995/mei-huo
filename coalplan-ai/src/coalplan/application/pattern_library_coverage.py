from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from coalplan.application.local_corpus_patterns import LocalCorpusAnalysis
from coalplan.application.writing_pattern_library import WritingPattern, WritingPatternLibrary, load_writing_pattern_library
from coalplan.application.writing_pattern_requirements import REQUIRED_PATTERN_KEYS


Severity = Literal["info", "warning", "error"]
CoverageStatus = Literal["passed", "warning", "blocked"]


class PatternCoverageIssue(BaseModel):
    code: str
    severity: Severity
    pattern_key: str | None = None
    message: str
    suggested_action: str
    evidence: list[str] = Field(default_factory=list)


class PatternCoveragePatternAudit(BaseModel):
    pattern_key: str
    status: CoverageStatus
    counts: dict[str, int] = Field(default_factory=dict)
    corpus_stats: dict[str, int] = Field(default_factory=dict)
    issues: list[PatternCoverageIssue] = Field(default_factory=list)


class PatternLibraryCoverageReport(BaseModel):
    status: CoverageStatus
    summary: str
    metrics: dict[str, Any] = Field(default_factory=dict)
    pattern_audits: list[PatternCoveragePatternAudit] = Field(default_factory=list)
    issues: list[PatternCoverageIssue] = Field(default_factory=list)
    recommendations: list[str] = Field(default_factory=list)


def audit_pattern_library_coverage(
    library: WritingPatternLibrary | dict | None = None,
    *,
    analysis: LocalCorpusAnalysis | dict | None = None,
) -> PatternLibraryCoverageReport:
    """Audit whether a local writing-pattern library is strong enough for reusable generation control."""

    parsed_library = _parse_library(library)
    parsed_analysis = _parse_analysis(analysis)

    issues: list[PatternCoverageIssue] = []
    pattern_audits: list[PatternCoveragePatternAudit] = []
    pattern_keys = set(parsed_library.patterns)
    missing_keys = sorted(REQUIRED_PATTERN_KEYS - pattern_keys)
    for key in missing_keys:
        issues.append(
            PatternCoverageIssue(
                code="missing_required_pattern",
                severity="error",
                pattern_key=key,
                message=f"Required construction-organization writing pattern is missing: {key}",
                suggested_action="Add this pattern before exporting or applying the library as a reusable skill.",
            )
        )

    for key in sorted(pattern_keys | REQUIRED_PATTERN_KEYS):
        pattern = parsed_library.patterns.get(key)
        if pattern is None:
            continue
        audit = _audit_single_pattern(pattern, analysis=parsed_analysis)
        pattern_audits.append(audit)
        issues.extend(audit.issues)

    if parsed_analysis is not None:
        issues.extend(_audit_corpus_support(parsed_analysis))

    error_count = sum(1 for issue in issues if issue.severity == "error")
    warning_count = sum(1 for issue in issues if issue.severity == "warning")
    status: CoverageStatus = "blocked" if error_count else "warning" if warning_count else "passed"
    metrics = {
        "pattern_count": len(parsed_library.patterns),
        "required_pattern_count": len(REQUIRED_PATTERN_KEYS),
        "missing_required_pattern_count": len(missing_keys),
        "issue_count": len(issues),
        "error_count": error_count,
        "warning_count": warning_count,
        "coverage_ratio": round(
            (len(REQUIRED_PATTERN_KEYS) - len(missing_keys)) / max(1, len(REQUIRED_PATTERN_KEYS)),
            3,
        ),
    }
    if parsed_analysis is not None:
        metrics.update(
            {
                "corpus_sample_count": parsed_analysis.sample_count,
                "corpus_content_kind": parsed_analysis.corpus_content_kind,
                "corpus_project_type_count": len(parsed_analysis.project_type_counts),
            }
        )

    recommendations = _build_recommendations(issues, parsed_analysis)
    summary = _summary_for(status, metrics)
    return PatternLibraryCoverageReport(
        status=status,
        summary=summary,
        metrics=metrics,
        pattern_audits=pattern_audits,
        issues=issues,
        recommendations=recommendations,
    )


def render_pattern_library_coverage_markdown(report: PatternLibraryCoverageReport) -> str:
    lines = [
        "# Pattern Library Coverage Audit",
        "",
        f"- status: `{report.status}`",
        f"- summary: {report.summary}",
        "",
        "## Metrics",
    ]
    for key, value in report.metrics.items():
        lines.append(f"- {key}: {value}")

    lines.extend(["", "## Pattern Audits"])
    for audit in report.pattern_audits:
        lines.extend(
            [
                f"### {audit.pattern_key}",
                f"- status: `{audit.status}`",
                "- counts: "
                + ", ".join(f"{key}={value}" for key, value in audit.counts.items()),
            ]
        )
        if audit.corpus_stats:
            lines.append(
                "- corpus_stats: "
                + ", ".join(f"{key}={value}" for key, value in audit.corpus_stats.items())
            )
        if audit.issues:
            lines.append("- issues:")
            for issue in audit.issues:
                lines.append(f"  - [{issue.severity}] {issue.code}: {issue.message}")
        else:
            lines.append("- issues: -")
        lines.append("")

    lines.extend(["## Issues"])
    if report.issues:
        for issue in report.issues:
            evidence = "; ".join(issue.evidence[:5])
            suffix = f" Evidence: {evidence}" if evidence else ""
            lines.append(
                f"- [{issue.severity}] {issue.code} ({issue.pattern_key or '-'}): "
                f"{issue.message} Suggested action: {issue.suggested_action}{suffix}"
            )
    else:
        lines.append("- passed")

    lines.extend(["", "## Recommendations"])
    if report.recommendations:
        lines.extend(f"- {item}" for item in report.recommendations)
    else:
        lines.append("- No extra recommendation.")
    return "\n".join(lines).strip() + "\n"


def _parse_library(library: WritingPatternLibrary | dict | None) -> WritingPatternLibrary:
    if library is None:
        return load_writing_pattern_library()
    if isinstance(library, WritingPatternLibrary):
        return library
    return WritingPatternLibrary.model_validate(library)


def _parse_analysis(analysis: LocalCorpusAnalysis | dict | None) -> LocalCorpusAnalysis | None:
    if analysis is None:
        return None
    if isinstance(analysis, LocalCorpusAnalysis):
        return analysis
    return LocalCorpusAnalysis.model_validate(analysis)


def _audit_single_pattern(
    pattern: WritingPattern,
    *,
    analysis: LocalCorpusAnalysis | None,
) -> PatternCoveragePatternAudit:
    list_fields = {
        "aliases": pattern.aliases,
        "source_topics": pattern.source_topics,
        "corpus_common_headings": pattern.corpus_common_headings,
        "preferred_structure": pattern.preferred_structure,
        "required_source_facts": pattern.required_source_facts,
        "auto_writable_moves": pattern.auto_writable_moves,
        "human_only_items": pattern.human_only_items,
        "revision_signals": pattern.revision_signals,
        "corpus_basis": pattern.corpus_basis,
    }
    counts = {field: len(values) for field, values in list_fields.items()}
    issues: list[PatternCoverageIssue] = []

    required_minimums = {
        "aliases": 1,
        "source_topics": 1,
        "preferred_structure": 3,
        "required_source_facts": 2,
        "auto_writable_moves": 1,
        "human_only_items": 1,
        "revision_signals": 1,
        "corpus_basis": 1,
    }
    for field, minimum in required_minimums.items():
        if counts[field] < minimum:
            severity: Severity = "error" if field in {"preferred_structure", "required_source_facts"} else "warning"
            issues.append(
                PatternCoverageIssue(
                    code=f"thin_{field}",
                    severity=severity,
                    pattern_key=pattern.key,
                    message=f"Pattern `{pattern.key}` has only {counts[field]} `{field}` entries; expected at least {minimum}.",
                    suggested_action=f"Enrich `{field}` from local human-written construction plans or quality-iteration learning.",
                )
            )
    if counts["corpus_common_headings"] == 0:
        issues.append(
            PatternCoverageIssue(
                code="missing_local_heading_seeds",
                severity="warning",
                pattern_key=pattern.key,
                message="No local corpus heading seeds are available for outline/subsection expansion.",
                suggested_action="Refresh the pattern library from local TOC corpus or add reusable heading seeds manually.",
            )
        )
    if counts["required_source_facts"] < counts["preferred_structure"] // 2:
        issues.append(
            PatternCoverageIssue(
                code="weak_source_fact_contract",
                severity="warning",
                pattern_key=pattern.key,
                message="The pattern has fewer source-fact requirements than its writing structure expects.",
                suggested_action="Add source-search requirements so mapping can retrieve facts before generation.",
            )
        )

    corpus_stats: dict[str, int] = {}
    if analysis is not None:
        stats = analysis.pattern_stats.get(pattern.key)
        if stats is not None:
            corpus_stats = {
                "file_count": stats.file_count,
                "heading_count": stats.heading_count,
                "body_excerpt_count": stats.body_excerpt_count,
                "common_heading_count": len(stats.common_headings),
            }
            if stats.file_count == 0:
                issues.append(
                    PatternCoverageIssue(
                        code="no_corpus_file_support",
                        severity="warning",
                        pattern_key=pattern.key,
                        message="The analyzed local corpus did not identify any file supporting this writing pattern.",
                        suggested_action="Add representative construction-organization samples or keep this pattern as hand-maintained guidance.",
                    )
                )
            elif stats.common_headings and counts["corpus_common_headings"] == 0:
                issues.append(
                    PatternCoverageIssue(
                        code="analysis_has_headings_but_library_empty",
                        severity="warning",
                        pattern_key=pattern.key,
                        message="The latest corpus analysis found heading seeds that are not reflected in the library.",
                        suggested_action="Regenerate the pattern library from the latest corpus analysis before applying it.",
                        evidence=[title for title, _count in stats.common_headings[:5]],
                    )
                )

    error_count = sum(1 for issue in issues if issue.severity == "error")
    warning_count = sum(1 for issue in issues if issue.severity == "warning")
    status: CoverageStatus = "blocked" if error_count else "warning" if warning_count else "passed"
    return PatternCoveragePatternAudit(
        pattern_key=pattern.key,
        status=status,
        counts=counts,
        corpus_stats=corpus_stats,
        issues=issues,
    )


def _audit_corpus_support(analysis: LocalCorpusAnalysis) -> list[PatternCoverageIssue]:
    issues: list[PatternCoverageIssue] = []
    if analysis.sample_count == 0:
        return [
            PatternCoverageIssue(
                code="empty_local_corpus",
                severity="error",
                message="The local construction-organization corpus contains no usable samples.",
                suggested_action="Add human-written construction-organization text or TOC samples before training a reusable skill.",
            )
        ]
    if analysis.sample_count < 5:
        issues.append(
            PatternCoverageIssue(
                code="small_local_corpus",
                severity="warning",
                message=f"Only {analysis.sample_count} corpus samples were analyzed.",
                suggested_action="Use the resulting skill as a demo candidate until more project types and chapter styles are added.",
            )
        )
    if len(analysis.project_type_counts) < 2:
        issues.append(
            PatternCoverageIssue(
                code="narrow_project_type_coverage",
                severity="warning",
                message="The analyzed corpus covers fewer than two project-type categories.",
                suggested_action="Add samples from coal fire, municipal, hydropower/slope, and new-energy projects for broader reuse.",
                evidence=list(analysis.project_type_counts),
            )
        )
    return issues


def _build_recommendations(
    issues: list[PatternCoverageIssue],
    analysis: LocalCorpusAnalysis | None,
) -> list[str]:
    recommendations: list[str] = []
    codes = {issue.code for issue in issues}
    if "missing_required_pattern" in codes:
        recommendations.append("Do not apply/export as the active reusable skill until all required patterns exist.")
    if "thin_required_source_facts" in codes or "weak_source_fact_contract" in codes:
        recommendations.append("Strengthen required_source_facts before source mapping; otherwise generated chapters will stay generic.")
    if "missing_local_heading_seeds" in codes or "analysis_has_headings_but_library_empty" in codes:
        recommendations.append("Refresh local corpus heading seeds so outline repair and subsection expansion can follow human-written structures.")
    if "thin_revision_signals" in codes:
        recommendations.append("Add revision_signals so the pipeline can decide when to remap, split, regenerate, or request human input.")
    if analysis is not None and analysis.corpus_content_kind != "text_extraction":
        recommendations.append("Current corpus appears TOC-heavy; add source-body excerpts to improve engineering, safety, and quality writing moves.")
    if not recommendations:
        recommendations.append("The library is fit for prompt-card use; keep quality-iteration learning enabled after real project runs.")
    return recommendations


def _summary_for(status: CoverageStatus, metrics: dict[str, Any]) -> str:
    if status == "passed":
        return "Pattern library covers the required construction-organization writing patterns with usable field depth."
    if status == "blocked":
        return (
            "Pattern library is not ready for active reusable-skill use: "
            f"{metrics['error_count']} blocking issue(s), "
            f"{metrics['warning_count']} warning(s)."
        )
    return (
        "Pattern library is usable with caution: "
        f"{metrics['warning_count']} warning(s) should be reviewed before broad reuse."
    )
