from __future__ import annotations

import unittest

from coalplan.application.pipeline_stage_gates import build_pipeline_gate_report
from coalplan.domain.documents import MarkdownSection, SourceDocument, SourceToc, SourceTocItem
from coalplan.domain.generation import ChapterTask, GenerationRun, Project, SourceMatch
from coalplan.domain.generation_control import ChapterGenerationPolicy, GenerationControlPlan, OutlineCoverageItem
from coalplan.domain.profile import ProjectProfile
from coalplan.domain.templates import TemplateNode, TemplateTree


class PipelineStageGatesTest(unittest.TestCase):
    def test_report_identifies_pipeline_gaps_without_running_llm(self) -> None:
        project = Project(name="demo", template_id="coal_fire")
        project.source_documents.append(SourceDocument(id="doc_1", file_name="bid.md", raw_artifact_path="inputs/bid.md"))
        project.sections.append(
            MarkdownSection(
                id="sec_1",
                title_path=["工程概况"],
                level=1,
                content="项目名称：示例工程。",
                source_file="bid.md",
            )
        )
        project.source_toc = SourceToc(
            items=[
                SourceTocItem(
                    section_id="sec_1",
                    title_path=["工程概况"],
                    level=1,
                    start_line=1,
                    end_line=2,
                    char_count=20,
                    snippet="项目名称：示例工程。",
                )
            ],
            artifact_json_path="inputs/toc.json",
            artifact_markdown_path="inputs/toc.md",
        )
        project.project_profile = ProjectProfile(
            project_name="示例工程",
            missing_items=["AI 项目概况抽取失败，已使用基础兜底画像"],
            source_section_ids=["sec_1"],
        )
        node = TemplateNode(id="node_1", title="工程概况", level=1)
        project.template_tree = TemplateTree(id="tpl", name="template", nodes=[node])
        run = GenerationRun(project_name=project.name, template_id=project.template_id)
        run.chapter_tasks.append(
            ChapterTask(
                node_id="node_1",
                title="工程概况",
                source_matches=[SourceMatch(section_id="sec_1", title_path=["工程概况"], snippet="项目名称：示例工程。", score=1.0)],
            )
        )
        project.runs.append(run)
        control_plan = GenerationControlPlan(
            project_id=project.id,
            outline_coverage=[OutlineCoverageItem(topic="施工部署", status="missing")],
            chapter_policies=[ChapterGenerationPolicy(node_id="node_1", title="工程概况", target_word_count=None)],
        )

        report = build_pipeline_gate_report(project=project, template_tree=project.template_tree, control_plan=control_plan)
        by_name = {gate.name: gate for gate in report.gates}

        self.assertEqual("warning", report.overall_status)
        self.assertEqual("passed", by_name["input"].status)
        self.assertEqual("warning", by_name["profile"].status)
        self.assertEqual("warning", by_name["coverage"].status)
        self.assertEqual("warning", by_name["detail"].status)
        self.assertEqual("pending", by_name["revision"].status)
        self.assertEqual("pending", by_name["merge"].status)

    def test_version_gate_warns_when_selected_content_tree_has_missing_sources(self) -> None:
        project = Project(name="demo", template_id="tpl")
        node = TemplateNode(id="node_1", title="注水工程施工", level=1)
        project.template_tree = TemplateTree(id="tpl", name="template", nodes=[node])
        run = GenerationRun(project_name=project.name, template_id=project.template_id)
        run.chapter_tasks.append(ChapterTask(node_id="node_1", title=node.title))
        project.runs.append(run)
        workspace_store = _FakeWorkspaceStore(
            {
                "selected_version_id": "ver_1",
                "versions": [
                    {
                        "id": "ver_1",
                        "content_tree": {
                            "nodes": [
                                {
                                    "id": "gcn_1",
                                    "title": "注水流程",
                                    "source_status": "missing",
                                    "children": [],
                                },
                                {
                                    "id": "gcn_2",
                                    "title": "质量控制",
                                    "source_status": "weak",
                                    "children": [],
                                },
                            ]
                        },
                        "content_revision_plan": {
                            "metrics": {"evidence_targeted_rewrite_count": 1},
                            "items": [
                                {
                                    "content_node_id": "gcn_1",
                                    "title": "娉ㄦ按娴佺▼",
                                    "action": "remap_sources",
                                    "reason": "omitted_required_source_facts must be absorbed",
                                    "requires_llm": True,
                                    "requires_user_confirmation": False,
                                },
                                {
                                    "content_node_id": "gcn_2",
                                    "title": "璐ㄩ噺鎺у埗",
                                    "action": "review_source_link",
                                    "requires_llm": True,
                                    "requires_user_confirmation": True,
                                },
                            ]
                        },
                    }
                ],
            }
        )

        report = build_pipeline_gate_report(
            project=project,
            template_tree=project.template_tree,
            workspace_store=workspace_store,
        )
        version_gate = {gate.name: gate for gate in report.gates}["version"]

        self.assertEqual("warning", version_gate.status)
        self.assertEqual(1, version_gate.metrics["selected_version_count"])
        self.assertEqual(1, version_gate.metrics["selected_version_missing_source_subsections"])
        self.assertEqual(1, version_gate.metrics["selected_version_weak_source_subsections"])
        self.assertEqual(2, version_gate.metrics["selected_version_content_revision_actions"])
        self.assertEqual(2, version_gate.metrics["selected_version_content_revision_llm_actions"])
        self.assertEqual(1, version_gate.metrics["selected_version_content_revision_user_actions"])
        self.assertEqual(1, version_gate.metrics["selected_version_evidence_targeted_content_revision_actions"])
        self.assertEqual(1, version_gate.metrics["selected_version_missing_generation_metadata"])
        self.assertTrue(any("missing subsection sources" in issue for issue in version_gate.issues))
        self.assertTrue(any("generated subsection revision actions" in issue for issue in version_gate.issues))
        self.assertTrue(any("lacks generation metadata" in issue for issue in version_gate.issues))

    def test_version_gate_warns_when_selected_version_has_evidence_audit_issues(self) -> None:
        project = Project(name="demo", template_id="tpl")
        node = TemplateNode(id="node_1", title="注水工程施工", level=1)
        project.template_tree = TemplateTree(id="tpl", name="template", nodes=[node])
        run = GenerationRun(project_name=project.name, template_id=project.template_id)
        run.chapter_tasks.append(ChapterTask(node_id="node_1", title=node.title))
        project.runs.append(run)
        workspace_store = _FakeWorkspaceStore(
            {
                "selected_version_id": "ver_1",
                "versions": [
                    {
                        "id": "ver_1",
                        "content_tree": {"nodes": []},
                        "content_revision_plan": {"items": []},
                        "generation_metadata": {
                            "selected_pattern_keys": [],
                            "pattern_evidence_scope": "structural guidance only",
                        },
                        "evidence_audit": {
                            "node_id": "node_1",
                            "title": node.title,
                            "evidence_count": 3,
                            "coverage_ratio": 0.2,
                            "issues": [
                                {
                                    "code": "omitted_required_source_facts",
                                    "suggested_action": "regenerate",
                                    "message": "omitted facts",
                                }
                            ],
                        },
                    }
                ],
            }
        )

        report = build_pipeline_gate_report(
            project=project,
            template_tree=project.template_tree,
            workspace_store=workspace_store,
        )
        version_gate = {gate.name: gate for gate in report.gates}["version"]

        self.assertEqual("warning", version_gate.status)
        self.assertEqual(1, version_gate.metrics["selected_version_evidence_revision_actions"])
        self.assertEqual(1, version_gate.metrics["selected_version_evidence_revision_llm_actions"])
        self.assertTrue(any("evidence utilization review" in issue for issue in version_gate.issues))


class _FakeWorkspaceStore:
    def __init__(self, workspace: dict) -> None:
        self.workspace = workspace

    def list_outline_nodes(self, project_id: str) -> list[dict]:
        return [{"node_id": "node_1", "title": "注水工程施工", "enabled": True}]

    def get_workspace(self, project_id: str, node_id: str) -> dict:
        return self.workspace


if __name__ == "__main__":
    unittest.main()
