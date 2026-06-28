from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from typing import Any

from coalplan.application.run_generation_pipeline import GenerationPipeline, _filter_required_fact_hints_by_source
from coalplan.domain.documents import MarkdownSection, SourceToc, SourceTocItem
from coalplan.domain.enums import TaskStatus
from coalplan.domain.generation import ChapterDraft, ChapterTask, GenerationRun, Project, SourceMatch
from coalplan.domain.generation_control import EvidenceUtilizationAudit, RequiredSourceFact
from coalplan.domain.outline import TemplateOutlineNode, TemplateOutlinePlan
from coalplan.domain.profile import ProjectProfile
from coalplan.domain.templates import TemplateNode, TemplateTree
from coalplan.infrastructure.llm.fake_llm import FakeLLMClient
from coalplan.infrastructure.markdown.parser import MarkdownDocumentParser
from coalplan.infrastructure.retrieval.keyword_retriever import KeywordSourceRetriever
from coalplan.infrastructure.storage.local_artifact_repository import LocalArtifactRepository
from coalplan.infrastructure.storage.local_project_repository import LocalProjectRepository
from coalplan.infrastructure.templates.markdown_template_loader import MarkdownTemplateLoader
from coalplan.infrastructure.validation.markdown_contract import REQUIRED_HEADINGS


class CapturingLLM(FakeLLMClient):
    def __init__(self) -> None:
        self.prompts: list[str] = []
        self.json_prompts: list[str] = []

    def complete(self, prompt: str) -> str:
        self.prompts.append(prompt)
        title = "water injection"
        return "\n".join(
            [
                f"# {title}",
                "",
                REQUIRED_HEADINGS[0],
                "- section_id: sec_111111111111; evidence_id: ev_1",
                "",
                REQUIRED_HEADINGS[1],
                "The chapter incorporates the required source fact: 0.2 - 0.3MPa.",
                "",
                REQUIRED_HEADINGS[2],
                "- none",
            ]
        )

    def complete_json(self, prompt: str, *, schema_name: str) -> dict[str, Any]:
        self.json_prompts.append(prompt)
        if schema_name == "SourceMappingResult":
            return {
                "node_id": "water",
                "matches": [
                    {
                        "section_id": "sec_111111111111",
                        "title_path": ["bid", "water"],
                        "usage": "method",
                        "reason": "source chapter contains water injection method and pressure",
                        "confidence": 0.9,
                    }
                ],
                "missing_evidence": [],
            }
        return super().complete_json(prompt, schema_name=schema_name)


class SelectedVersionWorkspace:
    def __init__(self, selected_version: dict) -> None:
        self.selected_version = selected_version
        self.created_versions: list[dict] = []

    def outline_tree(self, project_id: str) -> list:
        return []

    def get_workspace(self, project_id: str, node_id: str) -> dict:
        return {"selected_version_id": self.selected_version["id"], "supplements": []}

    def get_version(self, project_id: str, node_id: str, version_id: str) -> dict:
        return self.selected_version

    def create_chapter_version(self, *args, **kwargs) -> dict:
        version = {"args": args, **kwargs}
        self.created_versions.append(version)
        return version


