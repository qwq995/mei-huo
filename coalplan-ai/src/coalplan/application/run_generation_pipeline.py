from __future__ import annotations

from coalplan.application.generate_chapter import generate_chapter
from coalplan.application.generate_project_profile import generate_project_profile
from coalplan.application.ingest_bid_markdown import ingest_bid_markdown
from coalplan.application.load_template_tree import load_template_tree
from coalplan.application.map_chapter_sources import map_chapter_sources
from coalplan.application.map_sources_to_template import build_chapter_tasks
from coalplan.application.merge_chapters import merge_chapters
from coalplan.application.persist_source_index import persist_source_index
from coalplan.application.plan_template_outline import apply_outline_to_template_tree, plan_template_outline
from coalplan.application.serialization import dump_model, to_json_text
from coalplan.domain.enums import RunStatus
from coalplan.domain.generation import ChapterDraft, ChapterTask, GenerationRun, Project
from coalplan.domain.templates import TemplateNode, iter_template_nodes
from coalplan.ports.llm import LLMClient, StructuredLLMClient
from coalplan.ports.markdown_parser import MarkdownParser
from coalplan.ports.repository import ArtifactRepository, ProjectRepository
from coalplan.ports.retriever import SourceRetriever
from coalplan.ports.template_loader import TemplateLoader


class GenerationPipeline:
    def __init__(
        self,
        *,
        projects: ProjectRepository,
        artifacts: ArtifactRepository,
        parser: MarkdownParser,
        templates: TemplateLoader,
        retriever: SourceRetriever,
        llm: LLMClient,
        structured_llm: StructuredLLMClient | None = None,
    ) -> None:
        self.projects = projects
        self.artifacts = artifacts
        self.parser = parser
        self.templates = templates
        self.retriever = retriever
        self.llm = llm
        self.structured_llm = structured_llm
        self._drafts: dict[str, list[ChapterDraft]] = {}

    def create_project(self, name: str, template_id: str = "coal_fire") -> Project:
        project = Project(name=name, template_id=template_id)
        project = load_template_tree(project, template_id=template_id, loader=self.templates)
        return self.projects.save(project)

    def ingest_bid_markdown(self, project_id: str, *, file_name: str, content: str) -> Project:
        project = self.projects.get(project_id)
        project = ingest_bid_markdown(project, file_name=file_name, content=content, parser=self.parser, artifacts=self.artifacts)
        return self.projects.save(project)

    def set_template(self, project_id: str, template_id: str) -> Project:
        project = self.projects.get(project_id)
        if project.runs:
            raise ValueError("Template cannot be changed after generation runs have been created.")
        project.template_id = template_id
        project.template_tree = None
        project.outline_plan = None
        project = load_template_tree(project, template_id=template_id, loader=self.templates)
        return self.projects.save(project)

    def prepare_directory(self, project_id: str) -> Project:
        project = self.projects.get(project_id)
        project = self._ensure_generation_context(project)
        if not project.runs:
            run = GenerationRun(project_name=project.name, template_id=project.template_id)
            if project.template_tree is None:
                raise ValueError("Project template tree is not loaded.")
            run.chapter_tasks = build_chapter_tasks(project.template_tree, project.sections, self.retriever)
            run.logs.append(f"Prepared {len(run.chapter_tasks)} chapter task(s).")
            project.runs.append(run)
            project = self.projects.save(project)
        return project

    def prepare_run(self, project_id: str) -> GenerationRun:
        project = self.projects.get(project_id)
        project = self._ensure_generation_context(project)
        if project.template_tree is None:
            raise ValueError("Project template tree is not loaded.")
        run = GenerationRun(project_name=project.name, template_id=project.template_id)
        run.chapter_tasks = build_chapter_tasks(project.template_tree, project.sections, self.retriever)
        run.logs.append(f"Prepared {len(run.chapter_tasks)} chapter task(s).")
        run.logs.append("Prepared source toc, project profile, and template outline plan.")
        project.runs.append(run)
        self.projects.save(project)
        return run

    def generate_all(self, project_id: str) -> GenerationRun:
        project = self.projects.get(project_id)
        run = project.runs[-1] if project.runs else self.prepare_run(project_id)
        project = self.projects.get(project_id)
        project = self._ensure_generation_context(project)
        run = project.runs[-1] if project.runs else run
        if project.template_tree is None or project.project_profile is None or project.source_toc is None:
            raise ValueError("Project generation context is incomplete.")
        nodes_by_id = {node.id: node for node in iter_template_nodes(project.template_tree.nodes)}
        run.status = RunStatus.running
        drafts: list[ChapterDraft] = []
        for task in run.chapter_tasks:
            node = nodes_by_id[task.node_id]
            mapping, selected_sections, source_matches = map_chapter_sources(
                project_id=project.id,
                profile=project.project_profile,
                toc_items=project.source_toc.items,
                sections=project.sections,
                node=node,
                llm=self._structured_llm(),
                artifacts=self.artifacts,
            )
            task.source_mapping = mapping
            task.source_matches = source_matches
            draft = generate_chapter(
                project_id=project.id,
                node=node,
                task=task,
                llm=self.llm,
                artifacts=self.artifacts,
                project_profile=project.project_profile,
                selected_source_sections=selected_sections,
            )
            drafts.append(draft)
            run.logs.append(f"{task.status.value}: {task.title}")
        self._drafts[run.id] = drafts
        run.status = RunStatus.completed if all(task.status.value == "passed" for task in run.chapter_tasks) else RunStatus.partial_failed
        self._persist_validation(project.id, run)
        self.projects.save(project)
        return run

    def generate_one(self, project_id: str, node_id: str) -> ChapterDraft:
        project = self.projects.get(project_id)
        run = project.runs[-1] if project.runs else self.prepare_run(project_id)
        project = self.projects.get(project_id)
        project = self._ensure_generation_context(project)
        run = project.runs[-1] if project.runs else run
        if project.template_tree is None or project.project_profile is None or project.source_toc is None:
            raise ValueError("Project generation context is incomplete.")
        node = _find_node(project.template_tree.nodes, node_id)
        if node is None:
            raise KeyError(f"Unknown node_id: {node_id}")
        task = next((item for item in run.chapter_tasks if item.node_id == node_id), None)
        if task is None:
            task = ChapterTask(node_id=node.id, title=node.title, source_matches=self.retriever.retrieve(node, project.sections, limit=4))
            run.chapter_tasks.append(task)
        mapping, selected_sections, source_matches = map_chapter_sources(
            project_id=project.id,
            profile=project.project_profile,
            toc_items=project.source_toc.items,
            sections=project.sections,
            node=node,
            llm=self._structured_llm(),
            artifacts=self.artifacts,
        )
        task.source_mapping = mapping
        task.source_matches = source_matches
        draft = generate_chapter(
            project_id=project.id,
            node=node,
            task=task,
            llm=self.llm,
            artifacts=self.artifacts,
            project_profile=project.project_profile,
            selected_source_sections=selected_sections,
        )
        self._drafts.setdefault(run.id, []).append(draft)
        self._persist_validation(project.id, run)
        self.projects.save(project)
        return draft

    def merge_latest(self, project_id: str) -> GenerationRun:
        project = self.projects.get(project_id)
        if not project.runs:
            raise KeyError("Project has no generation run.")
        if project.template_tree is None:
            raise ValueError("Project template tree is not loaded.")
        run = project.runs[-1]
        drafts = self._drafts.get(run.id)
        if drafts is None:
            drafts = _load_drafts_from_tasks(project.id, run, self.artifacts)
        run = merge_chapters(
            project_id=project.id,
            run=run,
            drafts=drafts,
            template_tree=project.template_tree,
            title=f"{project.name}施工组织设计",
            artifacts=self.artifacts,
        )
        self.projects.save(project)
        return run

    def _ensure_generation_context(self, project: Project) -> Project:
        if project.template_tree is None:
            project = load_template_tree(project, template_id=project.template_id, loader=self.templates)
        if not project.sections:
            raise ValueError("No bid markdown sections are available. Upload and normalize a bid markdown file before generation.")
        if project.source_toc is None:
            project.source_toc = persist_source_index(project.id, project.sections, self.artifacts)
        if project.project_profile is None:
            project.project_profile = generate_project_profile(
                project_id=project.id,
                toc_items=project.source_toc.items,
                sections=project.sections,
                llm=self._structured_llm(),
                artifacts=self.artifacts,
            )
        if project.outline_plan is None:
            project.outline_plan = plan_template_outline(
                project_id=project.id,
                profile=project.project_profile,
                toc_items=project.source_toc.items,
                template_tree=project.template_tree,
                llm=self._structured_llm(),
                artifacts=self.artifacts,
            )
        project.template_tree = apply_outline_to_template_tree(project.template_tree, project.outline_plan)
        return self.projects.save(project)

    def _structured_llm(self) -> StructuredLLMClient:
        if self.structured_llm is not None:
            return self.structured_llm
        if not hasattr(self.llm, "complete_json"):
            raise TypeError("Configured LLM client must implement complete_json for structured generation stages.")
        return self.llm  # type: ignore[return-value]

    def _persist_validation(self, project_id: str, run: GenerationRun) -> None:
        self.artifacts.write_text(project_id, f"runs/{run.id}/validation.json", to_json_text(_validation_payload(run)))


