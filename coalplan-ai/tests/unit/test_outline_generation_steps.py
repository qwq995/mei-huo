from __future__ import annotations

import unittest

from coalplan.application.plan_template_outline import build_outline_generation_steps, build_template_outline_plan, render_outline_markdown
from coalplan.domain.documents import SourceTocItem
from coalplan.domain.outline import TemplateOutlineNode, TemplateOutlinePlan
from coalplan.domain.profile import ProjectProfile
from coalplan.domain.templates import TemplateNode, TemplateTree


class OutlineGenerationStepsTest(unittest.TestCase):
    def test_builds_layered_steps_by_level_and_parent(self) -> None:
        tree = TemplateTree(
            id="tpl",
            name="template",
            nodes=[
                TemplateNode(
                    id="root",
                    title="施工组织设计",
                    level=1,
                    children=[
                        TemplateNode(id="overview", title="工程概况", level=2),
                        TemplateNode(id="craft", title="主要施工工艺", level=2),
                    ],
                )
            ],
        )
        outline = TemplateOutlinePlan(
            template_id="tpl",
            nodes=[
                TemplateOutlineNode(node_id="root", title="施工组织设计", level=1, enabled=True),
                TemplateOutlineNode(node_id="overview", title="工程概况", level=2, enabled=True, source_hints=["sec_1"]),
                TemplateOutlineNode(node_id="craft", title="主要施工工艺", level=2, enabled=True, source_hints=["sec_2"]),
            ],
        )

        steps = build_outline_generation_steps(outline, tree)

        self.assertEqual(["outline_level_1_root", "outline_level_2_root"], [step.step_id for step in steps])
        self.assertEqual(["root"], steps[0].node_ids)
        self.assertEqual(["overview", "craft"], steps[1].node_ids)
        self.assertEqual(["sec_1", "sec_2"], steps[1].source_section_ids)

    def test_render_outline_markdown_includes_layered_steps(self) -> None:
        outline = TemplateOutlinePlan(
            template_id="tpl",
            nodes=[TemplateOutlineNode(node_id="overview", title="工程概况", level=2, enabled=True)],
        )
        outline.generation_steps = [
            build_outline_generation_steps(
                outline,
                TemplateTree(id="tpl", name="template", nodes=[TemplateNode(id="overview", title="工程概况", level=2)]),
            )[0]
        ]

        markdown = render_outline_markdown(outline)

        self.assertIn("## 分层生成步骤", markdown)
        self.assertIn("outline_level_2_root", markdown)
        self.assertIn("[主要来源]", markdown)

    def test_template_outline_plan_has_template_source_and_steps(self) -> None:
        tree = TemplateTree(
            id="tpl",
            name="template",
            nodes=[TemplateNode(id="overview", title="工程概况", level=2, source_rules=["工程概况"], auto_fill=["归纳"], manual_fill=["合同"])],
        )
        outline = build_template_outline_plan(
            profile=ProjectProfile(project_name="demo", source_section_ids=["sec_1"]),
            toc_items=[SourceTocItem(section_id="sec_1", title_path=["工程概况"], level=1)],
            template_tree=tree,
        )

        self.assertEqual("template", outline.plan_source)
        self.assertEqual(1, len(outline.generation_steps))
        self.assertEqual(["sec_1"], outline.generation_steps[0].source_section_ids)


if __name__ == "__main__":
    unittest.main()
