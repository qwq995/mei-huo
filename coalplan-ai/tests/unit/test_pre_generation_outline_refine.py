from __future__ import annotations

import unittest

from coalplan.application.map_sources_to_template import build_chapter_tasks
from coalplan.application.pre_generation_outline_refine import (
    STRUCTURE_ONLY_NOTE,
    build_pre_generation_outline_refine,
)
from coalplan.domain.documents import MarkdownSection
from coalplan.domain.templates import TemplateNode, TemplateTree
from coalplan.infrastructure.retrieval.keyword_retriever import KeywordSourceRetriever


class PreGenerationOutlineRefineTest(unittest.TestCase):
    def test_balanced_coal_fire_refine_splits_core_craft_nodes(self) -> None:
        outline_nodes = [
            _node("water", "注水工程施工", 2, 10, target_word_count=4200),
            _node("grout", "钻孔与灌、注浆工程施工", 2, 20, target_word_count=4900),
            _node("cover", "覆盖封堵工程", 2, 30, target_word_count=3600),
        ]
        tree = TemplateTree(
            id="coal_fire",
            name="coal fire",
            nodes=[TemplateNode(id=item["node_id"], title=item["title"], level=item["level"]) for item in outline_nodes],
        )

        result = build_pre_generation_outline_refine(
            template_tree=tree,
            current_outline_nodes=outline_nodes,
            toc_items=[],
            mode="balanced",
            project_type="coal_fire",
            use_local_corpus=True,
        )

        titles = {item["title"] for item in result["preview_nodes"]}
        self.assertTrue({"压力流量控制", "灌注浆参数控制", "压实与厚度控制"}.issubset(titles))
        self.assertGreaterEqual(result["summary"]["added_node_count"], 19)
        pressure = next(item for item in result["preview_nodes"] if item["title"] == "压力流量控制")
        self.assertEqual("water", pressure["parent_id"])
        self.assertGreaterEqual(pressure["target_word_count"], 550)
        self.assertLessEqual(pressure["target_word_count"], 1200)
        joined_notes = "\n".join(pressure["source_rules"] + pressure["special_notes"])
        self.assertIn(STRUCTURE_ONLY_NOTE, joined_notes)
        self.assertIn("section_id", joined_notes)

    def test_leaf_only_chapter_tasks_after_outline_expansion(self) -> None:
        tree = TemplateTree(
            id="demo",
            name="demo",
            nodes=[
                TemplateNode(
                    id="parent",
                    title="注水工程施工",
                    level=2,
                    source_rules=["source"],
                    auto_fill=["auto"],
                    target_word_count=2000,
                    children=[
                        TemplateNode(
                            id="child",
                            title="压力流量控制",
                            level=3,
                            source_rules=["source"],
                            auto_fill=["auto"],
                            target_word_count=800,
                        )
                    ],
                )
            ],
        )
        sections = [
            MarkdownSection(
                id="s1",
                title_path=["注水工程施工"],
                level=1,
                content="注水压力流量控制和监测记录。",
                source_file="bid.md",
            )
        ]

        tasks = build_chapter_tasks(tree, sections, KeywordSourceRetriever())

        self.assertEqual(["child"], [task.node_id for task in tasks])


def _node(node_id: str, title: str, level: int, sort_order: int, *, target_word_count: int | None = None) -> dict:
    return {
        "node_id": node_id,
        "id": node_id,
        "parent_id": None,
        "title": title,
        "level": level,
        "sort_order": sort_order,
        "enabled": True,
        "source_rules": ["source"],
        "auto_fill": ["auto"],
        "manual_fill": ["manual"],
        "special_notes": [],
        "target_word_count": target_word_count,
    }


if __name__ == "__main__":
    unittest.main()
