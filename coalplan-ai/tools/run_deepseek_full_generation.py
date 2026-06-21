from __future__ import annotations

import argparse
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any

from coalplan.application.serialization import to_json_text
from coalplan.application.word_count_targets import count_words
from coalplan.domain.enums import TaskStatus
from coalplan.main import build_pipeline
from coalplan.settings import Settings


def main() -> None:
    parser = argparse.ArgumentParser(description="Run full DeepSeek generation for the two desktop demo projects.")
    parser.add_argument("--input-root", type=Path, default=Path.home() / "Desktop" / "示例输入输出")
    parser.add_argument("--output-root", type=Path, default=None)
    parser.add_argument("--max-retries", type=int, default=1)
    args = parser.parse_args()

    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    output_root = args.output_root or Path.cwd() / f".coalplan-deepseek-full-wordcount-{timestamp}"
    output_root.mkdir(parents=True, exist_ok=True)

    settings = Settings(
        storage_dir=output_root / "storage",
        llm_provider="deepseek",
        structured_llm_provider="deepseek",
        llm_trace_dir=output_root / "traces",
        deepseek_api_key=os.getenv("COALPLAN_DEEPSEEK_API_KEY", ""),
        deepseek_base_url=os.getenv("COALPLAN_DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
        deepseek_model=os.getenv("COALPLAN_DEEPSEEK_MODEL", "deepseek-v4-pro"),
    )
    if not settings.deepseek_api_key:
        raise RuntimeError("COALPLAN_DEEPSEEK_API_KEY is required.")
    pipeline = build_pipeline(settings)

    demos = [
        {
            "key": "project_1",
            "name": "宁夏煤火全量字数控制生成",
            "template_id": "coal_fire",
            "input_name": "投标文档（md版本）.md",
        },
        {
            "key": "project_2",
            "name": "拉哇水电全量字数控制生成",
            "template_id": "hydro_diversion_slope",
            "input_name": "投标文档（md版本）.md",
        },
    ]

    results = []
    for demo in demos:
        results.append(_run_one(pipeline, input_root=args.input_root, output_root=output_root, demo=demo, max_retries=args.max_retries))

    summary = {
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "output_root": str(output_root.resolve()),
        "model": settings.deepseek_model,
        "projects": results,
    }
    (output_root / "deepseek_full_generation_summary.json").write_text(to_json_text(summary), encoding="utf-8")
    (output_root / "deepseek_full_generation_report.md").write_text(_render_report(summary), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


def _run_one(pipeline, *, input_root: Path, output_root: Path, demo: dict[str, str], max_retries: int) -> dict[str, Any]:
    project_dir = input_root / demo["key"]
    input_path = project_dir / demo["input_name"]
    reference_path = _find_reference_markdown(project_dir)
    if not input_path.exists():
        raise FileNotFoundError(f"Input markdown not found: {input_path}")
    if reference_path is None:
        raise FileNotFoundError(f"Reference generated markdown not found under: {project_dir}")

    project = pipeline.create_project(demo["name"], template_id=demo["template_id"])
    project = pipeline.ingest_bid_markdown(project.id, file_name=input_path.name, content=input_path.read_text(encoding="utf-8-sig"))
    pipeline.prepare_directory(project.id)
    word_count_plan = pipeline.estimate_outline_word_counts(project.id, reference_path.read_text(encoding="utf-8-sig"))

    run = pipeline.generate_all(project.id)
    retries = 0
    while retries < max_retries:
        project_state = pipeline.projects.get(project.id)
        failed_tasks = [task for task in project_state.runs[-1].chapter_tasks if task.status != TaskStatus.passed]
        if not failed_tasks:
            break
        retries += 1
        for task in failed_tasks:
            try:
                pipeline.generate_one(project.id, task.node_id)
            except Exception:
                pass
        run = pipeline.projects.get(project.id).runs[-1]

    merge_run = pipeline.merge_latest(project.id)
    workspace_store = pipeline.workspace_store
    selected_versions = []
    for node in workspace_store.list_outline_nodes(project.id):
        if not node.get("selected_version_id"):
            continue
        version = workspace_store.get_version(project.id, node["node_id"], node["selected_version_id"])
        selected_versions.append(
            {
                "node_id": node["node_id"],
                "title": node["title"],
                "target_word_count": node.get("target_word_count"),
                "actual_word_count": count_words(version.get("markdown", "")),
                "version_id": version["id"],
                "source_type": version["source_type"],
                "content_tree_nodes": _count_content_nodes(version.get("content_tree", {}).get("nodes", [])),
                "source_links": _count_source_links(version.get("content_tree", {}).get("nodes", [])),
            }
        )

    final_text = ""
    if merge_run.final_artifact_path:
        final_text = Path(merge_run.final_artifact_path).read_text(encoding="utf-8-sig")
        (output_root / f"{demo['key']}_final.md").write_text(final_text, encoding="utf-8")

    project_state = pipeline.projects.get(project.id)
    tasks = project_state.runs[-1].chapter_tasks if project_state.runs else []
    trace_count = len(list((output_root / "traces").glob("*.json")))
    return {
        "key": demo["key"],
        "project_id": project.id,
        "template_id": demo["template_id"],
        "input_path": str(input_path),
        "reference_path": str(reference_path),
        "source_section_count": len(project_state.sections),
        "outline_node_count": len(workspace_store.list_outline_nodes(project.id)),
        "word_count_estimate_count": len(word_count_plan["estimates"]),
        "target_word_count_total": sum(item["target_word_count"] or 0 for item in selected_versions),
        "actual_word_count_total": count_words(final_text) if final_text else sum(item["actual_word_count"] for item in selected_versions),
        "task_count": len(tasks),
        "passed_count": sum(1 for task in tasks if task.status == TaskStatus.passed),
        "failed": [
            {"node_id": task.node_id, "title": task.title, "status": task.status.value, "error_message": task.error_message}
            for task in tasks
            if task.status != TaskStatus.passed
        ],
        "run_status": merge_run.status.value,
        "final_artifact_path": merge_run.final_artifact_path,
        "local_final_copy": str(output_root / f"{demo['key']}_final.md") if final_text else None,
        "selected_versions": selected_versions,
        "trace_count_total": trace_count,
        "artifacts_root": str((pipeline.artifacts.root / project.id).resolve()),
    }


def _find_reference_markdown(project_dir: Path) -> Path | None:
    candidates = sorted(project_dir.glob("*.md"))
    for path in candidates:
        name = path.name
        if "生成文档" in name and "包含信息来源" in name and "不包含信息来源" not in name:
            return path
    for path in candidates:
        if "生成文档" in path.name:
            return path
    return None


def _count_content_nodes(nodes: list[dict]) -> int:
    return sum(1 + _count_content_nodes(node.get("children", [])) for node in nodes)


def _count_source_links(nodes: list[dict]) -> int:
    return sum(len(node.get("source_links", [])) + _count_source_links(node.get("children", [])) for node in nodes)


def _render_report(summary: dict[str, Any]) -> str:
    lines = [
        "# DeepSeek Full Generation Report",
        "",
        f"- output_root: `{summary['output_root']}`",
        f"- model: `{summary['model']}`",
        "",
    ]
    for project in summary["projects"]:
        lines.extend(
            [
                f"## {project['key']}",
                "",
                f"- project_id: `{project['project_id']}`",
                f"- template_id: `{project['template_id']}`",
                f"- source sections: {project['source_section_count']}",
                f"- outline nodes: {project['outline_node_count']}",
                f"- word count estimates: {project['word_count_estimate_count']}",
                f"- tasks: {project['passed_count']}/{project['task_count']} passed",
                f"- run status: `{project['run_status']}`",
                f"- target words total: {project['target_word_count_total']}",
                f"- actual words total: {project['actual_word_count_total']}",
                f"- final artifact: `{project['final_artifact_path']}`",
                f"- local final copy: `{project['local_final_copy']}`",
                f"- traces total so far: {project['trace_count_total']}",
                "",
                "| 章节 | 目标字数 | 实际字数 | 小节数 | 来源链接 |",
                "| --- | ---: | ---: | ---: | ---: |",
            ]
        )
        for version in project["selected_versions"]:
            lines.append(
                f"| {version['title']} | {version['target_word_count'] or ''} | {version['actual_word_count']} | {version['content_tree_nodes']} | {version['source_links']} |"
            )
        if project["failed"]:
            lines.extend(["", "Failed tasks:"])
            lines.extend(f"- {item['title']}: {item['status']} {item['error_message'] or ''}" for item in project["failed"])
        lines.append("")
    return "\n".join(lines).strip() + "\n"


if __name__ == "__main__":
    main()
