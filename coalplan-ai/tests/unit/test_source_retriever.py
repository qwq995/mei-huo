from __future__ import annotations

import unittest
from pathlib import Path

from coalplan.domain.templates import iter_template_nodes
from coalplan.infrastructure.markdown.parser import MarkdownDocumentParser
from coalplan.infrastructure.retrieval.keyword_retriever import KeywordSourceRetriever
from coalplan.infrastructure.templates.markdown_template_loader import MarkdownTemplateLoader


class SourceRetrieverTest(unittest.TestCase):
    def test_core_coal_fire_nodes_match_bid_sections(self) -> None:
        repo_root = Path(__file__).resolve().parents[2]
        assets = repo_root / "src" / "coalplan" / "assets"
        template = MarkdownTemplateLoader(assets / "templates").load("coal_fire")
        sample = (assets / "samples" / "coal_fire_bid.normalized.md").read_text(encoding="utf-8-sig")
        sections = MarkdownDocumentParser().split_sections(sample, source_file="bid.md")
        nodes = {node.title: node for node in iter_template_nodes(template.nodes)}
        retriever = KeywordSourceRetriever()

        expectations = {
            "1.1.1 火区位置": "项目地理位置与交通条件",
            "1.1.2 火区交通情况": "项目地理位置与交通条件",
            "第二节 火区现状": "火区勘查",
            "3.2.1 注水工程施工": "注水工程施工",
            "3.2.2 钻孔与灌、注浆工程施工": "钻孔与灌、注浆工程施工",
            "3.2.3 覆盖封堵工程": "覆盖封堵工程",
            "第七章 预期提交灭火工程施工成果": "灭火效果评价",
        }

        for node_title, expected_source_title in expectations.items():
            with self.subTest(node=node_title):
                matches = retriever.retrieve(nodes[node_title], sections, limit=4)
                joined_paths = [" > ".join(match.title_path) for match in matches]
                self.assertTrue(
                    any(expected_source_title in path for path in joined_paths),
                    f"{node_title} did not match {expected_source_title}; got {joined_paths}",
                )


if __name__ == "__main__":
    unittest.main()
