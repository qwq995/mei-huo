from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from coalplan.application.generate_chapter import build_chapter_prompt, build_generation_metadata, generate_chapter
from coalplan.application.word_count_targets import count_words
from coalplan.domain.documents import MarkdownSection
from coalplan.domain.enums import TaskStatus
from coalplan.domain.generation import ChapterTask, SourceMatch
from coalplan.domain.generation_control import ChapterGenerationPolicy
from coalplan.domain.outline import SourceEvidenceSpan, SourceMappingResult
from coalplan.domain.templates import TemplateNode
from coalplan.infrastructure.storage.local_artifact_repository import LocalArtifactRepository
from coalplan.infrastructure.validation.markdown_contract import REQUIRED_HEADINGS


class ChapterPromptTest(unittest.TestCase):
    def test_chapter_prompt_contains_source_evidence_map_and_pattern_guidance(self) -> None:
        node = TemplateNode(
            id="node_overview",
            title="工程概况",
            level=2,
            source_rules=["依据工程概况章节编写"],
            auto_fill=["归纳项目范围"],
            manual_fill=["合同工期需人工确认"],
        )
        task = ChapterTask(
            node_id=node.id,
            title=node.title,
            target_word_count=900,
            source_matches=[
                SourceMatch(
                    section_id="sec_overview",
                    title_path=["投标文件", "工程概况"],
                    snippet="ev_overview: 项目位于煤火治理区。",
                    score=0.9,
                )
            ],
            source_mapping=SourceMappingResult(
                node_id=node.id,
                evidence=[
                    SourceEvidenceSpan(
                        evidence_id="ev_overview",
                        section_id="sec_overview",
                        title_path=["投标文件", "工程概况"],
                        start_line=10,
                        end_line=12,
                        template_module="main_sources",
                        quote="项目位于煤火治理区，裂隙注水初始压力控制在0.2 - 0.3MPa，主要施工内容包括注水、钻孔灌浆和覆盖封堵。",
                        summary="项目位于煤火治理区，注水压力0.2 - 0.3MPa。",
                        confidence=0.88,
                    )
                ],
            ),
        )
        policy = ChapterGenerationPolicy(
            node_id=node.id,
            title=node.title,
            detail_level="subsection_required",
            split_required=True,
            max_source_matches=14,
            max_evidence_spans=28,
            source_subtopics=["注水范围", "压力流量控制"],
            required_subtopics=["施工准备", "质量检查"],
            writing_pattern_key="craft",
            writing_pattern_matches=["craft", "quality"],
            pattern_required_source_facts=["工艺流程", "控制参数"],
            pattern_human_only_items=["审批后的最终参数"],
            pattern_prompt_cards=[
                {
                    "pattern_key": "craft",
                    "matched_terms": ["grouting"],
                    "organization_policy": ["Use corpus patterns structurally only."],
                    "source_mapping_requirements": ["Find pressure and flow source evidence."],
                    "detail_design_rules": ["Allocate target word count across process/control/acceptance."],
                    "generation_moves": ["Write process, resources, controls, acceptance."],
                    "human_only_items": ["approved final pressure"],
                    "revision_checks": ["regenerate when mapped pressure is omitted"],
                }
            ],
            reason="dense craft chapter",
        )

        prompt = build_chapter_prompt(
            node=node,
            task=task,
            project_profile=None,
            selected_source_sections=[],
            user_context="",
            required_fact_hints=["GB50194-2014"],
            generation_policy=policy,
        )

        self.assertIn("ev_overview", prompt)
        self.assertIn("sec_overview", prompt)
        self.assertIn("0.2 - 0.3MPa", prompt)
        self.assertIn("L10-L12", prompt)
        self.assertIn("required_source_facts", prompt)
        self.assertIn("quality_feedback_required_facts", prompt)
        self.assertIn("GB50194-2014", prompt)
        self.assertIn("pattern_key", prompt)
        self.assertIn("evidence_scope", prompt)
        self.assertIn("detail_level: subsection_required", prompt)
        self.assertIn("source_subtopics", prompt)
        self.assertIn("压力流量控制", prompt)
        self.assertIn("pattern_required_source_facts", prompt)
        self.assertIn("审批后的最终参数", prompt)
        self.assertIn("pattern_prompt_cards", prompt)
        self.assertIn("Find pressure and flow source evidence.", prompt)
        self.assertIn("Write process, resources, controls, acceptance.", prompt)
        self.assertIn("regenerate when mapped pressure is omitted", prompt)
        self.assertIn("dense craft chapter", prompt)
        self.assertIn("硬上限", prompt)
        self.assertIn("主要来源摘要最多 6 条", prompt)

        metadata = build_generation_metadata(node=node, task=task, generation_policy=policy)
        self.assertIn("craft", metadata["selected_pattern_keys"])
        self.assertIn("quality", metadata["selected_pattern_keys"])
        self.assertIn("writing_guidance", metadata)
        self.assertIn("local_pattern_matches", metadata)
        self.assertIn("structural guidance only", metadata["pattern_evidence_scope"])
        self.assertTrue(any("Do not copy" in item for item in metadata["non_factual_pattern_rules"]))

    def test_generation_marks_needs_repair_when_pattern_card_moves_are_omitted(self) -> None:
        node = TemplateNode(id="node_craft", title="craft", level=2, source_rules=["method"], auto_fill=["write method"])
        task = ChapterTask(node_id=node.id, title=node.title)
        policy = ChapterGenerationPolicy(
            node_id=node.id,
            title=node.title,
            writing_pattern_key="craft",
            writing_pattern_matches=["craft"],
            pattern_prompt_cards=[
                {
                    "pattern_key": "craft",
                    "generation_moves": ["Write process controls", "Record acceptance evidence"],
                    "detail_design_rules": ["Allocate target word count across process/control/acceptance."],
                    "source_mapping_requirements": ["Map process and acceptance evidence."],
                    "revision_checks": ["regenerate when process controls are omitted"],
                }
            ],
        )
        markdown = "\n".join(
            [
                "# craft",
                "",
                REQUIRED_HEADINGS[0],
                "- section_id: sec_demo",
                "",
                REQUIRED_HEADINGS[1],
                "This chapter only says generic construction text.",
                "",
                REQUIRED_HEADINGS[2],
                "- none",
            ]
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            draft = generate_chapter(
                project_id="project_demo",
                node=node,
                task=task,
                llm=_StaticLLM(markdown),
                artifacts=LocalArtifactRepository(Path(temp_dir)),
                generation_policy=policy,
            )

        self.assertEqual(TaskStatus.needs_repair, draft.validation_status)
        self.assertEqual(TaskStatus.needs_repair, task.status)
        self.assertTrue(any(issue.code == "writing_pattern_requires_revision" for issue in draft.validation_issues))
        self.assertEqual("warning", draft.generation_metadata["generation_metadata_audit"]["status"])

    def test_chapter_prompt_limits_full_source_sections_by_word_budget(self) -> None:
        node = TemplateNode(
            id="node_pressure",
            title="压力流量控制",
            level=3,
            source_rules=["依据注水工程章节"],
            auto_fill=["归纳压力流量控制措施"],
            manual_fill=["最终注水参数需现场确认"],
        )
        task = ChapterTask(node_id=node.id, title=node.title, target_word_count=800)
        sections = [
            MarkdownSection(
                id=f"sec_{index}",
                title_path=["投标文件", f"章节{index}"],
                level=2,
                content=("来源内容" * 1200) + f"TAIL_{index}",
                source_file="bid.md",
            )
            for index in range(7)
        ]

        prompt = build_chapter_prompt(
            node=node,
            task=task,
            project_profile=None,
            selected_source_sections=sections,
        )

        self.assertIn("section_id: sec_0", prompt)
        self.assertIn("section_id: sec_4", prompt)
        self.assertNotIn("section_id: sec_5", prompt)
        self.assertNotIn("TAIL_0", prompt)
        self.assertIn("已按目标字数限幅省略 2 个低优先级来源章节", prompt)

    def test_generation_repairs_overlong_markdown_once_before_validation(self) -> None:
        node = TemplateNode(
            id="node_budget",
            title="预算控制",
            level=2,
            source_rules=["依据来源"],
            auto_fill=["归纳措施"],
            manual_fill=["现场参数需确认"],
        )
        task = ChapterTask(node_id=node.id, title=node.title, target_word_count=200)
        overlong = "\n".join(
            [
                "# 预算控制",
                "",
                REQUIRED_HEADINGS[0],
                "- section_id: sec_demo",
                "",
                REQUIRED_HEADINGS[1],
                "超长正文" * 300,
                "",
                REQUIRED_HEADINGS[2],
                "- 【需人工补充：现场参数需确认】",
            ]
        )
        repaired = "\n".join(
            [
                "# 预算控制",
                "",
                REQUIRED_HEADINGS[0],
                "- section_id: sec_demo",
                "",
                REQUIRED_HEADINGS[1],
                "压缩后的正文。",
                "",
                REQUIRED_HEADINGS[2],
                "- 【需人工补充：现场参数需确认】",
            ]
        )
        llm = _SequenceLLM([overlong, repaired])

        with tempfile.TemporaryDirectory() as temp_dir:
            draft = generate_chapter(
                project_id="project_demo",
                node=node,
                task=task,
                llm=llm,
                artifacts=LocalArtifactRepository(Path(temp_dir)),
            )

        self.assertEqual(2, llm.call_count)
        self.assertLessEqual(count_words(draft.markdown), 270)
        self.assertIn("压缩后的正文", draft.markdown)


class _StaticLLM:
    def __init__(self, markdown: str) -> None:
        self.markdown = markdown

    def complete(self, _prompt: str) -> str:
        return self.markdown


class _SequenceLLM:
    def __init__(self, responses: list[str]) -> None:
        self.responses = responses
        self.call_count = 0

    def complete(self, _prompt: str) -> str:
        response = self.responses[min(self.call_count, len(self.responses) - 1)]
        self.call_count += 1
        return response


if __name__ == "__main__":
    unittest.main()
