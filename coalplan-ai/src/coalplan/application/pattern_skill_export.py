from __future__ import annotations

from pathlib import Path

from coalplan.application.pattern_library_coverage import (
    PatternLibraryCoverageReport,
    audit_pattern_library_coverage,
    render_pattern_library_coverage_markdown,
)
from coalplan.application.pipeline_blueprint import render_pipeline_blueprint_markdown
from coalplan.application.serialization import dump_model, to_json_text
from coalplan.application.writing_pattern_library import (
    WritingPattern,
    WritingPatternLibrary,
    build_pattern_prompt_card,
    load_writing_pattern_library,
    render_pattern_prompt_card,
)
from coalplan.application.writing_pattern_requirements import REQUIRED_PATTERN_KEYS


def validate_pattern_library(library: WritingPatternLibrary | None = None) -> list[dict]:
    library = library or load_writing_pattern_library()
    issues: list[dict] = []
    missing = sorted(REQUIRED_PATTERN_KEYS - set(library.patterns))
    for key in missing:
        issues.append(
            {
                "code": "missing_required_pattern",
                "severity": "error",
                "pattern_key": key,
                "message": f"Required writing pattern is missing: {key}",
            }
        )
    for key, pattern in library.patterns.items():
        issues.extend(_validate_pattern(pattern))
        if pattern.key != key:
            issues.append(
                {
                    "code": "pattern_key_mismatch",
                    "severity": "warning",
                    "pattern_key": key,
                    "message": f"Pattern map key `{key}` differs from pattern.key `{pattern.key}`.",
                }
            )
    return issues


def export_pattern_skill_markdown(
    *,
    library: WritingPatternLibrary | None = None,
    output_path: str | Path | None = None,
) -> dict:
    library = library or load_writing_pattern_library()
    issues = validate_pattern_library(library)
    coverage_report = audit_pattern_library_coverage(library)
    markdown = render_pattern_skill_markdown(library, issues=issues, coverage_report=dump_model(coverage_report))
    resolved_output_path = None
    if output_path is not None:
        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(markdown, encoding="utf-8")
        resolved_output_path = str(path.resolve())
    return {
        "library": dump_model(library),
        "markdown": markdown,
        "validation_issues": issues,
        "coverage_report": dump_model(coverage_report),
        "output_path": resolved_output_path,
    }


