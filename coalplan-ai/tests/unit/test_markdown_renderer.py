from __future__ import annotations

import unittest

from coalplan.domain.generation import ChapterDraft
from coalplan.domain.templates import TemplateNode
from coalplan.infrastructure.markdown.renderer import merge_template_tree_markdowns


class MarkdownRendererTest(unittest.TestCase):
    def test_refined_tree_merge_uses_tree_depth_instead_of_template_level(self) -> None:
        nodes = [
            TemplateNode(
                id="root",
                title="施工方法",
                level=4,
                children=[
                    TemplateNode(
                        id="child",
                        title="压力流量控制",
                        level=6,
                        children=[],
                    )
                ],
            )
        ]
        drafts = [
            ChapterDraft(
                node_id="child",
                title="压力流量控制",
                markdown="\n".join(
                    [
                        "# 压力流量控制",
                        "",
                        "## 主要来源摘要",
                        "- section_id: sec_1",
                        "",
                        "## 生成正文",
                        "### 控制要求",
                        "按来源证据组织施工控制。",
                        "",
                        "## 人工补充需补充",
                        "- 【需人工补充：现场记录】",
                    ]
                ),
            )
        ]

        merged = merge_template_tree_markdowns("煤火治理施组", nodes, drafts)

        self.assertIn("## 施工方法", merged)
        self.assertIn("### 压力流量控制", merged)
        self.assertIn("##### 控制要求", merged)
        self.assertNotIn("主要来源摘要", merged)
        self.assertNotIn("人工补充需补充", merged)
        self.assertNotIn("######", merged)


if __name__ == "__main__":
    unittest.main()
