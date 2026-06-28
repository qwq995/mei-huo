from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from coalplan.application.local_corpus_patterns import (
    analyze_local_corpus,
    build_pattern_library_from_analysis,
    render_corpus_analysis_markdown,
)
from coalplan.application.pattern_library_coverage import (
    audit_pattern_library_coverage,
    render_pattern_library_coverage_markdown,
)
from coalplan.application.pattern_skill_export import (
    export_pattern_skill_markdown,
    export_pattern_skill_package,
    render_pattern_cards_reference_json,
)
from coalplan.application.serialization import dump_model, to_json_text
from coalplan.application.writing_pattern_library import WritingPatternLibrary, load_writing_pattern_library


DEFAULT_LOCAL_CORPUS_DIR = Path(r"C:\Users\Lenovo\Documents\煤火\施组目录结构_纯文本")


def active_pattern_library_path() -> Path:
    package_root = Path(__file__).resolve().parents[1]
    return package_root / "assets" / "generation" / "writing_patterns.json"


def default_generated_pattern_library_path() -> Path:
    return active_pattern_library_path().with_name("writing_patterns.generated.json")


def read_active_pattern_library() -> dict:
    library = load_writing_pattern_library()
    return {
        "library": dump_model(library),
        "active_path": str(active_pattern_library_path()),
        "generated_path": str(default_generated_pattern_library_path()),
        "generated_available": default_generated_pattern_library_path().exists(),
    }


def pattern_library_apply_history_path(active_path: str | Path | None = None) -> Path:
    target = Path(active_path) if active_path else active_pattern_library_path()
    return target.with_name(f"{target.stem}.apply-history.json")


def read_pattern_library_apply_history(*, active_path: str | Path | None = None) -> dict:
    path = pattern_library_apply_history_path(active_path)
    if not path.exists():
        return {"history": [], "apply_history_path": str(path)}
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        payload = []
    return {
        "history": payload if isinstance(payload, list) else [],
        "apply_history_path": str(path),
    }


def read_generated_pattern_library(path: str | Path | None = None) -> dict:
    generated_path = Path(path) if path else default_generated_pattern_library_path()
    if not generated_path.exists():
        raise FileNotFoundError(f"Generated pattern library not found: {generated_path}")
    library = WritingPatternLibrary.model_validate_json(generated_path.read_text(encoding="utf-8"))
    return {"library": dump_model(library), "generated_path": str(generated_path)}


def read_pattern_prompt_cards(*, generated_path: str | Path | None = None) -> dict:
    if generated_path:
        source = Path(generated_path)
        if not source.exists():
            raise FileNotFoundError(f"Generated pattern library not found: {source}")
        library = WritingPatternLibrary.model_validate_json(source.read_text(encoding="utf-8"))
        source_path = source
    else:
        library = load_writing_pattern_library()
        source_path = active_pattern_library_path()
    payload = render_pattern_cards_reference_json(library)
    payload["source_path"] = str(source_path)
    return payload


def export_pattern_skill(
    *,
    generated_path: str | Path | None = None,
    output_path: str | Path | None = None,
    output_dir: str | Path | None = None,
) -> dict:
    if generated_path:
        source = Path(generated_path)
        if not source.exists():
            raise FileNotFoundError(f"Generated pattern library not found: {source}")
        library = WritingPatternLibrary.model_validate_json(source.read_text(encoding="utf-8"))
    else:
        library = load_writing_pattern_library()
    if output_dir:
        return export_pattern_skill_package(library=library, output_dir=output_dir)
    return export_pattern_skill_markdown(library=library, output_path=output_path)