def export_pattern_skill_package(
    *,
    library: WritingPatternLibrary | None = None,
    output_dir: str | Path,
    skill_name: str = "construction-org-writing-patterns",
    coverage_report: dict | PatternLibraryCoverageReport | None = None,
) -> dict:
    library = library or load_writing_pattern_library()
    issues = validate_pattern_library(library)
    parsed_coverage_report = (
        _parse_coverage_report(coverage_report)
        if coverage_report is not None
        else audit_pattern_library_coverage(library)
    )
    coverage_report_dict = dump_model(parsed_coverage_report)
    skill_markdown = render_pattern_skill_package_markdown(
        library,
        skill_name=skill_name,
        issues=issues,
        coverage_report=coverage_report_dict,
    )
    cards_markdown = render_pattern_cards_reference_markdown(library)
    cards_json = render_pattern_cards_reference_json(library, coverage_report=coverage_report_dict)
    pipeline_markdown = render_pipeline_control_reference_markdown()
    pipeline_blueprint_markdown = render_pipeline_blueprint_markdown()
    coverage_markdown = render_pattern_library_coverage_markdown(parsed_coverage_report)
    manifest = {
        "name": skill_name,
        "version": library.version,
        "corpus_scope": library.corpus_scope,
        "pattern_count": len(library.patterns),
        "validation_issues": issues,
        "coverage_status": parsed_coverage_report.status,
        "coverage_issue_count": len(parsed_coverage_report.issues),
        "coverage_report": coverage_report_dict,
        "files": {
            "skill": "SKILL.md",
            "writing_pattern_cards": "references/writing-pattern-cards.md",
            "writing_pattern_cards_json": "references/writing-pattern-cards.json",
            "pipeline_control": "references/pipeline-control.md",
            "pipeline_blueprint": "references/pipeline-blueprint.md",
            "coverage_report": "references/pattern-library-coverage.md",
        },
    }

    root = Path(output_dir)
    references = root / "references"
    references.mkdir(parents=True, exist_ok=True)
    skill_path = root / "SKILL.md"
    cards_path = references / "writing-pattern-cards.md"
    cards_json_path = references / "writing-pattern-cards.json"
    pipeline_path = references / "pipeline-control.md"
    pipeline_blueprint_path = references / "pipeline-blueprint.md"
    coverage_path = references / "pattern-library-coverage.md"
    manifest_path = root / "manifest.json"
    skill_path.write_text(skill_markdown, encoding="utf-8")
    cards_path.write_text(cards_markdown, encoding="utf-8")
    cards_json_path.write_text(to_json_text(cards_json), encoding="utf-8")
    pipeline_path.write_text(pipeline_markdown, encoding="utf-8")
    pipeline_blueprint_path.write_text(pipeline_blueprint_markdown, encoding="utf-8")
    coverage_path.write_text(coverage_markdown, encoding="utf-8")
    manifest_path.write_text(to_json_text(manifest), encoding="utf-8")
    return {
        "library": dump_model(library),
        "markdown": skill_markdown,
        "validation_issues": issues,
        "coverage_report": coverage_report_dict,
        "output_dir": str(root.resolve()),
        "output_path": str(skill_path.resolve()),
        "package_paths": {
            "skill": str(skill_path.resolve()),
            "writing_pattern_cards": str(cards_path.resolve()),
            "writing_pattern_cards_json": str(cards_json_path.resolve()),
            "pipeline_control": str(pipeline_path.resolve()),
            "pipeline_blueprint": str(pipeline_blueprint_path.resolve()),
            "coverage_report": str(coverage_path.resolve()),
            "manifest": str(manifest_path.resolve()),
        },
        "manifest": manifest,
    }


def _parse_coverage_report(report: dict | PatternLibraryCoverageReport) -> PatternLibraryCoverageReport:
    if isinstance(report, PatternLibraryCoverageReport):
        return report
    return PatternLibraryCoverageReport.model_validate(report)