class RevisionContextPipelineTest(unittest.TestCase):
    def test_required_fact_hints_are_filtered_against_current_sources(self) -> None:
        source_text = "裂隙注水采用定向注水，注水压力 0.2~0.3MPa，结合现场温度反馈控制停注标准。"
        hints = [
            "3）裂隙注水：采用鸭嘴式喷头定向注水，注水压力 0.2~0.3MPa，避免水流沿裂隙快速流失",
            "旁多水利枢纽工程采用TBM和钻爆法联合施工，距下游拉萨市直线距离63km。",
            "扎拉坝址控制流域面积8546km2，多年平均流量110m³/s。",
            "根据《岩土工程勘察规范》（GB 50021）确定勘查点位和钻孔深度。",
        ]

        filtered = _filter_required_fact_hints_by_source(hints, source_text)

        self.assertEqual([hints[0]], filtered)

    def test_revision_action_injects_decision_context_into_next_llm_prompt(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            llm = CapturingLLM()
            projects = LocalProjectRepository(root / "projects")
            artifacts = LocalArtifactRepository(root / "artifacts")
            pipeline = GenerationPipeline(
                projects=projects,
                artifacts=artifacts,
                parser=MarkdownDocumentParser(),
                templates=MarkdownTemplateLoader(Path("src/coalplan/assets/templates")),
                retriever=KeywordSourceRetriever(),
                llm=llm,
                structured_llm=llm,
                workspace_store=None,
            )
            project, run, draft = _project_with_omitted_required_fact()
            projects.save(project)
            pipeline._drafts[run.id] = [draft]

            result = pipeline.execute_revision_action(project.id, "water", action="regenerate")

            self.assertEqual("chapter_version", result["kind"])
            self.assertTrue(llm.prompts)
            prompt = "\n\n--- prompt boundary ---\n\n".join(llm.prompts)
            self.assertIn("Revision Control Requirements", prompt)
            self.assertIn("omitted_required_source_facts", prompt)
            self.assertIn("quality_feedback_required_facts", prompt)
            self.assertIn("- Initial water injection pressure is 0.2 - 0.3MPa.", _prompt_section(prompt, "## quality_feedback_required_facts"))
            self.assertIn("0.2 - 0.3MPa", prompt)
            self.assertIn("ev_1", prompt)
            mapping_prompt = "\n\n--- prompt boundary ---\n\n".join(llm.json_prompts)
            self.assertIn("Mapping Control Context", mapping_prompt)
            self.assertIn("Revision Control Requirements", mapping_prompt)
            self.assertIn("0.2 - 0.3MPa", mapping_prompt)

    def test_revision_action_prefers_current_failed_draft_over_selected_version(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            llm = CapturingLLM()
            workspace = SelectedVersionWorkspace(
                {
                    "id": "ver_old",
                    "title": "water injection",
                    "markdown": "\n".join(
                        [
                            "# water injection",
                            "",
                            REQUIRED_HEADINGS[0],
                            "- section_id: sec_111111111111",
                            "",
                            REQUIRED_HEADINGS[1],
                            "Old selected version without the omitted pressure fact.",
                            "",
                            REQUIRED_HEADINGS[2],
                            "- none",
                        ]
                    ),
                    "source_section_ids": ["sec_111111111111"],
                    "source_type": "ai_generate",
                    "artifact_path": None,
                    "evidence_audit": None,
                    "generation_metadata": {},
                }
            )
            projects = LocalProjectRepository(root / "projects")
            artifacts = LocalArtifactRepository(root / "artifacts")
            pipeline = GenerationPipeline(
                projects=projects,
                artifacts=artifacts,
                parser=MarkdownDocumentParser(),
                templates=MarkdownTemplateLoader(Path("src/coalplan/assets/templates")),
                retriever=KeywordSourceRetriever(),
                llm=llm,
                structured_llm=llm,
                workspace_store=workspace,
            )
            project, run, draft = _project_with_omitted_required_fact()
            run.chapter_tasks[0].status = TaskStatus.needs_repair
            draft.validation_status = TaskStatus.needs_repair
            projects.save(project)
            pipeline._drafts[run.id] = [draft]

            result = pipeline.execute_revision_action(project.id, "water", action="regenerate")

            self.assertEqual("chapter_version", result["kind"])
            prompt = "\n\n--- prompt boundary ---\n\n".join(llm.prompts)
            self.assertIn("Revision Control Requirements", prompt)
            self.assertIn("omitted_required_source_facts", prompt)
            self.assertIn("quality_feedback_required_facts", prompt)
            self.assertIn("- Initial water injection pressure is 0.2 - 0.3MPa.", _prompt_section(prompt, "## quality_feedback_required_facts"))
            self.assertIn("0.2 - 0.3MPa", prompt)
            self.assertIn("ev_1", prompt)

    def test_revision_action_restores_failed_draft_from_persisted_validation(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            first_llm = CapturingLLM()
            projects = LocalProjectRepository(root / "projects")
            artifacts = LocalArtifactRepository(root / "artifacts")
            pipeline = GenerationPipeline(
                projects=projects,
                artifacts=artifacts,
                parser=MarkdownDocumentParser(),
                templates=MarkdownTemplateLoader(Path("src/coalplan/assets/templates")),
                retriever=KeywordSourceRetriever(),
                llm=first_llm,
                structured_llm=first_llm,
                workspace_store=None,
            )
            project, run, draft = _project_with_omitted_required_fact()
            run.chapter_tasks[0].status = TaskStatus.needs_repair
            draft.validation_status = TaskStatus.needs_repair
            artifacts.write_text(project.id, f"chapters/{draft.node_id}.md", draft.markdown)
            projects.save(project)
            pipeline._persist_validation(
                project.id,
                run,
                drafts=[draft],
                template_tree=project.template_tree,
                control_plan=pipeline._generation_control_plan(project),
            )

            fresh_llm = CapturingLLM()
            fresh_pipeline = GenerationPipeline(
                projects=projects,
                artifacts=artifacts,
                parser=MarkdownDocumentParser(),
                templates=MarkdownTemplateLoader(Path("src/coalplan/assets/templates")),
                retriever=KeywordSourceRetriever(),
                llm=fresh_llm,
                structured_llm=fresh_llm,
                workspace_store=None,
            )

            result = fresh_pipeline.execute_revision_action(project.id, "water", action="regenerate")

            self.assertEqual("chapter_version", result["kind"])
            prompt = "\n\n--- prompt boundary ---\n\n".join(fresh_llm.prompts)
            self.assertIn("Revision Control Requirements", prompt)
            self.assertIn("quality_feedback_required_facts", prompt)
            self.assertIn("- Initial water injection pressure is 0.2 - 0.3MPa.", _prompt_section(prompt, "## quality_feedback_required_facts"))


def _project_with_omitted_required_fact() -> tuple[Project, GenerationRun, ChapterDraft]:
    node = TemplateNode(
        id="water",
        title="water injection",
        level=2,
        source_rules=["water injection source"],
        auto_fill=["write method based on source"],
        manual_fill=[],
        target_word_count=700,
    )
    tree = TemplateTree(id="demo", name="demo", nodes=[node])
    section = MarkdownSection(
        id="sec_111111111111",
        title_path=["bid", "water"],
        level=2,
        content="Water injection method. Initial water injection pressure is 0.2 - 0.3MPa.",
        keywords=["water", "pressure"],
        source_file="bid.md",
        start_line=1,
        end_line=2,
    )
    run = GenerationRun(project_name="demo", template_id="demo")
    run.chapter_tasks = [
        ChapterTask(
            node_id="water",
            title="water injection",
            target_word_count=700,
            status=TaskStatus.passed,
            source_matches=[
                SourceMatch(
                    section_id="sec_111111111111",
                    title_path=["bid", "water"],
                    snippet="pressure 0.2 - 0.3MPa",
                    score=0.9,
                )
            ],
        )
    ]
    draft = ChapterDraft(
        node_id="water",
        title="water injection",
        markdown="# water injection\n\n## 涓昏鏉ユ簮鎽樿\n\n- sec_111111111111\n\n## 鐢熸垚姝ｆ枃\n\nGeneric water injection text.\n\n## 浜哄伐琛ュ厖闇€琛ュ厖\n\n- none\n",
        source_section_ids=["sec_111111111111"],
        validation_status=TaskStatus.passed,
        evidence_audit=EvidenceUtilizationAudit(
            node_id="water",
            title="water injection",
            evidence_count=1,
            required_source_facts=[
                RequiredSourceFact(
                    fact_id="ev_1:fact_1",
                    evidence_id="ev_1",
                    section_id="sec_111111111111",
                    fact_type="parameter",
                    text="Initial water injection pressure is 0.2 - 0.3MPa.",
                    tokens=["0.2 - 0.3MPa"],
                )
            ],
            omitted_required_fact_ids=["ev_1:fact_1"],
            unused_high_value_evidence_ids=["ev_1"],
            coverage_ratio=0.0,
        ),
    )
    project = Project(
        name="demo",
        template_id="demo",
        sections=[section],
        source_toc=SourceToc(
            items=[
                SourceTocItem(
                    section_id=section.id,
                    title_path=section.title_path,
                    level=section.level,
                    start_line=section.start_line,
                    end_line=section.end_line,
                    char_count=len(section.content),
                    snippet=section.content,
                )
            ]
        ),
        project_profile=ProjectProfile(
            project_name="demo",
            project_type="water injection",
            source_section_ids=[section.id],
        ),
        outline_plan=TemplateOutlinePlan(
            template_id="demo",
            nodes=[
                TemplateOutlineNode(
                    node_id=node.id,
                    title=node.title,
                    level=node.level,
                    enabled=True,
                    source_hints=[section.id],
                    main_sources=node.source_rules,
                    auto_fill=node.auto_fill,
                    manual_fill=node.manual_fill,
                    target_word_count=node.target_word_count,
                )
            ],
        ),
        template_tree=tree,
        runs=[run],
    )
    return project, run, draft


def _prompt_section(prompt: str, heading: str) -> str:
    start = prompt.index(heading)
    rest = prompt[start:]
    marker = "\n## "
    next_start = rest.find(marker, len(heading))
    return rest if next_start == -1 else rest[:next_start]


if __name__ == "__main__":
    unittest.main()
