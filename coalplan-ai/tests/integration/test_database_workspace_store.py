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
            supplement = workspace.add_supplement(
                project.id,
                node_id,
                {"kind": "text", "title": "现场要求", "content": "必须写入临时补充要求", "must_include": True},
            )
            version = workspace.create_chapter_version(
                project.id,
                node_id,
                title=nodes[0]["title"],
                markdown="# 测试章节\n\n## 主要来源摘要\n\n## 生成正文\n\n## 人工补充需补充\n",
                source_type="manual",
                supplement_ids=[supplement["id"]],
                created_by="user",
                select=True,
            )

            reloaded = WorkspaceStore(session_factory, artifacts)
            data = reloaded.get_workspace(project.id, node_id)
            self.assertEqual("现场要求", data["supplements"][0]["title"])
            self.assertEqual(version["id"], data["selected_version_id"])
            self.assertIn("测试章节", data["versions"][0]["markdown"])
            self.assertIn("必须写入临时补充要求", reloaded.render_chapter_context(project.id, node_id))


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


if __name__ == "__main__":
    unittest.main()
