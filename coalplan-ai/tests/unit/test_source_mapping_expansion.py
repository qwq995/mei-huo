from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from typing import Any

from coalplan.application.map_chapter_sources import map_chapter_sources
from coalplan.domain.documents import MarkdownSection, SourceTocItem
from coalplan.domain.profile import ProjectProfile
from coalplan.domain.templates import TemplateNode
from coalplan.infrastructure.storage.local_artifact_repository import LocalArtifactRepository


class _ParentOnlyMappingLLM:
    def complete_json(self, prompt: str, *, schema_name: str) -> dict[str, Any]:
        return {
            "node_id": "node_fire_status",
            "matches": [
                {
                    "section_id": "sec_parent",
                    "title_path": ["工程概况", "自然地理情况"],
                    "usage": "fact",
                    "reason": "parent title matched",
                    "confidence": 0.9,
                }
            ],
            "missing_evidence": [],
        }


class _NoisyCraftMappingLLM:
    def complete_json(self, prompt: str, *, schema_name: str) -> dict[str, Any]:
        return {
            "node_id": "node_water",
            "matches": [
                {
                    "section_id": "sec_performance",
                    "title_path": ["投标人业绩", "类似项目表"],
                    "usage": "fact",
                    "reason": "contains construction project table",
                    "confidence": 0.9,
                },
                {
                    "section_id": "sec_water",
                    "title_path": ["主要工程项目施工方法", "注水工程施工"],
                    "usage": "method",
                    "reason": "contains water injection method",
                    "confidence": 0.86,
                },
            ],
            "missing_evidence": [],
        }


class _GroutQuantityNoiseMappingLLM:
    def complete_json(self, prompt: str, *, schema_name: str) -> dict[str, Any]:
        return {
            "node_id": "node_water",
            "matches": [
                {
                    "section_id": "sec_grout_quantity",
                    "title_path": ["工程概况", "火区勘查", "作业技术依据"],
                    "usage": "quantity",
                    "reason": "contains 注水泥 quantity text",
                    "confidence": 0.9,
                },
                {
                    "section_id": "sec_water",
                    "title_path": ["主要工程项目施工方法", "注水工程施工"],
                    "usage": "method",
                    "reason": "contains real water injection method",
                    "confidence": 0.86,
                },
            ],
            "missing_evidence": [],
        }


