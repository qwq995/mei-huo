from __future__ import annotations

import unittest

from coalplan.application.chapter_skill_library import (
    build_outline_skill_context,
    load_chapter_skills,
    match_chapter_skills,
    render_chapter_skills_for_prompt,
)
from coalplan.domain.documents import SourceTocItem
from coalplan.domain.templates import TemplateNode, TemplateTree


class ChapterSkillLibraryTest(unittest.TestCase):
    def test_loads_cross_domain_specialized_skills(self) -> None:
        skills = load_chapter_skills()
        self.assertGreaterEqual(len(skills), 10)
        self.assertIn("construction-safety-chapter", skills)
        self.assertIn("construction-craft-chapter", skills)
        self.assertIn("construction-overview-chapter", skills)
        self.assertIn("construction-calculation-drawing-chapter", skills)

    def test_matches_one_primary_skill_by_chapter_title(self) -> None:
        safety = match_chapter_skills(title="职业健康安全管理", context="危险源和应急预案")
        craft = match_chapter_skills(title="地下洞室开挖与支护工程", context="钻爆法施工")
        self.assertEqual("construction-safety-chapter", safety[0].skill_key)
        self.assertEqual("construction-craft-chapter", craft[0].skill_key)

    def test_context_alone_cannot_misclassify_a_generic_chapter(self) -> None:
        matches = match_chapter_skills(title="前言", context="概述质量、安全、环保与进度目标")
        self.assertEqual([], matches)

    def test_safety_monitoring_is_not_occupational_safety_management(self) -> None:
        matches = match_chapter_skills(title="安全监测", context="监测仪器、测点布置与数据采集")
        self.assertEqual([], matches)

    def test_construction_period_water_control_is_not_schedule_management(self) -> None:
        matches = match_chapter_skills(title="施工期水流控制", context="导流、排水和防洪度汛")
        self.assertEqual([], matches)

    def test_skill_context_and_generation_prompt_are_machine_usable(self) -> None:
        node = TemplateNode(
            id="safety",
            title="施工安全管理",
            level=1,
            source_rules=["危险源"],
            matched_skill_keys=["construction-safety-chapter"],
        )
        cards = build_outline_skill_context(
            TemplateTree(id="tpl", name="tpl", nodes=[node]),
            [SourceTocItem(section_id="sec_1", title_path=["安全管理", "应急预案"], level=2)],
        )
        self.assertEqual("construction-safety-chapter", cards[0]["skill_key"])
        self.assertIn("危险源辨识与分级管控", str(cards[0]["outline_expansion"]))
        self.assertIn("skill: construction-safety-chapter", render_chapter_skills_for_prompt(node))


if __name__ == "__main__":
    unittest.main()
