import unittest

from coalplan.application.generation_control_plan import (
    build_generation_control_plan,
    build_outline_repair_proposal_nodes,
    build_project_subsection_proposal_nodes,
    build_subsection_proposal_nodes,
    render_generation_control_plan,
)
from coalplan.domain.documents import SourceTocItem
from coalplan.domain.templates import TemplateNode, TemplateTree


class GenerationControlPlanTest(unittest.TestCase):
    def test_generation_control_plan_flags_source_topics_missing_from_outline(self) -> None:
        template = TemplateTree(
            id="demo",
            name="Demo",
            nodes=[
                TemplateNode(
                    id="n1",
                    title="工程概况",
                    level=1,
                    source_rules=["工程概况"],
                    auto_fill=["归纳工程范围"],
                    manual_fill=["合同信息"],
                )
            ],
        )
        toc_items = [
            SourceTocItem(
                section_id="sec_quality",
                title_path=["第六章 保障措施", "质量保障措施"],
                level=2,
                char_count=1000,
            )
        ]

        plan = build_generation_control_plan(template_tree=template, toc_items=toc_items)

        quality = next(item for item in plan.outline_coverage if item.topic == "质量管理")
        self.assertEqual("missing", quality.status)
        self.assertEqual(["sec_quality"], quality.matched_source_section_ids)
        self.assertTrue(any(trigger.action == "expand_subsections" and trigger.title == "质量管理" for trigger in plan.revision_triggers))

    def test_generation_control_plan_requires_subsections_for_dense_craft_nodes(self) -> None:
        template = TemplateTree(
            id="demo",
            name="Demo",
            nodes=[
                TemplateNode(
                    id="grout",
                    title="钻孔与灌浆工程施工",
                    level=2,
                    source_rules=["钻孔与灌浆工程施工"],
                    auto_fill=["归纳施工工艺"],
                    manual_fill=["孔位和灌浆参数"],
                    target_word_count=1800,
                )
            ],
        )

        plan = build_generation_control_plan(template_tree=template, toc_items=[])

        policy = plan.chapter_policies[0]
        self.assertEqual("subsection_required", policy.detail_level)
        self.assertTrue(policy.split_required)
        self.assertGreater(policy.max_source_matches, 8)
        self.assertEqual("craft", policy.writing_pattern_key)
        self.assertIn("craft", policy.writing_pattern_matches)
        self.assertTrue(policy.pattern_required_source_facts)
        self.assertTrue(policy.pattern_prompt_cards)
        self.assertEqual("craft", policy.pattern_prompt_cards[0]["pattern_key"])
        self.assertIn("source_mapping_requirements", policy.pattern_prompt_cards[0])
        self.assertIn("generation_moves", policy.pattern_prompt_cards[0])
        rendered = render_generation_control_plan(plan)
        self.assertIn("pattern_prompt_cards", rendered)
        self.assertIn("craft", rendered)
        self.assertIn("灌浆参数", policy.required_subtopics)

    def test_outline_repair_proposal_nodes_create_missing_topic_nodes(self) -> None:
        template = TemplateTree(id="demo", name="Demo", nodes=[])
        toc_items = [
            SourceTocItem(
                section_id="sec_safety",
                title_path=["第六章 保障措施", "安全保障措施"],
                level=2,
                char_count=1200,
            )
        ]
        plan = build_generation_control_plan(template_tree=template, toc_items=toc_items)

        nodes = build_outline_repair_proposal_nodes(plan=plan, toc_items=toc_items)

        safety = next(node for node in nodes if node["title"] == "安全管理体系及保证措施")
        self.assertEqual("create", safety["__action"])
        self.assertTrue(safety["enabled"])
        self.assertGreaterEqual(safety["target_word_count"], 1200)
        self.assertTrue(any("安全保障措施" in source for source in safety["source_rules"]))

    def test_subsection_proposal_nodes_create_children_for_dense_chapter(self) -> None:
        parent = TemplateNode(
            id="grout",
            title="钻孔与灌浆工程施工",
            level=2,
            source_rules=["钻孔与灌浆工程施工"],
            auto_fill=["归纳施工工艺"],
            manual_fill=["孔位和灌浆参数"],
            target_word_count=1800,
        )
        template = TemplateTree(id="demo", name="Demo", nodes=[parent])
        plan = build_generation_control_plan(template_tree=template, toc_items=[])

        children = build_subsection_proposal_nodes(plan=plan, parent_node=parent)

        self.assertGreaterEqual(len(children), 4)
        self.assertTrue(all(child["__action"] == "create" for child in children))
        self.assertTrue(all(child["parent_id"] == "grout" for child in children))
        self.assertTrue(any(child["title"] == "灌浆参数" for child in children))
        self.assertTrue(any("不得由模型推定" in " ".join(child["special_notes"]) for child in children))

    def test_dense_chapter_subsections_can_come_from_source_toc(self) -> None:
        parent = TemplateNode(
            id="grout",
            title="钻孔与灌浆工程施工",
            level=2,
            source_rules=["钻孔与灌浆工程施工"],
            auto_fill=["归纳施工工艺"],
            manual_fill=["孔位和灌浆参数"],
            target_word_count=1800,
        )
        toc_items = [
            SourceTocItem(
                section_id="sec_parent",
                title_path=["主要施工方案", "钻孔与灌、注浆工程施工"],
                level=2,
                char_count=0,
            ),
            SourceTocItem(
                section_id="sec_curtain",
                title_path=["主要施工方案", "钻孔与灌、注浆工程施工", "帷幕灌浆施工"],
                level=3,
                char_count=2300,
            ),
            SourceTocItem(
                section_id="sec_mud",
                title_path=["主要施工方案", "钻孔与灌、注浆工程施工", "黄泥注浆施工"],
                level=3,
                char_count=1800,
            ),
            SourceTocItem(
                section_id="sec_casing",
                title_path=["主要施工方案", "钻孔与灌、注浆工程施工", "套管施工措施"],
                level=3,
                char_count=900,
            ),
            SourceTocItem(
                section_id="sec_quality",
                title_path=["主要施工方案", "钻孔与灌、注浆工程施工", "灌浆施工质量检查"],
                level=3,
                char_count=1600,
            ),
        ]
        plan = build_generation_control_plan(template_tree=TemplateTree(id="demo", name="Demo", nodes=[parent]), toc_items=toc_items)

        policy = plan.chapter_policies[0]
        children = build_subsection_proposal_nodes(plan=plan, parent_node=parent)

        self.assertTrue(policy.split_required)
        self.assertIn("帷幕灌浆施工", policy.source_subtopics)
        self.assertIn("黄泥注浆施工", policy.required_subtopics)
        self.assertTrue(any(child["title"] == "帷幕灌浆施工" for child in children))
        self.assertTrue(any("帷幕灌浆施工" in " ".join(child["source_rules"]) for child in children))

    def test_project_subsection_proposal_nodes_batch_all_dense_chapters(self) -> None:
        grout = TemplateNode(
            id="grout",
            title="钻孔与灌注浆工程施工",
            level=2,
            source_rules=["钻孔与灌注浆工程施工"],
            auto_fill=["归纳施工工艺"],
            manual_fill=["孔位和灌浆参数"],
            target_word_count=1800,
        )
        water = TemplateNode(
            id="water",
            title="注水工程施工",
            level=2,
            source_rules=["注水工程施工"],
            auto_fill=["归纳注水施工工艺"],
            manual_fill=["注水压力和流量"],
            target_word_count=1600,
        )
        existing = [
            {
                "node_id": "existing_child",
                "parent_id": "grout",
                "title": "帷幕灌浆施工",
                "sort_order": 10,
            }
        ]
        toc_items = [
            SourceTocItem(
                section_id="sec_curtain",
                title_path=["工艺实施", "钻孔与灌注浆工程施工", "帷幕灌浆施工"],
                level=3,
                char_count=1800,
            ),
            SourceTocItem(
                section_id="sec_mud",
                title_path=["工艺实施", "钻孔与灌注浆工程施工", "黄泥注浆施工"],
                level=3,
                char_count=1600,
            ),
            SourceTocItem(
                section_id="sec_water_pressure",
                title_path=["工艺实施", "注水工程施工", "压力流量控制"],
                level=3,
                char_count=1300,
            ),
        ]
        template = TemplateTree(id="demo", name="Demo", nodes=[grout, water])
        plan = build_generation_control_plan(template_tree=template, toc_items=toc_items)

        proposals = build_project_subsection_proposal_nodes(
            plan=plan,
            template_tree=template,
            existing_outline_nodes=existing,
        )

        self.assertTrue(any(node["parent_id"] == "grout" and node["title"] == "黄泥注浆施工" for node in proposals))
        self.assertTrue(any(node["parent_id"] == "water" and node["title"] == "压力流量控制" for node in proposals))
        self.assertFalse(any(node["parent_id"] == "grout" and node["title"] == "帷幕灌浆施工" for node in proposals))

    def test_overview_or_location_nodes_with_craft_source_hints_do_not_force_split(self) -> None:
        node = TemplateNode(
            id="location",
            title="火区位置",
            level=2,
            source_rules=["结合注水、钻孔、灌浆、覆盖封堵施工范围说明火区位置"],
            auto_fill=["归纳火区地理位置、治理范围和边界关系"],
            manual_fill=["坐标和现场复核资料"],
            target_word_count=1200,
        )

        plan = build_generation_control_plan(template_tree=TemplateTree(id="demo", name="Demo", nodes=[node]), toc_items=[])

        policy = plan.chapter_policies[0]
        self.assertFalse(policy.split_required)
        self.assertNotEqual("subsection_required", policy.detail_level)
        self.assertFalse(any(trigger.node_id == "location" and trigger.action == "expand_subsections" for trigger in plan.revision_triggers))


if __name__ == "__main__":
    unittest.main()
