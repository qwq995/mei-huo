from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from coalplan.application.run_generation_pipeline import GenerationPipeline
from coalplan.application.workspace_store import WorkspaceStore
from coalplan.infrastructure.database.repository import DatabaseProjectRepository
from coalplan.infrastructure.database.session import create_session_factory, init_database, sqlite_url_for_storage
from coalplan.infrastructure.llm.fake_llm import FakeLLMClient
from coalplan.infrastructure.markdown.parser import MarkdownDocumentParser
from coalplan.infrastructure.retrieval.keyword_retriever import KeywordSourceRetriever
from coalplan.infrastructure.storage.local_artifact_repository import LocalArtifactRepository
from coalplan.infrastructure.templates.markdown_template_loader import MarkdownTemplateLoader


class DatabaseWorkspaceStoreTest(unittest.TestCase):
    def test_outline_proposals_reuse_pending_candidate_but_chapter_proposals_keep_versions(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp = Path(temp_dir)
            session_factory = create_session_factory(sqlite_url_for_storage(temp / "db"))
            init_database(session_factory)
            artifacts = LocalArtifactRepository(temp / "artifacts")
            workspace = WorkspaceStore(session_factory, artifacts)
            project_id = "project_dedupe"

            first = workspace.propose_outline_change(project_id, "repair outline", [{"node_id": "n1", "title": "A"}])
            second = workspace.propose_outline_change(project_id, "repair outline", [{"node_id": "n2", "title": "B"}])

            self.assertEqual(first["id"], second["id"])
            pending_outline = workspace.list_proposals(project_id, target_type="outline", status="pending")
            self.assertEqual(1, len(pending_outline))
            self.assertEqual("n2", pending_outline[0]["preview"]["nodes"][0]["node_id"])

            workspace._create_proposal(project_id, "outline", project_id, "legacy repair", {"nodes": [{"node_id": "old_1"}]})
            workspace._create_proposal(project_id, "outline", project_id, "legacy repair", {"nodes": [{"node_id": "old_2"}]})
            reused = workspace.propose_outline_change(project_id, "legacy repair", [{"node_id": "new_1"}])

            self.assertEqual("new_1", reused["preview"]["nodes"][0]["node_id"])
            pending_legacy = [
                item
                for item in workspace.list_proposals(project_id, target_type="outline", status="pending")
                if item["suggestion"] == "legacy repair"
            ]
            superseded_legacy = [
                item
                for item in workspace.list_proposals(project_id, target_type="outline", status="superseded")
                if item["suggestion"] == "legacy repair"
            ]
            self.assertEqual(1, len(pending_legacy))
            self.assertEqual(1, len(superseded_legacy))

            chapter_first = workspace.propose_chapter_edit(project_id, "chapter_1", "revise", "# one")
            chapter_second = workspace.propose_chapter_edit(project_id, "chapter_1", "revise", "# two")

            self.assertNotEqual(chapter_first["id"], chapter_second["id"])
            pending_chapter = workspace.list_proposals(project_id, target_type="chapter", status="pending")
            self.assertEqual(2, len(pending_chapter))

    def test_workspace_data_survives_new_store_instance(self) -> None:
        repo_root = Path(__file__).resolve().parents[2]
        assets = repo_root / "src" / "coalplan" / "assets"
        sample = (assets / "samples" / "coal_fire_bid.normalized.md").read_text(encoding="utf-8-sig")

        with tempfile.TemporaryDirectory() as temp_dir:
            temp = Path(temp_dir)
            session_factory = create_session_factory(sqlite_url_for_storage(temp / "db"))
            init_database(session_factory)
            artifacts = LocalArtifactRepository(temp / "artifacts")
            workspace = WorkspaceStore(session_factory, artifacts)
            pipeline = _pipeline(session_factory, artifacts, workspace, assets)

            project = pipeline.create_project("火区治理工作台")
            project = pipeline.ingest_bid_markdown(project.id, file_name="bid.md", content=sample)
            pipeline.prepare_directory(project.id)
            nodes = workspace.list_outline_nodes(project.id)
            self.assertGreater(len(nodes), 0)

            node_id = nodes[0]["node_id"]
            workspace.update_outline_word_counts(project.id, {node_id: 900})
            nodes = workspace.list_outline_nodes(project.id)
            self.assertEqual(900, next(item for item in nodes if item["node_id"] == node_id)["target_word_count"])
            supplement = workspace.add_supplement(
                project.id,
                node_id,
                {"kind": "text", "title": "现场要求", "content": "必须写入临时补充要求", "must_include": True},
            )
            attachment = workspace.add_attachment(
                project.id,
                node_id,
                file_name="site-note.md",
                content_type="text/markdown",
                content="附件说明：现场照片编号 A-01。".encode("utf-8"),
                description="必须参考现场照片编号 A-01 的附件说明。",
            )
            version = workspace.create_chapter_version(
                project.id,
                node_id,
                title=nodes[0]["title"],
                markdown="# 测试章节\n\n## 主要来源摘要\n\n## 生成正文\n### 子节一\n原始内容。\n\n## 人工补充需补充\n",
                source_type="manual",
                supplement_ids=[supplement["id"]],
                created_by="user",
                select=True,
                generation_metadata={
                    "selected_pattern_keys": ["craft", "quality"],
                    "pattern_evidence_scope": "structural guidance only; not a factual source",
                    "non_factual_pattern_rules": ["Do not copy unsupported project facts from the pattern library."],
                },
                evidence_audit={
                    "node_id": node_id,
                    "title": nodes[0]["title"],
                    "evidence_count": 2,
                    "required_source_facts": [
                        {
                            "fact_id": "ev_1:fact_1",
                            "evidence_id": "ev_1",
                            "section_id": "sec_1",
                            "fact_type": "parameter",
                            "text": "Subsection one must include parameter 0.2MPa.",
                            "tokens": ["0.2MPa"],
                        }
                    ],
                    "omitted_required_fact_ids": ["ev_1:fact_1"],
                    "feedback_required_fact_hints": [],
                    "omitted_feedback_fact_hints": [],
                    "used_evidence_ids": ["ev_1"],
                    "unused_high_value_evidence_ids": [],
                    "coverage_ratio": 0.5,
                    "manual_items_with_source_support": [],
                    "issues": [],
                },
            )

            reloaded = WorkspaceStore(session_factory, artifacts)
            data = reloaded.get_workspace(project.id, node_id)
            self.assertEqual("现场要求", data["supplements"][0]["title"])
            self.assertEqual(attachment["id"], data["attachments"][0]["id"])
            self.assertEqual(version["id"], data["selected_version_id"])
            self.assertIn("测试章节", data["versions"][0]["markdown"])
            self.assertIn("content_tree", data["versions"][0])
            self.assertIn("content_revision_plan", data["versions"][0])
            self.assertTrue(data["versions"][0]["content_revision_plan_path"].endswith(".content_revision_plan.json"))
            self.assertEqual(["craft", "quality"], data["versions"][0]["generation_metadata"]["selected_pattern_keys"])
            self.assertTrue(data["versions"][0]["generation_metadata_path"].endswith(".generation_metadata.json"))
            self.assertEqual(0.5, data["versions"][0]["evidence_audit"]["coverage_ratio"])
            self.assertTrue(data["versions"][0]["evidence_audit_path"].endswith(".evidence_audit.json"))
            metadata = reloaded.get_version_generation_metadata(project.id, node_id, version["id"])
            self.assertIn("organization_audit", metadata)
            self.assertIn("pattern_audits", metadata["organization_audit"])
            evidence_audit = reloaded.get_version_evidence_audit(project.id, node_id, version["id"])
            self.assertEqual(["ev_1"], evidence_audit["used_evidence_ids"])
            tree = reloaded.get_version_content_tree(project.id, node_id, version["id"])
            content_node = _find_generated_node(tree["nodes"], "子节一")
            self.assertIsNotNone(content_node)
            revision_plan = reloaded.get_version_content_revision_plan(project.id, node_id, version["id"])
            self.assertEqual(version["id"], revision_plan["version_id"])
            self.assertGreaterEqual(revision_plan["metrics"]["candidate_count"], 1)
            self.assertEqual(1, revision_plan["metrics"]["evidence_targeted_rewrite_count"])
            self.assertTrue(
                any(
                    item["action"] == "rewrite_subsection" and "0.2MPa" in " ".join(item["next_steps"])
                    for item in revision_plan["items"]
                )
            )
            revision_targets = pipeline._version_content_revision_targets(project.id)
            self.assertTrue(
                any(
                    target["action"] == "rewrite_subsection" and "0.2MPa" in " ".join(target.get("next_steps") or [])
                    for target in revision_targets
                )
            )
            learning = pipeline.quality_iteration_learning_report(
                project.id,
                quality_iteration={
                    "project_id": project.id,
                    "status": "warning",
                    "round_count": 0,
                    "rounds": [],
                    "final_audit": {},
                    "content_revision_targets": [],
                    "generation_metadata_targets": [],
                },
            )
            self.assertGreaterEqual(learning["metrics"]["content_revision_target_count"], 1)
            self.assertEqual(1, learning["metrics"]["evidence_targeted_content_revision_target_count"])
            edited = reloaded.update_version_content_node(
                project.id,
                node_id,
                version["id"],
                content_node["id"],
                "### 子节一\n更新后的内容。",
            )
            self.assertIn("更新后的内容", edited["markdown"])
            self.assertEqual("subsection_edit", edited["source_type"])
            self.assertIn("必须写入临时补充要求", reloaded.render_chapter_context(project.id, node_id))
            self.assertIn("site-note.md", reloaded.render_chapter_context(project.id, node_id))


def _pipeline(session_factory, artifacts, workspace, assets: Path) -> GenerationPipeline:
    return GenerationPipeline(
        projects=DatabaseProjectRepository(session_factory),
        artifacts=artifacts,
        parser=MarkdownDocumentParser(),
        templates=MarkdownTemplateLoader(assets / "templates"),
        retriever=KeywordSourceRetriever(),
        llm=FakeLLMClient(),
        workspace_store=workspace,
    )


def _find_generated_node(nodes: list[dict], title: str) -> dict | None:
    for node in nodes:
        if node["title"] == title:
            return node
        found = _find_generated_node(node.get("children", []), title)
        if found:
            return found
    return None


if __name__ == "__main__":
    unittest.main()
