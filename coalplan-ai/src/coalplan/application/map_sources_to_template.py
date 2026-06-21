from __future__ import annotations

from coalplan.domain.generation import ChapterTask
from coalplan.domain.templates import TemplateTree, iter_template_nodes
from coalplan.domain.documents import MarkdownSection
from coalplan.ports.retriever import SourceRetriever


def build_chapter_tasks(template: TemplateTree, sections: list[MarkdownSection], retriever: SourceRetriever) -> list[ChapterTask]:
    tasks: list[ChapterTask] = []
    for node in iter_template_nodes(template.nodes):
        if not node.has_generation_contract:
            continue
        matches = retriever.retrieve(node, sections, limit=4)
        tasks.append(ChapterTask(node_id=node.id, title=node.title, target_word_count=node.target_word_count, source_matches=matches))
    return tasks
