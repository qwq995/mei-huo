from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from coalplan.application.quality_audit import (
    QualityAuditInput,
    audit_generation_quality,
    render_quality_audit_markdown,
)
from coalplan.application.quality_feedback import build_quality_feedback_plan, render_quality_feedback_plan
from coalplan.application.serialization import dump_model, to_json_text
from coalplan.application.trace_evidence_diagnostics import (
    diagnose_trace_evidence_absorption,
    render_trace_evidence_diagnostics_markdown,
)


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Audit generated construction-organization markdown against source and human references.")
    parser.add_argument("--input-root", type=Path, default=Path.home() / "Desktop" / "示例输入输出")
    parser.add_argument("--output-dir", type=Path, default=None)
    parser.add_argument("--projects", nargs="*", default=["project_3", "project_4"])
    parser.add_argument("--trace-dir", type=Path, default=None, help="Optional LLM trace directory used to diagnose omitted source facts.")
    args = parser.parse_args()

    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    output_dir = args.output_dir or Path.cwd() / f".coalplan-quality-audit-{timestamp}"
    output_dir.mkdir(parents=True, exist_ok=True)

    reports = []
    for project_key in args.projects:
        project_dir = args.input_root / project_key
        report = _audit_project(project_key, project_dir, output_dir, trace_dir=args.trace_dir)
        reports.append(report)

    summary = {
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "input_root": str(args.input_root.resolve()),
        "output_dir": str(output_dir.resolve()),
        "projects": reports,
    }
    (output_dir / "quality_audit_summary.json").write_text(to_json_text(summary), encoding="utf-8")
    (output_dir / "quality_audit_summary.md").write_text(_render_summary(summary), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


def _audit_project(project_key: str, project_dir: Path, output_dir: Path, *, trace_dir: Path | None = None) -> dict[str, Any]:
    generated_path = _find_generated_markdown(project_dir)
    source_path = project_dir / "投标文档（md版本）.md"
    human_path = project_dir / "human_org.txt"
    if generated_path is None:
        raise FileNotFoundError(f"Generated markdown not found under: {project_dir}")
    if not source_path.exists():
        raise FileNotFoundError(f"Source markdown not found: {source_path}")

    report = audit_generation_quality(
        QualityAuditInput(
            project_key=project_key,
            generated_markdown=generated_path.read_text(encoding="utf-8-sig"),
            source_markdown=source_path.read_text(encoding="utf-8-sig"),
            human_markdown=human_path.read_text(encoding="utf-8-sig") if human_path.exists() else "",
        )
    )
    report["paths"] = {
        "project_dir": str(project_dir),
        "generated": str(generated_path),
        "source": str(source_path),
        "human": str(human_path) if human_path.exists() else None,
    }
    report["feedback_plan_path"] = str(output_dir / f"{project_key}_quality_feedback_plan.json")
    trace_report = None
    if trace_dir is not None:
        trace_report = diagnose_trace_evidence_absorption(quality_report=report, trace_dir=trace_dir)
        trace_json_path = output_dir / f"{project_key}_trace_evidence_diagnostics.json"
        trace_md_path = output_dir / f"{project_key}_trace_evidence_diagnostics.md"
        trace_json_path.write_text(to_json_text(trace_report), encoding="utf-8")
        trace_md_path.write_text(render_trace_evidence_diagnostics_markdown(trace_report), encoding="utf-8")
        report["trace_diagnostics_path"] = str(trace_json_path)
        report["trace_diagnostics_markdown_path"] = str(trace_md_path)
    feedback = build_quality_feedback_plan(report, trace_diagnostics=trace_report)
    (output_dir / f"{project_key}_quality_audit.json").write_text(to_json_text(report), encoding="utf-8")
    (output_dir / f"{project_key}_quality_audit.md").write_text(render_quality_audit_markdown(report), encoding="utf-8")
    (output_dir / f"{project_key}_quality_feedback_plan.json").write_text(to_json_text(dump_model(feedback)), encoding="utf-8")
    (output_dir / f"{project_key}_quality_feedback_plan.md").write_text(render_quality_feedback_plan(feedback), encoding="utf-8")
    return report


def _find_generated_markdown(project_dir: Path) -> Path | None:
    preferred = project_dir / "生成文档（包含信息来源）.md"
    if preferred.exists():
        return preferred
    candidates = sorted(project_dir.glob("*生成*.md"))
    with_source = [path for path in candidates if "包含" in path.name and "不包含" not in path.name]
    if with_source:
        return with_source[0]
    return candidates[0] if candidates else None


def _render_summary(summary: dict[str, Any]) -> str:
    lines = [
        "# Generation Quality Audit Summary",
        "",
        f"- input_root: `{summary['input_root']}`",
        f"- output_dir: `{summary['output_dir']}`",
        "",
        "| project | generated words | human words | word ratio | heading coverage | source fact absorption | issues |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for report in summary["projects"]:
        lines.append(
            "| {project} | {generated} | {human} | {word_ratio} | {heading_ratio} | {fact_ratio} | {issues} |".format(
                project=report["project_key"],
                generated=report["word_counts"]["generated"],
                human=report["word_counts"]["human"] or "",
                word_ratio=report["word_counts"]["generated_vs_human_ratio"],
                heading_ratio=report["headings"]["human_heading_coverage_ratio"],
                fact_ratio=report["source_facts"]["absorption_ratio"],
                issues=f"{len(report['issues'])} / recs {len(report.get('recommendations', []))}",
            )
        )
    lines.append("")
    for report in summary["projects"]:
        lines.extend(
            [
                f"## {report['project_key']}",
                "",
                f"- report_json: `{report['project_key']}_quality_audit.json`",
                f"- report_md: `{report['project_key']}_quality_audit.md`",
                f"- feedback_plan: `{report['project_key']}_quality_feedback_plan.md`",
                "- issues:",
            ]
        )
        if report["issues"]:
            lines.extend(f"  - {item}" for item in report["issues"])
        else:
            lines.append("  - None.")
        lines.append("- recommendations:")
        if report.get("recommendations"):
            lines.extend(f"  - {item['action']}: {item['reason']}" for item in report["recommendations"])
        else:
            lines.append("  - None.")
        lines.append("")
    return "\n".join(lines).strip() + "\n"


if __name__ == "__main__":
    main()
