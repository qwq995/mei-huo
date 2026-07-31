from __future__ import annotations

import unittest

from coalplan.application.plan_template_outline import (
    apply_outline_to_template_tree,
    build_outline_generation_steps,
    build_template_outline_plan,
    render_outline_markdown,
)
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

    def test_skill_expands_broad_template_node_and_keeps_summaries(self) -> None:
        tree = TemplateTree(
            id="tpl",
            name="template",
            nodes=[
                TemplateNode(
                    id="safety",
                    title="职业健康安全管理",
                    level=1,
                    source_rules=["安全管理", "危险源"],
                    auto_fill=["安全措施"],
                    manual_fill=["危险源清单"],
                )
            ],
        )
        toc = [
            SourceTocItem(
                section_id="sec_safety",
                title_path=["安全管理", "危险源辨识与应急预案"],
                level=2,
                snippet="重大危险源、安全检查和事故应急处置。",
            )
        ]

        outline = build_template_outline_plan(
            profile=ProjectProfile(project_name="水电项目", project_type="水利水电工程", source_section_ids=["sec_safety"]),
            toc_items=toc,
            template_tree=tree,
        )
        dynamic = [node for node in outline.nodes if node.origin in {"skill", "hybrid"}]

        self.assertGreaterEqual(len(dynamic), 5)
        self.assertTrue(all(node.parent_node_id == "safety" for node in dynamic))
        self.assertTrue(all(node.template_anchor_id == "safety" for node in dynamic))
        self.assertTrue(outline.project_summary.overview)
        self.assertTrue(all(node.chapter_summary.overview for node in outline.nodes))

        applied = apply_outline_to_template_tree(tree, outline)
        self.assertGreaterEqual(len(applied.nodes[0].children), 5)
        self.assertEqual(["construction-safety-chapter"], applied.nodes[0].matched_skill_keys)

    def test_template_nodes_do_not_claim_unrelated_profile_sources(self) -> None:
        tree = TemplateTree(
            id="hydro",
            name="水电模板",
            nodes=[
                TemplateNode(
                    id="blast",
                    title="测量放样、钻孔与装药爆破",
                    level=2,
                    source_rules=["钻爆施工"],
                    auto_fill=["工艺流程"],
                    manual_fill=["爆破参数"],
                )
            ],
        )
        toc = [
            SourceTocItem(
                section_id="sec_overview",
                title_path=["工程说明", "项目概况"],
                level=2,
                snippet="本标工程包括泄洪洞工程。",
            )
        ]

        outline = build_template_outline_plan(
            profile=ProjectProfile(project_name="拉哇", source_section_ids=["sec_overview"]),
            toc_items=toc,
            template_tree=tree,
        )

        self.assertEqual([], outline.nodes[0].source_hints)
        self.assertNotEqual("grounded", outline.nodes[0].chapter_summary.coverage_status)
        self.assertFalse(
            any(
                node.source_hints == ["sec_overview"]
                for node in outline.nodes
                if node.chapter_summary.coverage_status == "grounded"
            )
        )

    def test_organization_chapter_does_not_receive_schedule_expansion(self) -> None:
        tree = TemplateTree(
            id="hydro",
            name="水电模板",
            nodes=[
                TemplateNode(
                    id="organization",
                    title="第二章 施工组织机构及人员配置",
                    level=1,
                    source_rules=["项目组织机构"],
                    auto_fill=["部门职责"],
                    manual_fill=["人员名单"],
                )
            ],
        )

        outline = build_template_outline_plan(
            profile=ProjectProfile(project_name="拉哇"),
            toc_items=[],
            template_tree=tree,
        )

        self.assertEqual(["第二章 施工组织机构及人员配置"], [node.title for node in outline.nodes])
        self.assertEqual([], outline.nodes[0].matched_skill_keys)


if __name__ == "__main__":
    unittest.main()