def _find_node(nodes: list[TemplateNode], node_id: str) -> TemplateNode | None:
    for node in nodes:
        if node.id == node_id:
            return node
        found = _find_node(node.children, node_id)
        if found:
            return found
    return None


def _load_drafts_from_tasks(project_id: str, run: GenerationRun, artifacts: ArtifactRepository) -> list[ChapterDraft]:
    drafts: list[ChapterDraft] = []
    for task in run.chapter_tasks:
        path = f"{getattr(artifacts, 'root')}/{project_id}/chapters/{task.node_id}.md"
        try:
            markdown = artifacts.read_text(path)
        except Exception:
            continue
        drafts.append(
            ChapterDraft(
                node_id=task.node_id,
                title=task.title,
                markdown=markdown,
                source_section_ids=[match.section_id for match in task.source_matches],
                validation_status=task.status,
                artifact_path=path,
            )
        )
    return drafts


def _validation_payload(run: GenerationRun) -> dict:
    return {
        "run_id": run.id,
        "status": run.status.value,
        "tasks": [
            {
                "node_id": task.node_id,
                "title": task.title,
                "status": task.status.value,
                "source_section_ids": [match.section_id for match in task.source_matches],
                "mapping": dump_model(task.source_mapping) if task.source_mapping else None,
                "error_message": task.error_message,
            }
            for task in run.chapter_tasks
        ],
    }