def audit_pattern_library(
    *,
    generated_path: str | Path | None = None,
    library: dict[str, Any] | WritingPatternLibrary | None = None,
    corpus_dir: str | Path | None = None,
    output_dir: str | Path,
) -> dict:
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    if library is not None:
        target_library = WritingPatternLibrary.model_validate(library) if isinstance(library, dict) else library
        source_path = None
    elif generated_path:
        source = Path(generated_path)
        if not source.exists():
            raise FileNotFoundError(f"Generated pattern library not found: {source}")
        target_library = WritingPatternLibrary.model_validate_json(source.read_text(encoding="utf-8"))
        source_path = source
    else:
        target_library = load_writing_pattern_library()
        source_path = active_pattern_library_path()

    analysis = analyze_local_corpus(corpus_dir) if corpus_dir else None
    report = audit_pattern_library_coverage(target_library, analysis=analysis)
    report_json_path = output_path / "pattern_library_coverage.json"
    report_md_path = output_path / "pattern_library_coverage.md"
    report_json_path.write_text(to_json_text(dump_model(report)), encoding="utf-8")
    report_md_path.write_text(render_pattern_library_coverage_markdown(report), encoding="utf-8")
    return {
        "report": dump_model(report),
        "library": dump_model(target_library),
        "source_path": str(source_path) if source_path else None,
        "corpus_dir": str(corpus_dir) if corpus_dir else None,
        "artifact_json_path": str(report_json_path),
        "artifact_markdown_path": str(report_md_path),
    }


def analyze_corpus_to_pattern_library(
    *,
    corpus_dir: str | Path | None = None,
    output_dir: str | Path,
) -> dict:
    corpus_path = Path(corpus_dir) if corpus_dir else DEFAULT_LOCAL_CORPUS_DIR
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    analysis = analyze_local_corpus(corpus_path)
    generated_library = build_pattern_library_from_analysis(analysis)

    analysis_json_path = output_path / "local-corpus-analysis.json"
    analysis_md_path = output_path / "local-corpus-analysis.md"
    generated_path = output_path / "writing_patterns.generated.json"

    analysis_json_path.write_text(to_json_text(dump_model(analysis)), encoding="utf-8")
    analysis_md_path.write_text(render_corpus_analysis_markdown(analysis), encoding="utf-8")
    generated_path.write_text(to_json_text(dump_model(generated_library)), encoding="utf-8")

    return {
        "analysis": dump_model(analysis),
        "generated_library": dump_model(generated_library),
        "corpus_dir": str(corpus_path),
        "analysis_json_path": str(analysis_json_path),
        "analysis_markdown_path": str(analysis_md_path),
        "generated_path": str(generated_path),
    }


def build_reviewable_pattern_skill_from_corpus(
    *,
    corpus_dir: str | Path | None = None,
    output_dir: str | Path,
    skill_name: str = "construction-org-writing-patterns",
    include_source_excerpts: bool = False,
    max_source_chars: int = 250_000,
) -> dict:
    """Build the full reviewable writing-skill package from the local corpus.

    This is intentionally review-only: it analyzes local human-written
    construction-organization samples, builds a generated pattern library,
    audits coverage, and exports a skill package. It does not replace the
    active `writing_patterns.json`; applying the generated library remains a
    separate explicit user action.
    """

    corpus_path = Path(corpus_dir) if corpus_dir else DEFAULT_LOCAL_CORPUS_DIR
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    analysis = analyze_local_corpus(
        corpus_path,
        include_source_excerpts=include_source_excerpts,
        max_source_chars=max_source_chars,
    )
    generated_library = build_pattern_library_from_analysis(analysis)

    analysis_json_path = output_path / "local-corpus-analysis.json"
    analysis_md_path = output_path / "local-corpus-analysis.md"
    generated_path = output_path / "writing_patterns.generated.json"
    coverage_json_path = output_path / "pattern_library_coverage.json"
    coverage_md_path = output_path / "pattern_library_coverage.md"
    package_dir = output_path / skill_name

    analysis_json_path.write_text(to_json_text(dump_model(analysis)), encoding="utf-8")
    analysis_md_path.write_text(render_corpus_analysis_markdown(analysis), encoding="utf-8")
    generated_path.write_text(to_json_text(dump_model(generated_library)), encoding="utf-8")

    coverage_report = audit_pattern_library_coverage(generated_library, analysis=analysis)
    coverage_json_path.write_text(to_json_text(dump_model(coverage_report)), encoding="utf-8")
    coverage_md_path.write_text(render_pattern_library_coverage_markdown(coverage_report), encoding="utf-8")

    skill_package = export_pattern_skill_package(
        library=generated_library,
        output_dir=package_dir,
        skill_name=skill_name,
        coverage_report=coverage_report,
    )

    return {
        "corpus_dir": str(corpus_path),
        "output_dir": str(output_path),
        "analysis": dump_model(analysis),
        "generated_library": dump_model(generated_library),
        "coverage_report": dump_model(coverage_report),
        "skill_package": skill_package,
        "analysis_json_path": str(analysis_json_path),
        "analysis_markdown_path": str(analysis_md_path),
        "generated_path": str(generated_path),
        "coverage_json_path": str(coverage_json_path),
        "coverage_markdown_path": str(coverage_md_path),
        "skill_package_dir": skill_package["output_dir"],
        "skill_manifest_path": skill_package["package_paths"]["manifest"],
    }


