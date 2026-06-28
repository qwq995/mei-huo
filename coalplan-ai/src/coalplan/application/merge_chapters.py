from __future__ import annotations

from coalplan.domain.generation import ChapterDraft, GenerationRun
from coalplan.domain.enums import RunStatus, TaskStatus
from coalplan.domain.templates import TemplateTree
from coalplan.infrastructure.markdown.renderer import merge_template_tree_markdowns
from coalplan.ports.repository import ArtifactRepository


def merge_chapters(
    *,
    project_id: str,
    run: GenerationRun,
    drafts: list[ChapterDraft],
    template_tree: TemplateTree,
    title: str,
    artifacts: ArtifactRepository,
) -> GenerationRun:
    mergeable_draft_node_ids = {draft.node_id for draft in drafts if draft.validation_status != TaskStatus.failed}
    for task in run.chapter_tasks:
        if task.node_id in mergeable_draft_node_ids:
            task.status = TaskStatus.passed
    failed = [task for task in run.chapter_tasks if task.status != TaskStatus.passed]
    if failed:
        run.status = RunStatus.partial_failed
        run.logs.append(f"Merge skipped: {len(failed)} chapter task(s) have no selected or mergeable version.")
        return run
    final_markdown = merge_template_tree_markdowns(title, template_tree.nodes, [draft for draft in drafts if draft.node_id in mergeable_draft_node_ids])
    run.final_artifact_path = artifacts.write_text(project_id, "artifacts/final.md", final_markdown)
    run.status = RunStatus.completed
    run.logs.append("Merged selected mergeable chapters into artifacts/final.md; quality findings remain advisory for human review.")
    return run