def render_pattern_skill_package_markdown(
    library: WritingPatternLibrary,
    *,
    skill_name: str = "construction-org-writing-patterns",
    issues: list[dict] | None = None,
    coverage_report: dict | None = None,
) -> str:
    issues = issues if issues is not None else validate_pattern_library(library)
    lines = [
        "---",
        f"name: {skill_name}",
        "description: Use local construction-organization corpus writing patterns as reusable structural guidance for source-grounded chapter generation, outline expansion, source mapping, detail control, and revision decisions.",
        "---",
        "",
        "# Construction Organization Writing Patterns",
        "",
        "This skill is generated from the local construction-organization writing pattern library.",
        "It is a reusable writing-control layer only; it is never a factual source.",
        "Its goal is not to make generated paragraphs identical to human references. It teaches how human-written construction plans organize directories, subsection order, engineering/safety/quality/environment key points, and inspection loops.",
        "",
        "## Scope",
        f"- pattern_library_version: `{library.version}`",
        f"- corpus_scope: `{library.corpus_scope}`",
        f"- pattern_count: {len(library.patterns)}",
        "",
        "## Required References",
        "- Read `references/writing-pattern-cards.md` before generating or revising chapter正文.",
        "- Read `references/pipeline-blueprint.md` before designing or debugging the full generation workflow.",
        "- Read `references/pipeline-control.md` when deciding outline expansion, mapping, detail budget, or revision actions.",
        "",
        "## Core Rules",
        "- Project facts must come from mapped `section_id`, `evidence_id`, user supplements, or explicit manual placeholders.",
        "- Use human-written references as organization patterns only: where a topic belongs, which subpoints should be covered, and how control measures are sequenced.",
        "- Do not optimize for verbatim similarity to human paragraphs; optimize for source-grounded completeness of the current chapter's expected points.",
        "- Use pattern cards to decide outline candidates, source-search requirements, internal writing order, detail allocation, and revision signals.",
        "- Do not invent quantities, dates, coordinates, approvals, parameters, standards, acceptance conclusions, personnel, or equipment.",
        "- Dense craft chapters should be split into source-derived subchapters before long-form generation.",
        "- If expected pattern facts are missing from source evidence, return `missing_evidence`, keep `【需人工补充：...】`, or request human input.",
        "",
        "## Chapter Contract",
        "Generated chapter Markdown must keep only:",
        "",
        "```markdown",
        "# {chapter_title}",
        "",
        "## 主要来源摘要",
        "",
        "## 生成正文",
        "",
        "## 人工补充需补充",
        "",
        "## 特殊备注",
        "```",
        "",
        "`## 特殊备注` is optional and should appear only for high-risk, high-uncertainty, or strongly source-dependent sections.",
        "",
        "## Validation",
    ]
    if issues:
        lines.extend(f"- [{item['severity']}] {item['code']} ({item.get('pattern_key') or '-'}): {item['message']}" for item in issues)
    else:
        lines.append("- passed")
    if coverage_report:
        lines.extend(
            [
                "",
                "## Coverage Audit",
                f"- status: `{coverage_report.get('status')}`",
                f"- summary: {coverage_report.get('summary')}",
                f"- issue_count: {len(coverage_report.get('issues') or [])}",
                "- details: `references/pattern-library-coverage.md`",
            ]
        )
    return "\n".join(lines).strip() + "\n"


def render_pattern_cards_reference_markdown(library: WritingPatternLibrary) -> str:
    lines = [
        "# Writing Pattern Cards",
        "",
        "These cards are generated from local construction-organization documents.",
        "They are structural controls for the LLM, not source evidence.",
        "",
    ]
    for pattern in library.patterns.values():
        lines.extend(
            [
                f"## {pattern.key}",
                "",
                "```text",
                render_pattern_prompt_card(build_pattern_prompt_card(pattern)),
                "```",
                "",
            ]
        )
    return "\n".join(lines).strip() + "\n"


def render_pattern_cards_reference_json(
    library: WritingPatternLibrary,
    *,
    coverage_report: dict | None = None,
) -> dict:
    """Render machine-readable prompt cards for backend/agent reuse.

    The JSON mirrors the Markdown reference but keeps the prompt-card fields
    structured so generation, mapping, detail planning, and revision code can
    inject only the fields needed for a given stage.
    """

    cards = {}
    for key, pattern in library.patterns.items():
        cards[key] = dump_model(build_pattern_prompt_card(pattern))
    return {
        "version": library.version,
        "corpus_scope": library.corpus_scope,
        "evidence_scope": (
            "Structural guidance only; project facts must come from mapped section_id/evidence_id, "
            "user supplements, or manual placeholders."
        ),
        "stage_usage": {
            "outline_planning": ["outline_guidance", "corpus_basis"],
            "source_mapping": ["source_mapping_requirements", "human_only_items"],
            "detail_design": ["detail_design_rules", "generation_moves"],
            "chapter_generation": ["generation_moves", "human_only_items"],
            "revision_gate": ["revision_checks_from_revision_signals", "source_mapping_requirements"],
        },
        "cards": cards,
        "coverage_report": coverage_report,
    }


