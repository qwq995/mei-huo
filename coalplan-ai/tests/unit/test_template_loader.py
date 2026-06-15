from __future__ import annotations

import unittest
from pathlib import Path

from coalplan.domain.templates import iter_template_nodes
from coalplan.infrastructure.templates.markdown_template_loader import MarkdownTemplateLoader


class TemplateLoaderTest(unittest.TestCase):
    def test_loads_coal_fire_tree_and_four_modules(self) -> None:
        template_dir = Path(__file__).resolve().parents[2] / "src" / "coalplan" / "assets" / "templates"
        tree = MarkdownTemplateLoader(template_dir).load("coal_fire")
        nodes = iter_template_nodes(tree.nodes)

        self.assertGreaterEqual(len(nodes), 8)
        fire_position = next(node for node in nodes if node.title == "1.1.1 火区位置")
        self.assertTrue(fire_position.source_rules)
        self.assertTrue(fire_position.auto_fill)
        self.assertTrue(fire_position.manual_fill)
        self.assertTrue(fire_position.special_notes)

        raw_text = (template_dir / "coal_fire_template.md").read_text(encoding="utf-8-sig")
        for old_module in ("[来源]", "[需补充]", "[人工补充]"):
            self.assertNotIn(old_module, raw_text)


if __name__ == "__main__":
    unittest.main()