def build_pattern_library_candidate_from_learning_report(
    *,
    learning_report: dict[str, Any],
    output_dir: str | Path,
    selected_suggestion_indexes: list[int] | None = None,
) -> dict:
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    active = load_writing_pattern_library()
    candidate = active.model_copy(deep=True)
    candidate.version = f"{active.version}+quality-learning"
    candidate.corpus_scope = (
        f"{active.corpus_scope}; quality iteration learning from "
        f"{learning_report.get('project_id') or 'external report'}"
    )

    changes: list[dict[str, Any]] = []
    selected_indexes = set(selected_suggestion_indexes) if selected_suggestion_indexes is not None else None
    for suggestion_index, suggestion in enumerate(learning_report.get("suggestions") or []):
        if selected_indexes is not None and suggestion_index not in selected_indexes:
            continue
        if not isinstance(suggestion, dict):
            continue
        pattern_key = str(suggestion.get("pattern_key") or "general")
        if pattern_key not in candidate.patterns:
            pattern_key = _best_existing_pattern_key(suggestion)
        pattern = candidate.patterns.get(pattern_key)
        if pattern is None:
            continue

        evidence = [str(item).strip() for item in suggestion.get("evidence") or [] if str(item).strip()]
        suggested_text = [str(item).strip() for item in suggestion.get("suggested_text") or [] if str(item).strip()]
        suggestion_type = str(suggestion.get("suggestion_type") or "")
        before = dump_model(pattern)

        if suggestion_type == "strengthen_required_source_facts":
            for term in _generalized_required_fact_terms(evidence):
                _append_unique(pattern.required_source_facts, term)
            _append_unique(
                pattern.revision_signals,
                "Mapped source facts are available but omitted from generated正文; regenerate with required source facts.",
            )
        elif suggestion_type == "add_outline_guidance":
            for heading in evidence:
                if _is_reusable_heading(heading):
                    _append_unique(pattern.corpus_common_headings, heading)
            _append_unique(
                pattern.revision_signals,
                "Human-reference headings are missing; propose source-supported outline or subsection repair before regeneration.",
            )
        elif suggestion_type == "add_revision_signal":
            for text in suggested_text or [str(suggestion.get("reason") or "")]:
                if text:
                    _append_unique(pattern.revision_signals, text)
        elif suggestion_type == "increase_detail_or_split":
            _append_unique(
                pattern.revision_signals,
                "Quality audit indicates insufficient detail or missing subsection split for this writing pattern.",
            )
            _append_unique(
                pattern.auto_writable_moves,
                "Increase detail budget or split dense chapters into source-derived subsections when evidence density is high.",
            )
        else:
            continue

        for item in evidence[:8]:
            _append_unique(pattern.corpus_basis, f"quality_iteration_evidence: {item}")
        after = dump_model(pattern)
        if before != after:
            changes.append(
                {
                    "suggestion_index": suggestion_index,
                    "pattern_key": pattern.key,
                    "suggestion_type": suggestion_type,
                    "reason": suggestion.get("reason"),
                    "evidence": evidence[:8],
                    "added_fields": _changed_pattern_fields(before, after),
                    "added_items": _added_pattern_items(before, after),
                }
            )

    generated_path = output_path / "writing_patterns.learning.generated.json"
    report_json_path = output_path / "quality_iteration_learning_report.json"
    report_md_path = output_path / "quality_iteration_learning_candidate.md"

    generated_path.write_text(to_json_text(dump_model(candidate)), encoding="utf-8")
    report_json_path.write_text(to_json_text(learning_report), encoding="utf-8")
    report_md_path.write_text(
        _render_learning_candidate_markdown(
            learning_report=learning_report,
            generated_path=generated_path,
            changes=changes,
        ),
        encoding="utf-8",
    )

    return {
        "learning_report": learning_report,
        "generated_library": dump_model(candidate),
        "changes": changes,
        "selected_suggestion_indexes": sorted(selected_indexes) if selected_indexes is not None else None,
        "source": "quality_iteration_learning",
        "generated_path": str(generated_path),
        "learning_report_path": str(report_json_path),
        "learning_candidate_markdown_path": str(report_md_path),
    }