def render_pipeline_control_reference_markdown() -> str:
    return "\n".join(
        [
            "# Pipeline Control Reference",
            "",
            "Use this reference to decide how pattern guidance flows through the generation pipeline.",
            "Pattern guidance should make the output closer to human construction-plan organization, not copy human wording or unsupported project facts.",
            "",
            "## Stage Use",
            "- Outline planning: use `outline_guidance` and local corpus headings to propose nodes or subchapters. User confirmation is required before applying proposals.",
            "- Source mapping: use `source_mapping_requirements` and `required_source_facts` as search requirements. Return `missing_evidence` rather than weak matches.",
            "- Detail design: use `detail_design_rules` to allocate target word count and decide whether to split dense chapters.",
            "- Chapter generation: use `generation_moves` only inside `## 生成正文`; keep the external Markdown contract unchanged.",
            "- Manual placeholders: keep `human_only_items` as `【需人工补充：...】` unless mapped evidence or user supplements support them.",
            "- Revision gate: use `revision_checks_from_revision_signals` to choose `remap_sources`, `expand_subsections`, `regenerate`, `repair_format`, `request_human_input`, or `disable_node`.",
            "- Version review: before merge, inspect selected-version evidence audits, content revision plans, and generation metadata; unresolved evidence-targeted rewrites or organization repairs must be handled first.",
            "",
            "## Guardrails",
            "- Never treat corpus headings, pattern facts, or prompt cards as project facts.",
            "- Never write template-only factual text when source mapping is empty.",
            "- A retry must carry reasons, missing evidence, omitted required facts, and unused high-value evidence ids.",
            "- Evidence-targeted subsection rewrites must carry the omitted fact id, evidence id, source section id, and fact text into the next prompt.",
            "- Merge only validated and user-selected chapter versions after version review is clear.",
        ]
    ).strip() + "\n"


def render_pattern_skill_markdown(
    library: WritingPatternLibrary,
    *,
    issues: list[dict] | None = None,
    coverage_report: dict | None = None,
) -> str:
    issues = issues if issues is not None else validate_pattern_library(library)
    lines = [
        "# Construction Organization Writing Skill",
        "",
        "This skill is generated from the local construction-organization corpus pattern library.",
        "It is structural writing guidance only; it is never a factual source.",
        "Its goal is not to make generated paragraphs identical to human references. It teaches directory placement, subsection order, engineering/safety/quality/environment key point coverage, and inspection-control loops.",
        "",
        "## Metadata",
        f"- version: `{library.version}`",
        f"- corpus_scope: `{library.corpus_scope}`",
        f"- pattern_count: {len(library.patterns)}",
        "",
        "## Global Rules",
        "- Use mapped `section_id` and `evidence_id` as the only source of project facts.",
        "- Use human-written references as organization patterns only: topic placement, expected subpoints, sequencing, and control-loop shape.",
        "- Do not optimize for verbatim similarity to human paragraphs; optimize for source-grounded completeness of the current chapter's expected points.",
        "- Use this skill to choose chapter structure, detail order, and revision expectations.",
        "- Do not invent quantities, dates, coordinates, approvals, parameters, standards, acceptance conclusions, personnel, or equipment.",
        "- If a fact is expected by the pattern but absent from evidence, keep `【需人工补充：...】` or explain why it is out of scope.",
        "- Dense craft chapters should be split into source-derived subsections before full prose generation.",
        "",
        "## How To Use In The Pipeline",
        "",
        "Use this skill as a reusable writing-control layer, not as source material.",
        "",
        "1. **Outline planning**: match template node titles, four-module text, and source TOC headings to pattern aliases, source topics, and local corpus common headings.",
        "2. **Source mapping**: use `required_source_facts` as search requirements. If supporting sections cannot be found, return `missing_evidence` instead of weak matches.",
        "3. **Detail design**: use `preferred_structure` as the internal order for target word count allocation. High target words or dense craft evidence should trigger subsection generation.",
        "4. **Chapter generation**: write only the fixed chapter Markdown contract; use pattern steps to organize `## 生成正文`, not as extra headings unless the project outline already contains those subheadings.",
        "5. **Manual placeholders**: items in `human_only_items` must remain `【需人工补充：...】` unless mapped evidence, user supplements, or approved project data support them.",
        "6. **Revision gate**: if `revision_signals` appear in the draft, route to `regenerate`, `remap_sources`, `expand_subsections`, `repair_format`, or `request_human_input` according to the evidence problem.",
        "",
        "## Chapter Markdown Contract",
        "",
        "Every generated chapter must keep exactly this external structure:",
        "",
        "```markdown",
        "# {chapter_title}",
        "",
        "## 主要来源摘要",
        "",
        "## 生成正文",
        "",
        "## 人工补充需补充",
        "",
        "## 特殊备注",
        "```",
        "",
        "`## 特殊备注` is optional and should appear only for high-risk, high-uncertainty, or strongly source-dependent sections.",
        "",
        "## Revision Decision Hints",
        "",
        "- `remap_sources`: expected pattern facts exist in the source corpus or audit hints but did not reach the chapter prompt.",
        "- `regenerate`: mapped evidence or `quality_feedback_required_facts` reached the prompt but the draft omitted them.",
        "- `expand_subsections`: the chapter matches a dense craft/management pattern, target word count is high, or local corpus headings show natural subtopics.",
        "- `request_human_input`: the pattern expects drawings, approvals, final parameters, personnel/equipment, coordinates, measured data, or acceptance conclusions absent from evidence.",
        "- `disable_node`: the node is template-only and no source evidence or user supplement supports it.",
        "",
        "## Validation",
    ]
    if issues:
        lines.extend(f"- [{item['severity']}] {item['code']} ({item.get('pattern_key') or '-'}): {item['message']}" for item in issues)
    else:
        lines.append("- passed")
    if coverage_report:
        lines.extend(
            [
                "",
                "## Coverage Audit",
                f"- status: `{coverage_report.get('status')}`",
                f"- summary: {coverage_report.get('summary')}",
                f"- issue_count: {len(coverage_report.get('issues') or [])}",
            ]
        )
    lines.extend(["", "## Patterns"])
    for pattern in library.patterns.values():
        lines.extend(_render_pattern_block(pattern))
    return "\n".join(lines).strip() + "\n"


