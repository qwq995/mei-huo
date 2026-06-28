from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from coalplan.application.generate_chapter import generate_chapter
from coalplan.application.merge_chapters import merge_chapters
from coalplan.domain.enums import RunStatus, TaskStatus
from coalplan.domain.generation import ChapterDraft, ChapterTask, GenerationRun, SourceMatch
from coalplan.domain.outline import SourceEvidenceSpan, SourceMappingResult
from coalplan.domain.templates import TemplateNode, TemplateTree
from coalplan.infrastructure.storage.local_artifact_repository import LocalArtifactRepository


class _OmittingLLM:
    def complete(self, prompt: str) -> str:
        return "\n".join(
            [
                "# 质量控制依据",
                "## 主要来源摘要",
                "- evidence_id: ev_standard；section_id: sec_standard；来源列明施工质量技术标准。",
                "## 生成正文",
                "本节依据投标文件中质量管理要求，组织施工过程质量检查、验收和记录管理。",
                "## 人工补充需补充",
                "- 无。",
            ]
        )


class EvidenceGateGenerationTest(unittest.TestCase):
    def test_generation_requires_revision_when_required_evidence_fact_is_omitted(self) -> None:
        node = TemplateNode(id="node_quality", title="质量控制依据", level=2)
        mapping = SourceMappingResult(
            node_id=node.id,
            evidence=[
                SourceEvidenceSpan(
                    evidence_id="ev_standard",
                    section_id="sec_standard",
                    title_path=["投标文件", "质量控制目标和法律法规", "法律法规及技术标准"],
                    quote="施工过程中应遵守GB5749-2006《生活饮用水卫生标准》和GB8978-1996《污水综合排放标准》。",
                    summary="质量与施工辅助设施相关技术标准包含GB5749-2006、GB8978-1996。",
                    matched_terms=["质量", "技术标准"],
                    confidence=0.92,
                )
            ],
        )
        task = ChapterTask(
            node_id=node.id,
            title=node.title,
            source_matches=[
                SourceMatch(
                    section_id="sec_standard",
                    title_path=["投标文件", "质量控制目标和法律法规", "法律法规及技术标准"],
                    snippet="ev_standard: GB5749-2006、GB8978-1996",
                    score=0.92,
                )
            ],
            source_mapping=mapping,
        )

        with tempfile.TemporaryDirectory() as tmp:
            draft = generate_chapter(
                project_id="project_test",
                node=node,
                task=task,
                llm=_OmittingLLM(),
                artifacts=LocalArtifactRepository(Path(tmp)),
            )

        self.assertEqual(TaskStatus.needs_repair, draft.validation_status)
        self.assertEqual(TaskStatus.needs_repair, task.status)
        self.assertIn("evidence_utilization_requires_revision", {issue.code for issue in draft.validation_issues})
        self.assertIn("omitted_required_source_facts", {issue.code for issue in draft.evidence_audit.issues})
        self.assertTrue(draft.artifact_path)

    def test_generation_requires_revision_when_quality_feedback_fact_is_omitted(self) -> None:
        node = TemplateNode(id="node_quality", title="质量控制依据", level=2)
        task = ChapterTask(node_id=node.id, title=node.title)

        with tempfile.TemporaryDirectory() as tmp:
            draft = generate_chapter(
                project_id="project_test",
                node=node,
                task=task,
                llm=_OmittingLLM(),
                artifacts=LocalArtifactRepository(Path(tmp)),
                required_fact_hints=["GB50194-2014"],
            )

        self.assertEqual(TaskStatus.needs_repair, draft.validation_status)
        self.assertIn("evidence_utilization_requires_revision", {issue.code for issue in draft.validation_issues})
        self.assertIn("omitted_feedback_required_facts", {issue.code for issue in draft.evidence_audit.issues})

    def test_merge_does_not_promote_needs_repair_drafts_to_passed(self) -> None:
        node = TemplateNode(id="node_quality", title="质量控制依据", level=2)
        run = GenerationRun(
            project_name="demo",
            template_id="tpl",
            chapter_tasks=[ChapterTask(node_id=node.id, title=node.title, status=TaskStatus.needs_repair)],
        )
        draft = ChapterDraft(
            node_id=node.id,
            title=node.title,
            markdown="# 质量控制依据\n\n## 主要来源摘要\n- sec\n\n## 生成正文\n正文。\n\n## 人工补充需补充\n- 无。\n",
            validation_status=TaskStatus.needs_repair,
        )

        with tempfile.TemporaryDirectory() as tmp:
            updated = merge_chapters(
                project_id="project_test",
                run=run,
                drafts=[draft],
                template_tree=TemplateTree(id="tpl", name="模板", nodes=[node]),
                title="demo",
                artifacts=LocalArtifactRepository(Path(tmp)),
            )

        self.assertEqual(RunStatus.completed, updated.status)
        self.assertIsNotNone(updated.final_artifact_path)
        self.assertEqual(TaskStatus.passed, updated.chapter_tasks[0].status)


if __name__ == "__main__":
    unittest.main()
