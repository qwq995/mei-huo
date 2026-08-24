"""Export a clearly marked partial manuscript from selected chapter versions."""

from __future__ import annotations

import argparse
from pathlib import Path

from coalplan.application.run_generation_pipeline import iter_template_nodes
from coalplan.domain.enums import TaskStatus
from coalplan.domain.generation import ChapterDraft
from coalplan.infrastructure.markdown.renderer import merge_template_tree_markdowns
from coalplan.main import build_pipeline
from coalplan.settings import Settings


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    args = parser.parse_args()
    root = args.root.resolve()
    pipeline = build_pipeline(Settings(
        storage_dir=root / "storage",
        llm_provider="fake",
        structured_llm_provider="fake",
        llm_trace_dir=root / "traces",
    ))
    project = pipeline.projects.list()[0]
    project.template_tree = pipeline._effective_template_tree(project)
    drafts = pipeline._selected_version_drafts(project)
    existing = {draft.node_id for draft in drafts}
    missing = []
    for node in iter_template_nodes(project.template_tree.nodes):
        if node.id in existing:
            continue
        if node.children:
            continue
        missing.append(node)
        drafts.append(ChapterDraft(
            node_id=node.id,
            title=node.title,
            markdown=(
                "## 生成正文\n\n"
                "【待生成：本章节尚未完成模型生成，当前阶段性合稿不将其视为已完成内容。】\n"
            ),
            validation_status=TaskStatus.pending,
        ))
    title = f"{project.name}施工组织设计（阶段性合稿）"
    content = merge_template_tree_markdowns(title, project.template_tree.nodes, drafts)
    output = root / "current_partial_manuscript.md"
    output.write_text(content, encoding="utf-8")
    print(f"project_id={project.id}")
    print(f"generated_chapters={len(existing)}")
    print(f"pending_chapters={len(missing)}")
    print(f"output={output}")


if __name__ == "__main__":
    main()