def _validate_pattern(pattern: WritingPattern) -> list[dict]:
    issues: list[dict] = []
    required_fields = {
        "aliases": pattern.aliases,
        "preferred_structure": pattern.preferred_structure,
        "required_source_facts": pattern.required_source_facts,
        "human_only_items": pattern.human_only_items,
        "revision_signals": pattern.revision_signals,
    }
    for field, value in required_fields.items():
        if not value:
            severity = "error" if field in {"preferred_structure", "required_source_facts"} else "warning"
            issues.append(
                {
                    "code": f"empty_{field}",
                    "severity": severity,
                    "pattern_key": pattern.key,
                    "message": f"Pattern `{pattern.key}` has no `{field}` entries.",
                }
            )
    if len(pattern.preferred_structure) < 3:
        issues.append(
            {
                "code": "short_preferred_structure",
                "severity": "warning",
                "pattern_key": pattern.key,
                "message": "Preferred structure should contain at least three writing steps.",
            }
        )
    return issues


def _render_pattern_block(pattern: WritingPattern) -> list[str]:
    lines = [
        "",
        f"### {pattern.key}",
        "",
        _line("aliases", pattern.aliases),
        _line("source_topics", pattern.source_topics),
        _line("local_corpus_common_headings", pattern.corpus_common_headings[:16]),
        "",
        "Preferred structure:",
        *[f"{index}. {item}" for index, item in enumerate(pattern.preferred_structure, start=1)],
        "",
        _line("required_source_facts", pattern.required_source_facts),
        _line("auto_writable_moves", pattern.auto_writable_moves),
        _line("human_only_items", pattern.human_only_items),
        _line("revision_signals", pattern.revision_signals),
        _line("corpus_basis", pattern.corpus_basis),
        "",
        "Prompt card:",
        "```text",
        render_pattern_prompt_card(build_pattern_prompt_card(pattern)),
        "```",
    ]
    return lines


def _line(label: str, items: list[str]) -> str:
    return f"- {label}: " + ("; ".join(items) if items else "-")