def apply_generated_pattern_library(
    *,
    generated_path: str | Path | None = None,
    active_path: str | Path | None = None,
) -> dict:
    source = Path(generated_path) if generated_path else default_generated_pattern_library_path()
    target = Path(active_path) if active_path else active_pattern_library_path()
    if not source.exists():
        raise FileNotFoundError(f"Generated pattern library not found: {source}")
    library = WritingPatternLibrary.model_validate_json(source.read_text(encoding="utf-8"))
    coverage_report = audit_pattern_library_coverage(library)
    target.parent.mkdir(parents=True, exist_ok=True)
    backup_path = None
    if target.exists():
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        backup_path = target.with_name(f"{target.stem}.{timestamp}.bak{target.suffix}")
        backup_path.write_text(target.read_text(encoding="utf-8"), encoding="utf-8")
    target.write_text(to_json_text(dump_model(library)), encoding="utf-8")
    apply_log_path = target.with_name(f"{target.stem}.apply-log.json")
    applied_at = datetime.now().isoformat(timespec="seconds")
    apply_log = {
        "applied": True,
        "applied_at": applied_at,
        "active_path": str(target),
        "generated_path": str(source),
        "backup_path": str(backup_path) if backup_path else None,
        "library_version": library.version,
        "corpus_scope": library.corpus_scope,
        "pattern_count": len(library.patterns),
        "coverage_status": coverage_report.status,
        "coverage_issue_count": len(coverage_report.issues),
        "coverage_report": dump_model(coverage_report),
    }
    apply_log_path.write_text(to_json_text(apply_log), encoding="utf-8")
    apply_history_path = pattern_library_apply_history_path(target)
    history = read_pattern_library_apply_history(active_path=target)["history"]
    history.append(apply_log)
    apply_history_path.write_text(to_json_text(history), encoding="utf-8")
    load_writing_pattern_library.cache_clear()
    return {
        "applied": True,
        "applied_at": applied_at,
        "active_path": str(target),
        "generated_path": str(source),
        "backup_path": str(backup_path) if backup_path else None,
        "apply_log_path": str(apply_log_path),
        "apply_history_path": str(apply_history_path),
        "apply_history_count": len(history),
        "coverage_status": coverage_report.status,
        "coverage_issue_count": len(coverage_report.issues),
        "coverage_report": dump_model(coverage_report),
        "library": dump_model(library),
    }


