import unittest

from coalplan.application.chapter_writing_guidance import guidance_for_node, render_writing_guidance
from coalplan.domain.templates import TemplateNode


class ChapterWritingGuidanceTest(unittest.TestCase):
    def test_craft_guidance_for_grouting_chapter(self) -> None:
        guidance = guidance_for_node(
            TemplateNode(
                id="grout",
                title="钻孔与灌浆工程施工",
                level=2,
                source_rules=["钻孔与灌浆"],
                auto_fill=[],
                manual_fill=[],
            )
        )

        rendered = render_writing_guidance(guidance)
        self.assertEqual("工艺类章节", guidance.category)
        self.assertIn("工艺流程", rendered)
        self.assertIn("灌浆控制", rendered)
        self.assertIn("主要工艺", rendered)

    def test_safety_guidance_for_emergency_chapter(self) -> None:
        guidance = guidance_for_node(
            TemplateNode(
                id="safety",
                title="应急预案及安全保证措施",
                level=2,
                source_rules=["安全管理", "应急预案"],
                auto_fill=[],
                manual_fill=[],
            )
        )

        rendered = render_writing_guidance(guidance)
        self.assertEqual("安全/应急类章节", guidance.category)
        self.assertIn("危险源辨识", rendered)
        self.assertIn("应急联系人", rendered)


if __name__ == "__main__":
    unittest.main()
