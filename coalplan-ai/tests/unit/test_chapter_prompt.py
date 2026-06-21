from __future__ import annotations

import unittest

from coalplan.application.generate_chapter import build_chapter_prompt
from coalplan.domain.generation import ChapterTask, SourceMatch
from coalplan.domain.outline import SourceEvidenceSpan, SourceMappingResult
from coalplan.domain.templates import TemplateNode


class ChapterPromptTest(unittest.TestCase):
    def test_chapter_prompt_contains_source_evidence_map(self) -> None:
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
                        quote="项目位于煤火治理区，主要施工内容包括注水、钻孔灌浆和覆盖封堵。",
                        summary="项目位于煤火治理区。",
                        confidence=0.88,
                    )
                ],
            ),
        )

        prompt = build_chapter_prompt(
            node=node,
            task=task,
            project_profile=None,
            selected_source_sections=[],
            user_context="",
        )

        self.assertIn("原文文段映射表", prompt)
        self.assertIn("ev_overview", prompt)
        self.assertIn("L10-L12", prompt)
        self.assertIn("项目位于煤火治理区", prompt)
        self.assertIn("主要来源摘要", prompt)


if __name__ == "__main__":
    unittest.main()