def _best_existing_pattern_key(suggestion: dict[str, Any]) -> str:
    text = " ".join(
        [
            str(suggestion.get("reason") or ""),
            " ".join(str(item) for item in suggestion.get("evidence") or []),
            " ".join(str(item) for item in suggestion.get("suggested_text") or []),
        ]
    )
    from coalplan.application.writing_pattern_library import match_patterns_for_text

    matches = match_patterns_for_text(text, limit=1)
    return matches[0].pattern_key if matches else "craft"


def _generalized_required_fact_terms(evidence: list[str]) -> list[str]:
    terms: list[str] = []
    for item in evidence:
        text = item.lower()
        if re.search(r"\d", item):
            if any(token in text for token in ["mpa", "pressure", "压力", "流量", "配比", "参数"]):
                terms.append("控制参数")
            elif any(token in text for token in ["m3", "m²", "m2", "kg", "t", "工程量", "quantity"]):
                terms.append("工程量")
            else:
                terms.append("带单位的关键参数")
        if any(token in text for token in ["acceptance", "验收", "检查", "检测", "inspection"]):
            terms.append("检查验收要求")
        if any(token in text for token in ["risk", "危险", "安全", "hazard"]):
            terms.append("危险源与安全措施")
        if any(token in text for token in ["schedule", "工期", "进度", "节点"]):
            terms.append("工期节点")
        if any(token in text for token in ["material", "材料", "设备", "resource"]):
            terms.append("材料设备配置")
    return list(dict.fromkeys(terms or ["来源中已明确的关键事实"]))


def _is_reusable_heading(value: str) -> bool:
    text = value.strip()
    if not text or len(text) > 80:
        return False
    return not text.startswith(("http://", "https://"))


def _append_unique(items: list[str], value: str) -> None:
    text = value.strip()
    if text and text not in items:
        items.append(text)


def _changed_pattern_fields(before: dict, after: dict) -> list[str]:
    return [field for field in _pattern_list_fields() if before.get(field) != after.get(field)]


def _added_pattern_items(before: dict, after: dict) -> dict[str, list[str]]:
    output: dict[str, list[str]] = {}
    for field in _pattern_list_fields():
        before_items = [str(item) for item in before.get(field) or []]
        after_items = [str(item) for item in after.get(field) or []]
        added = [item for item in after_items if item not in before_items]
        if added:
            output[field] = added
    return output


def _pattern_list_fields() -> list[str]:
    return [
        "corpus_common_headings",
        "required_source_facts",
        "auto_writable_moves",
        "human_only_items",
        "revision_signals",
        "corpus_basis",
    ]


def _render_learning_candidate_markdown(
    *,
    learning_report: dict[str, Any],
    generated_path: Path,
    changes: list[dict[str, Any]],
) -> str:
    lines = [
        "# Pattern Library Learning Candidate",
        "",
        f"- project_id: `{learning_report.get('project_id')}`",
        f"- source_status: `{learning_report.get('status')}`",
        f"- generated_path: `{generated_path}`",
        f"- change_count: {len(changes)}",
        "",
        "This file is review-only. It does not change the active pattern library until `/pattern-library/apply-generated` is called with the generated path.",
        "",
        "## Changes",
        "",
    ]
    if not changes:
        lines.append("- No candidate change was produced.")
        return "\n".join(lines).strip() + "\n"
    for item in changes:
        lines.extend(
            [
                f"### {item.get('pattern_key')} / {item.get('suggestion_type')}",
                f"- suggestion_index: {item.get('suggestion_index')}",
                f"- reason: {item.get('reason')}",
                "- added_fields: " + ", ".join(item.get("added_fields") or []),
            ]
        )
        added_items = item.get("added_items") or {}
        if added_items:
            lines.append("- added_items:")
            for field, values in added_items.items():
                lines.append(f"  - {field}:")
                lines.extend(f"    - {value}" for value in values[:8])
        evidence = item.get("evidence") or []
        if evidence:
            lines.append("- evidence:")
            lines.extend(f"  - {entry}" for entry in evidence)
        lines.append("")
    return "\n".join(lines).strip() + "\n"
