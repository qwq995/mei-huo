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
from coalplan.domain.enums import RunStatus, TaskStatus
from coalplan.domain.generation import ChapterDraft, ChapterTask, GenerationRun, Project
from coalplan.domain.templates import TemplateNode, TemplateTree, iter_template_nodes
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
        workspace_store=None,
    ) -> None:
        self.projects = projects
        self.artifacts = artifacts
        self.parser = parser
        self.templates = templates
        self.retriever = retriever
        self.llm = llm
        self.structured_llm = structured_llm
        self.workspace_store = workspace_store
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
        project = self._ensure_base_context(project)
        project = self.projects.save(project)
        project.template_tree = self._effective_template_tree(project)
        if not project.runs:
            run = GenerationRun(project_name=project.name, template_id=project.template_id)
            if project.template_tree is None:
                raise ValueError("Project template tree is not loaded.")
            run.chapter_tasks = build_chapter_tasks(project.template_tree, project.sections, self.retriever)
            run.logs.append(f"Prepared {len(run.chapter_tasks)} chapter task(s).")
            project.runs.append(run)
            project = self.projects.save(project)
        return project

    def propose_ai_outline(self, project_id: str, suggestion: str = "") -> dict:
        if self.workspace_store is None:
            raise ValueError("Workspace store is not configured.")
        project = self.projects.get(project_id)
        project = self._ensure_base_context(project)
        if project.template_tree is None or project.project_profile is None or project.source_toc is None:
            raise ValueError("Project directory context is incomplete.")
        outline = plan_template_outline(
            project_id=project.id,
            profile=project.project_profile,
            toc_items=project.source_toc.items,
            template_tree=project.template_tree,
            llm=self._structured_llm(),
            artifacts=self.artifacts,
        )
        preview_nodes = [
            {
                "node_id": node.node_id,
                "title": node.title,
                "level": node.level,
                "enabled": node.enabled,
                "source_rules": node.main_sources,
                "auto_fill": node.auto_fill,
                "manual_fill": node.manual_fill,
                "special_notes": node.special_notes,
            }
            for node in outline.nodes
        ]
        text = suggestion or "AI 基于项目概况、投标目录和模板四模块生成目录优化建议。"
        return self.workspace_store.propose_outline_change(project.id, text, preview_nodes)

    def prepare_run(self, project_id: str) -> GenerationRun:
        project = self.projects.get(project_id)
        project = self._ensure_generation_context(project)
        project.template_tree = self._effective_template_tree(project)
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
        project.template_tree = self._effective_template_tree(project)
        run = project.runs[-1] if project.runs else run
        if project.template_tree is None or project.project_profile is None or project.source_toc is None:
            raise ValueError("Project generation context is incomplete.")
        nodes_by_id = {node.id: node for node in iter_template_nodes(project.template_tree.nodes)}
        run.status = RunStatus.running
        drafts: list[ChapterDraft] = []
        for task in run.chapter_tasks:
            try:
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
                    user_context=self._chapter_user_context(project.id, node.id),
                )
                self._record_chapter_version(project.id, node.id, draft, "ai_generate")
                drafts.append(draft)
            except Exception as exc:
                task.status = TaskStatus.failed
                task.error_message = str(exc)
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
        project.template_tree = self._effective_template_tree(project)
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
            user_context=self._chapter_user_context(project.id, node.id),
        )
        self._record_chapter_version(project.id, node.id, draft, "ai_generate")
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
        project.template_tree = self._effective_template_tree(project)
        run = project.runs[-1]
        drafts = self._selected_version_drafts(project)
        if not drafts:
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
        project = self._ensure_base_context(project)
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

    def _ensure_base_context(self, project: Project) -> Project:
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
        return self.projects.save(project)

    def _effective_template_tree(self, project: Project) -> TemplateTree | None:
        if self.workspace_store is None or project.template_tree is None:
            return project.template_tree
        try:
            nodes = self.workspace_store.outline_tree(project.id)
            if nodes:
                return TemplateTree(id=project.template_tree.id, name=project.template_tree.name, nodes=nodes)
        except Exception:
            return project.template_tree
        return project.template_tree

    def _structured_llm(self) -> StructuredLLMClient:
        if self.structured_llm is not None:
            return self.structured_llm
        if not hasattr(self.llm, "complete_json"):
            raise TypeError("Configured LLM client must implement complete_json for structured generation stages.")
        return self.llm  # type: ignore[return-value]

    def _chapter_user_context(self, project_id: str, node_id: str) -> str:
        if self.workspace_store is None:
            return ""
        try:
            return self.workspace_store.render_chapter_context(project_id, node_id)
        except Exception:
            return ""

    def _record_chapter_version(self, project_id: str, node_id: str, draft: ChapterDraft, source_type: str) -> None:
        if self.workspace_store is None or draft.validation_status.value != "passed":
            return
        try:
            workspace = self.workspace_store.get_workspace(project_id, node_id)
            supplement_ids = [item["id"] for item in workspace.get("supplements", [])]
            self.workspace_store.create_chapter_version(
                project_id,
                node_id,
                title=draft.title,
                markdown=draft.markdown,
                artifact_path=draft.artifact_path,
                source_type=source_type,
                source_section_ids=draft.source_section_ids,
                supplement_ids=supplement_ids,
                created_by="ai",
                select=True,
            )
        except Exception as exc:
            # Versioning should not make the generation endpoint fail after a valid draft was produced.
            pass

    def _selected_version_drafts(self, project: Project) -> list[ChapterDraft]:
        if self.workspace_store is None:
            return []
        drafts: list[ChapterDraft] = []
        try:
            for node in iter_template_nodes(project.template_tree.nodes if project.template_tree else []):
                workspace = self.workspace_store.get_workspace(project.id, node.id)
                selected_id = workspace.get("selected_version_id")
                if not selected_id:
                    continue
                version = self.workspace_store.get_version(project.id, node.id, selected_id)
                drafts.append(
                    ChapterDraft(
                        node_id=node.id,
                        title=version["title"],
                        markdown=version["markdown"],
                        source_section_ids=version.get("source_section_ids", []),
                        validation_status=TaskStatus.passed,
                        artifact_path=version.get("artifact_path"),
                    )
                )
        except Exception:
            return []
        return drafts

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
                "evidence_count": len(task.source_mapping.evidence) if task.source_mapping else 0,
                "evidence_artifact_path": task.source_mapping.evidence_artifact_path if task.source_mapping else None,
                "error_message": task.error_message,
            }
            for task in run.chapter_tasks
        ],
    }