class SourceMappingExpansionTest(unittest.TestCase):
    def test_parent_mapping_expands_to_detail_child_sections_before_evidence(self) -> None:
        toc_items = [
            SourceTocItem(
                section_id="sec_parent",
                title_path=["工程概况", "自然地理情况"],
                level=2,
                char_count=80,
                snippet="自然地理情况",
            ),
            SourceTocItem(
                section_id="sec_climate",
                title_path=["工程概况", "自然地理情况", "气候与水文条件"],
                level=3,
                char_count=420,
                snippet="年平均气温约5-8℃，年平均降水量约200～300mm。",
            ),
        ]
        sections = [
            MarkdownSection(
                id="sec_parent",
                title_path=["工程概况", "自然地理情况"],
                level=2,
                content="自然地理情况如下。",
                source_file="bid.md",
            ),
            MarkdownSection(
                id="sec_climate",
                title_path=["工程概况", "自然地理情况", "气候与水文条件"],
                level=3,
                content="年平均气温约5-8℃，冬季多大风；年平均降水量约200～300mm，主要集中在7-9月。",
                source_file="bid.md",
            ),
        ]
        node = TemplateNode(
            id="node_fire_status",
            title="火区现状",
            level=2,
            source_rules=["自然地理情况", "气候与水文条件"],
            auto_fill=["归纳火区气候水文对施工组织的影响"],
            manual_fill=["现场复核火区边界与温度"],
        )

        with tempfile.TemporaryDirectory() as tmp:
            mapping, selected_sections, source_matches = map_chapter_sources(
                project_id="project_test",
                profile=ProjectProfile(project_name="煤火治理项目"),
                toc_items=toc_items,
                sections=sections,
                node=node,
                llm=_ParentOnlyMappingLLM(),
                artifacts=LocalArtifactRepository(Path(tmp)),
                max_matches=4,
            )

        match_ids = [match.section_id for match in mapping.matches]
        self.assertIn("sec_parent", match_ids)
        self.assertIn("sec_climate", match_ids)
        self.assertIn("sec_climate", [section.id for section in selected_sections])
        self.assertIn("sec_climate", [match.section_id for match in source_matches])
        self.assertTrue(any(span.section_id == "sec_climate" for span in mapping.evidence))
        self.assertTrue(any("Expanded parent source matches" in issue for issue in mapping.validation_issues))

    def test_craft_mapping_filters_unrelated_performance_tables(self) -> None:
        toc_items = [
            SourceTocItem(
                section_id="sec_performance",
                title_path=["投标人业绩", "类似项目表"],
                level=2,
                char_count=500,
                snippet="西藏旁多水利枢纽灌溉输水洞工程II标段，承担工作：TBM和钻爆法联合施工。",
            ),
            SourceTocItem(
                section_id="sec_water",
                title_path=["主要工程项目施工方法", "注水工程施工"],
                level=2,
                char_count=420,
                snippet="裂隙注水采用鸭嘴式喷头，控制注水压力和流量。",
            ),
        ]
        sections = [
            MarkdownSection(
                id="sec_performance",
                title_path=["投标人业绩", "类似项目表"],
                level=2,
                content="| 项目 | 承担工作 | 开工日期 |\n| 西藏旁多水利枢纽灌溉输水洞工程II标段 | TBM和钻爆法联合施工 | 2007年4月 |",
                source_file="bid.md",
            ),
            MarkdownSection(
                id="sec_water",
                title_path=["主要工程项目施工方法", "注水工程施工"],
                level=2,
                content="裂隙注水：利用高压风枪清理裂隙杂物，采用鸭嘴式喷头定向注水，注水压力 0.2~0.3MPa。",
                source_file="bid.md",
            ),
        ]
        node = TemplateNode(
            id="node_water",
            title="3.2.1 注水工程施工",
            level=3,
            source_rules=["注水施工工艺、压力、流量、裂隙注水控制。"],
            auto_fill=["按注水施工准备、工艺流程、参数控制和质量安全组织正文。"],
            manual_fill=["注水孔位、孔深、孔径、现场温度反馈和停注标准。"],
        )

        with tempfile.TemporaryDirectory() as tmp:
            mapping, selected_sections, _ = map_chapter_sources(
                project_id="project_test",
                profile=ProjectProfile(project_name="煤火治理项目"),
                toc_items=toc_items,
                sections=sections,
                node=node,
                llm=_NoisyCraftMappingLLM(),
                artifacts=LocalArtifactRepository(Path(tmp)),
                max_matches=4,
            )

        match_ids = [match.section_id for match in mapping.matches]
        self.assertNotIn("sec_performance", match_ids)
        self.assertEqual(["sec_water"], match_ids)
        self.assertEqual(["sec_water"], [section.id for section in selected_sections])
        self.assertTrue(any("Filtered unrelated source matches" in issue for issue in mapping.validation_issues))

    def test_water_injection_mapping_does_not_treat_cement_grout_as_water_injection(self) -> None:
        toc_items = [
            SourceTocItem(
                section_id="sec_grout_quantity",
                title_path=["工程概况", "火区勘查", "作业技术依据"],
                level=3,
                char_count=240,
                snippet="帷幕灌浆钻孔 5994 米、注水泥粉煤灰浆 3.16 万立方米。",
            ),
            SourceTocItem(
                section_id="sec_water",
                title_path=["主要工程项目施工方法", "注水工程施工"],
                level=2,
                char_count=240,
                snippet="裂隙注水采用鸭嘴式喷头，注水压力 0.2~0.3MPa。",
            ),
        ]
        sections = [
            MarkdownSection(
                id="sec_grout_quantity",
                title_path=["工程概况", "火区勘查", "作业技术依据"],
                level=3,
                content="工程量核算依据：帷幕灌浆钻孔 5994 米、注水泥粉煤灰浆 3.16 万立方米。",
                source_file="bid.md",
            ),
            MarkdownSection(
                id="sec_water",
                title_path=["主要工程项目施工方法", "注水工程施工"],
                level=2,
                content="裂隙注水采用鸭嘴式喷头，注水压力 0.2~0.3MPa。",
                source_file="bid.md",
            ),
        ]
        node = TemplateNode(
            id="node_water",
            title="3.2.1 注水工程施工",
            level=3,
            source_rules=["注水施工工艺、压力、流量、裂隙注水控制。"],
        )

        with tempfile.TemporaryDirectory() as tmp:
            mapping, _, _ = map_chapter_sources(
                project_id="project_test",
                profile=ProjectProfile(project_name="煤火治理项目"),
                toc_items=toc_items,
                sections=sections,
                node=node,
                llm=_GroutQuantityNoiseMappingLLM(),
                artifacts=LocalArtifactRepository(Path(tmp)),
                max_matches=4,
            )

        self.assertNotIn("sec_grout_quantity", [match.section_id for match in mapping.matches])


if __name__ == "__main__":
    unittest.main()
