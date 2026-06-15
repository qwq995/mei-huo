from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from coalplan.application.run_generation_pipeline import GenerationPipeline
from coalplan.domain.enums import RunStatus
from coalplan.infrastructure.llm.fake_llm import FakeLLMClient
from coalplan.infrastructure.markdown.parser import MarkdownDocumentParser
from coalplan.infrastructure.retrieval.keyword_retriever import KeywordSourceRetriever
from coalplan.infrastructure.storage.local_artifact_repository import LocalArtifactRepository
from coalplan.infrastructure.storage.local_project_repository import LocalProjectRepository
from coalplan.infrastructure.templates.markdown_template_loader import MarkdownTemplateLoader


class CoalFirePipelineFakeLLMTest(unittest.TestCase):
    def test_generation_requires_bid_markdown_sections(self) -> None:
        repo_root = Path(__file__).resolve().parents[2]
        assets = repo_root / "src" / "coalplan" / "assets"

        with tempfile.TemporaryDirectory() as temp_dir:
            temp = Path(temp_dir)
            pipeline = _pipeline(temp, assets)
            project = pipeline.create_project("煤火治理演示")

            with self.assertRaisesRegex(ValueError, "No bid markdown sections"):
                pipeline.prepare_run(project.id)

    def test_end_to_end_generation_and_merge_persists_intermediate_artifacts(self) -> None:
        repo_root = Path(__file__).resolve().parents[2]
        assets = repo_root / "src" / "coalplan" / "assets"
        sample = (assets / "samples" / "coal_fire_bid.normalized.md").read_text(encoding="utf-8-sig")

        with tempfile.TemporaryDirectory() as temp_dir:
            temp = Path(temp_dir)
            pipeline = _pipeline(temp, assets)
            project = pipeline.create_project("煤火治理演示")
            project = pipeline.ingest_bid_markdown(project.id, file_name="bid.md", content=sample)

            self.assertGreater(len(project.sections), 0)
            self.assertIsNotNone(project.source_toc)
            artifact_root = temp / "artifacts" / project.id
            self.assertTrue((artifact_root / "inputs" / "sections.json").exists())
            self.assertTrue((artifact_root / "inputs" / "toc.json").exists())
            self.assertTrue((artifact_root / "inputs" / "toc.md").exists())
            self.assertTrue((artifact_root / "inputs" / "sections" / f"{project.sections[0].id}.md").exists())

            run = pipeline.prepare_run(project.id)
            self.assertGreater(len(run.chapter_tasks), 0)
            project_after_prepare = pipeline.projects.get(project.id)
            self.assertIsNotNone(project_after_prepare.project_profile)
            self.assertIsNotNone(project_after_prepare.outline_plan)
            self.assertTrue((artifact_root / "profile" / "project_profile.json").exists())
            self.assertTrue((artifact_root / "outline" / "generated_outline.json").exists())

            run = pipeline.generate_all(project.id)
            self.assertEqual(RunStatus.completed, run.status)
            self.assertTrue((artifact_root / "runs" / run.id / "validation.json").exists())
            self.assertTrue(any((artifact_root / "mapping").glob("*.json")))
            self.assertTrue(any((artifact_root / "chapters").glob("*.md")))

            run = pipeline.merge_latest(project.id)
            self.assertIsNotNone(run.final_artifact_path)
            final_markdown = Path(run.final_artifact_path).read_text(encoding="utf-8")
            self.assertIn("# 煤火治理演示施工组织设计", final_markdown)
            self.assertIn("## 主要来源摘要", final_markdown)
            self.assertIn("## 人工补充需补充", final_markdown)
            self.assertIn("【需人工补充：", final_markdown)


def _pipeline(temp: Path, assets: Path) -> GenerationPipeline:
    return GenerationPipeline(
        projects=LocalProjectRepository(temp / "projects"),
        artifacts=LocalArtifactRepository(temp / "artifacts"),
        parser=MarkdownDocumentParser(),
        templates=MarkdownTemplateLoader(assets / "templates"),
        retriever=KeywordSourceRetriever(),
        llm=FakeLLMClient(),
    )


if __name__ == "__main__":
    unittest.main()
