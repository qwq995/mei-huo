from __future__ import annotations

import unittest

from coalplan.application.chapter_generation_plan import (
    default_chapter_generation_plan,
    render_chapter_plan_for_prompt,
    validate_saved_plan,
)
from coalplan.application.chapter_writing_units import plan_chapter_writing_units
from coalplan.application.generate_chapter import build_generation_metadata
from coalplan.application.generation_control_plan import _chapter_policy
from coalplan.application.run_generation_pipeline import _merge_partial_generated_body
from coalplan.domain.generation import ChapterTask
from coalplan.domain.generation_context import WritingUnitSpec
from coalplan.domain.templates import TemplateNode


class ChapterGenerationPlanTests(unittest.TestCase):
    def test_natural_condition_plan_filters_cross_chapter_safety_topics(self) -> None:
        node = TemplateNode(id="weather", title="1.2 水文气象条件", level=2)
        unit = WritingUnitSpec(
            unit_id="legacy",
            title="水文气象条件",
            objective="展开雨季施工、安全组织体系和危险源辨识",
            target_word_count=700,
            writing_topics=["雨季施工", "安全目标", "安全组织体系和岗位职责", "危险源辨识"],
            evidence_terms=[],
            content_functions=["安全环保"],
            sequence=1,
        )

        plan = default_chapter_generation_plan(node=node, writing_units=[unit])

        self.assertEqual(3, len(plan.items))
        self.assertNotIn("安全组织体系", " ".join(item.title + " " + " ".join(item.key_points) for item in plan.items))
        self.assertTrue(any("完整安全组织体系" in item for item in plan.out_of_scope))

    def test_confirmed_saved_plan_controls_writing_units(self) -> None:
        node = TemplateNode(id="weather", title="1.2 水文气象条件", level=2, target_word_count=900)
        default = default_chapter_generation_plan(
            node=node,
            writing_units=[
                WritingUnitSpec(
                    unit_id="legacy",
                    title="旧单元",
                    objective="旧目标",
                    target_word_count=700,
                    writing_topics=["安全目标"],
                    evidence_terms=[],
                    content_functions=["安全环保"],
                    sequence=1,
                )
            ],
        )
        saved = validate_saved_plan(
            {**default.model_dump(), "status": "confirmed"},
            node_id=node.id,
            title=node.title,
        )
        node.chapter_summary = {"generation_plan": saved.model_dump()}

        units = plan_chapter_writing_units(node=node, policy=None)

        self.assertEqual([item.title for item in saved.items], [unit.title for unit in units])
        self.assertNotIn("安全目标", " ".join(topic for unit in units for topic in unit.writing_topics))
        prompt = render_chapter_plan_for_prompt(saved)
        self.assertIn("生成范围硬约束", prompt)
        self.assertIn("不得新增提纲之外", prompt)

    def test_confirmed_plan_requires_an_enabled_item(self) -> None:
        node = TemplateNode(id="overview", title="工程概况", level=2)
        default = default_chapter_generation_plan(node=node, writing_units=[])
        payload = default.model_dump()
        payload["status"] = "confirmed"
        payload["items"] = [{**item, "enabled": False} for item in payload["items"]]

        with self.assertRaisesRegex(ValueError, "至少保留一个"):
            validate_saved_plan(payload, node_id=node.id, title=node.title)

    def test_confirmed_plan_disables_legacy_pattern_and_skill_controls(self) -> None:
        node = TemplateNode(
            id="weather",
            title="1.2 水文气象条件",
            level=2,
            auto_fill=["补充安全目标、施工措施和应急体系"],
            matched_skill_keys=["construction-safety-chapter"],
        )
        plan = default_chapter_generation_plan(node=node, writing_units=[])
        plan.status = "confirmed"
        node.chapter_summary = {"generation_plan": plan.model_dump()}

        policy = _chapter_policy(node, [])
        metadata = build_generation_metadata(
            node=node,
            task=ChapterTask(node_id=node.id, title=node.title),
            generation_policy=policy,
        )

        self.assertEqual([], policy.writing_pattern_matches)
        self.assertEqual([], policy.pattern_prompt_cards)
        self.assertEqual([], metadata["selected_pattern_keys"])
        self.assertEqual([], metadata["matched_skill_keys"])
        self.assertIsNone(metadata["writing_guidance"])

    def test_partial_ai_edit_preserves_untouched_plan_sections(self) -> None:
        base = "### 基础资料\n\n旧基础。\n\n### 施工影响\n\n旧影响。\n\n### 资料缺口\n\n旧缺口。"
        revised = "### 施工影响\n\n新影响。"
        plan = {"items": [{"title": title, "enabled": True} for title in ("基础资料", "施工影响", "资料缺口")]}

        merged = _merge_partial_generated_body(base, revised, plan)

        self.assertIn("旧基础", merged)
        self.assertIn("新影响", merged)
        self.assertIn("旧缺口", merged)
        self.assertNotIn("旧影响", merged)


if __name__ == "__main__":
    unittest.main()
