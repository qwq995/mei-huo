from __future__ import annotations

import argparse
import json
import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from coalplan.application.serialization import dump_model, to_json_text
from coalplan.domain.enums import TaskStatus
from coalplan.domain.templates import iter_template_nodes
from coalplan.main import build_pipeline
from coalplan.settings import Settings


@dataclass(frozen=True)
class DemoProject:
    key: str
    name: str
    template_id: str
    input_path: Path
    preferred_title_terms: tuple[str, ...]
    supplement_title: str
    supplement_content: str
    table_title: str
    table_content: str
    attachment_name: str
    attachment_description: str
    subsection_note: str


def main() -> None:
    parser = argparse.ArgumentParser(description="Run workspace tree flow against the two desktop demo projects.")
    parser.add_argument("--input-root", type=Path, default=Path.home() / "Desktop" / "示例输入输出")
    parser.add_argument("--output-root", type=Path, default=None)
    parser.add_argument("--provider", default=os.getenv("COALPLAN_LLM_PROVIDER", "deepseek"))
    parser.add_argument("--structured-provider", default=os.getenv("COALPLAN_STRUCTURED_LLM_PROVIDER", None))
    parser.add_argument("--run-real-generation", action="store_true", help="Use configured LLM for the representative chapter.")
    args = parser.parse_args()

    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    output_root = args.output_root or Path.cwd() / f".coalplan-real-run-tree-workspace-{timestamp}"
    output_root.mkdir(parents=True, exist_ok=True)

    settings = Settings(
        storage_dir=output_root / "storage",
        llm_provider=args.provider if args.run_real_generation else "source_driven",
        structured_llm_provider=args.structured_provider if args.run_real_generation else "source_driven",
        llm_trace_dir=output_root / "traces",
        deepseek_api_key=os.getenv("COALPLAN_DEEPSEEK_API_KEY", ""),
        deepseek_base_url=os.getenv("COALPLAN_DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
        deepseek_model=os.getenv("COALPLAN_DEEPSEEK_MODEL", "deepseek-v4-pro"),
        minimax_api_key=os.getenv("COALPLAN_MINIMAX_API_KEY", ""),
        minimax_base_url=os.getenv("COALPLAN_MINIMAX_BASE_URL", "https://api.minimaxi.com/v1"),
        minimax_model=os.getenv("COALPLAN_MINIMAX_MODEL", "MiniMax-M2.7"),
    )
    pipeline = build_pipeline(settings)

    projects = _demo_projects(args.input_root)
    results = []
    for demo in projects:
        results.append(_run_project_flow(pipeline, demo, output_root))

    summary = {
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "output_root": str(output_root.resolve()),
        "llm_provider": settings.llm_provider,
        "structured_llm_provider": settings.structured_llm_provider or settings.llm_provider,
        "projects": results,
    }
    (output_root / "workspace_tree_flow_summary.json").write_text(to_json_text(summary), encoding="utf-8")
    (output_root / "workspace_tree_flow_report.md").write_text(_render_report(summary), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


def _demo_projects(input_root: Path) -> list[DemoProject]:
    return [
        DemoProject(
            key="project_1",
            name="宁夏煤火工作台目录树验证",
            template_id="coal_fire",
            input_path=input_root / "project_1" / "投标文档（md版本）.md",
            preferred_title_terms=("灭火工程量", "工程概况", "火区位置"),
            supplement_title="现场人工补充要求",
            supplement_content="本章生成时必须提示现场复核火区边界、温度异常点、裂隙和塌陷区，未核验参数不得写成确定值。",
            table_title="人工补充表格：复核项",
            table_content="| 复核项 | 当前要求 | 写入方式 |\n| --- | --- | --- |\n| 火区边界 | 以最新复勘成果确认 | 缺失时保留人工补充占位 |\n| 灌浆参数 | 以专项试验或监理确认值为准 | 不得编造压力和流量 |",
            attachment_name="coal_fire_site_note.txt",
            attachment_description="现场图文附件说明：后续上传火区边界复勘照片和温度监测表，本轮仅将说明写入生成上下文。",
            subsection_note="【小节迭代补充】请在本小节中强调火区边界、工程量和现场复核数据需要人工确认。",
        ),
        DemoProject(
            key="project_2",
            name="拉哇水电工作台目录树验证",
            template_id="hydro_diversion_slope",
            input_path=input_root / "project_2" / "投标文档（md版本）.md",
            preferred_title_terms=("1.1 工程概况", "合同工程项目概述", "施工条件"),
            supplement_title="现场人工补充要求",
            supplement_content="本章生成时必须提示导流洞、泄洪系统、边坡支护相关参数需结合最新图纸、施工总布置和现场交面确认。",
            table_title="人工补充表格：图纸与界面",
            table_content="| 补充项 | 当前状态 | 写入要求 |\n| --- | --- | --- |\n| 最新施工图 | 待人工确认 | 保留图纸版本占位 |\n| 交面条件 | 待现场确认 | 保留与其他标段界面占位 |",
            attachment_name="hydro_site_note.txt",
            attachment_description="现场图文附件说明：后续上传导流洞进口、出口边坡及施工道路照片，本轮仅将说明写入生成上下文。",
            subsection_note="【小节迭代补充】请在本小节中强调图纸版本、施工界面和现场道路条件需要人工确认。",
        ),
    ]


def _run_project_flow(pipeline, demo: DemoProject, output_root: Path) -> dict[str, Any]:
    if not demo.input_path.exists():
        raise FileNotFoundError(f"Demo input not found: {demo.input_path}")
    markdown = demo.input_path.read_text(encoding="utf-8-sig")
    project = pipeline.create_project(demo.name, template_id=demo.template_id)
    project = pipeline.ingest_bid_markdown(project.id, file_name=demo.input_path.name, content=markdown)
    project = pipeline.prepare_directory(project.id)

    store = pipeline.workspace_store
    outline_nodes = store.list_outline_nodes(project.id)
    target = _choose_node(outline_nodes, demo.preferred_title_terms)
    node_id = target["node_id"]
    updated_node = store.update_outline_node(
        project.id,
        node_id,
        {
            "source_rules": [*target.get("source_rules", []), "用户补充：生成时必须结合本章持久化补充材料与附件说明。"],
            "manual_fill": [*target.get("manual_fill", []), "用户补充材料、表格、附件说明中标记为必须写入的事项。"],
        },
    )
    supplement = store.add_supplement(
        project.id,
        node_id,
        {
            "kind": "note",
            "title": demo.supplement_title,
            "content": demo.supplement_content,
            "must_include": True,
            "sort_order": 1,
        },
    )
    table = store.add_supplement(
        project.id,
        node_id,
        {
            "kind": "table",
            "title": demo.table_title,
            "content": demo.table_content,
            "must_include": True,
            "sort_order": 2,
        },
    )
    attachment = store.add_attachment(
        project.id,
        node_id,
        file_name=demo.attachment_name,
        content_type="text/plain",
        content=(demo.attachment_description + "\n").encode("utf-8"),
        description=demo.attachment_description,
    )

    draft = pipeline.generate_one(project.id, node_id)
    workspace = store.get_workspace(project.id, node_id)
    selected_version = next(item for item in workspace["versions"] if item["id"] == workspace["selected_version_id"])
    tree = selected_version["content_tree"]
    editable_node = _first_content_node(tree["nodes"])
    edited_markdown = _append_subsection_note(editable_node["markdown"], demo.subsection_note)
    subsection_version = store.update_version_content_node(
        project.id,
        node_id,
        selected_version["id"],
        editable_node["id"],
        edited_markdown,
        select=True,
    )
    proposal = store.propose_chapter_edit(
        project.id,
        node_id,
        "根据用户修改要求，强调人工确认项并保持已生成来源依据。",
        subsection_version["markdown"] + "\n\n> AI 修改建议预览：已强调人工确认项，待用户确认后保存为新版本。\n",
    )
    applied = store.apply_proposal(project.id, proposal["id"])
    after_workspace = store.get_workspace(project.id, node_id)
    selected_after = next(item for item in after_workspace["versions"] if item["id"] == after_workspace["selected_version_id"])

    merge_run = pipeline.merge_latest(project.id)
    content_tree_nodes = _count_content_nodes(selected_after["content_tree"]["nodes"])
    source_link_count = _count_source_links(selected_after["content_tree"]["nodes"])
    trace_count = len(list((output_root / "traces").glob("*.json")))
    context = store.render_chapter_context(project.id, node_id)
    context_path = output_root / f"{demo.key}_chapter_context.md"
    context_path.write_text(context, encoding="utf-8")
    version_path = output_root / f"{demo.key}_selected_version.md"
    version_path.write_text(selected_after["markdown"], encoding="utf-8")

    return {
        "key": demo.key,
        "project_id": project.id,
        "template_id": demo.template_id,
        "input_path": str(demo.input_path),
        "source_section_count": len(project.sections),
        "outline_node_count": len(outline_nodes),
        "target_node_id": node_id,
        "target_title": updated_node["title"],
        "draft_status": draft.validation_status.value if isinstance(draft.validation_status, TaskStatus) else str(draft.validation_status),
        "draft_path": draft.artifact_path,
        "supplement_ids": [supplement["id"], table["id"]],
        "attachment_id": attachment["id"],
        "attachment_artifact_path": attachment["artifact_path"],
        "initial_version_id": selected_version["id"],
        "initial_content_tree_node_count": _count_content_nodes(tree["nodes"]),
        "initial_source_link_count": _count_source_links(tree["nodes"]),
        "edited_content_node_id": editable_node["id"],
        "subsection_edit_version_id": subsection_version["id"],
        "proposal_id": proposal["id"],
        "proposal_apply_status": applied["status"],
        "selected_version_id": selected_after["id"],
        "selected_version_source_type": selected_after["source_type"],
        "selected_content_tree_node_count": content_tree_nodes,
        "selected_source_link_count": source_link_count,
        "final_artifact_path": merge_run.final_artifact_path,
        "merge_status": merge_run.status.value,
        "merge_logs": merge_run.logs[-3:],
        "trace_count_total": trace_count,
        "context_path": str(context_path),
        "selected_version_path": str(version_path),
        "content_tree_path": selected_after.get("content_tree_path"),
        "checks": {
            "sections_persisted": len(project.sections) > 0,
            "outline_nodes_persisted": len(outline_nodes) > 0,
            "supplements_persisted": len(after_workspace["supplements"]) >= 2,
            "attachments_persisted": len(after_workspace["attachments"]) >= 1,
            "versions_created": len(after_workspace["versions"]) >= 3,
            "content_tree_created": content_tree_nodes > 0,
            "source_links_preserved_after_iteration": source_link_count > 0,
            "iterated_version_selected": selected_after["source_type"] == "ai_edit",
            "single_chapter_merge_skip_recorded": (not merge_run.final_artifact_path) and any("Merge skipped" in log for log in merge_run.logs),
            "context_contains_supplement": demo.supplement_title in context and demo.attachment_name in context,
        },
    }


def _choose_node(nodes: list[dict], terms: tuple[str, ...]) -> dict:
    enabled_nodes = [node for node in nodes if node.get("enabled")]
    for term in terms:
        for node in enabled_nodes:
            if term in node.get("title", ""):
                return node
    return enabled_nodes[0]


def _first_content_node(nodes: list[dict]) -> dict:
    if not nodes:
        raise ValueError("content_tree has no nodes")
    node = nodes[0]
    while node.get("children"):
        node = node["children"][0]
    return node


def _append_subsection_note(markdown: str, note: str) -> str:
    text = markdown.rstrip()
    if note in text:
        return text + "\n"
    return f"{text}\n\n{note}\n"


def _count_content_nodes(nodes: list[dict]) -> int:
    return sum(1 + _count_content_nodes(node.get("children", [])) for node in nodes)


def _count_source_links(nodes: list[dict]) -> int:
    return sum(len(node.get("source_links", [])) + _count_source_links(node.get("children", [])) for node in nodes)


def _render_report(summary: dict[str, Any]) -> str:
    lines = [
        "# Workspace Tree Flow Report",
        "",
        f"- output_root: `{summary['output_root']}`",
        f"- llm_provider: `{summary['llm_provider']}`",
        f"- structured_llm_provider: `{summary['structured_llm_provider']}`",
        "",
    ]
    for project in summary["projects"]:
        lines.extend(
            [
                f"## {project['key']} - {project['target_title']}",
                "",
                f"- project_id: `{project['project_id']}`",
                f"- template_id: `{project['template_id']}`",
                f"- source sections: {project['source_section_count']}",
                f"- outline nodes: {project['outline_node_count']}",
                f"- draft status: `{project['draft_status']}`",
                f"- versions created: {project['checks']['versions_created']}",
                f"- selected version source type: `{project['selected_version_source_type']}`",
                f"- content tree nodes: {project['selected_content_tree_node_count']}",
                f"- content tree source links: {project['selected_source_link_count']}",
                f"- merge status: `{project['merge_status']}`",
                f"- final artifact: `{project['final_artifact_path']}`",
                f"- selected version markdown: `{project['selected_version_path']}`",
                f"- context snapshot: `{project['context_path']}`",
                "",
                "Checks:",
            ]
        )
        for key, value in project["checks"].items():
            lines.append(f"- {key}: {'PASS' if value else 'FAIL'}")
        lines.append("")
    return "\n".join(lines).strip() + "\n"


if __name__ == "__main__":
    main()
