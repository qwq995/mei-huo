from __future__ import annotations

import unittest

from coalplan.application.generated_content_tree import build_generated_content_tree, replace_content_node_markdown
from coalplan.domain.outline import SourceEvidenceSpan, SourceMappingMatch, SourceMappingResult


class GeneratedContentTreeTest(unittest.TestCase):
    def test_builds_tree_and_maps_subsections_to_evidence(self) -> None:
        markdown = """# 注水工程施工

## 主要来源摘要
- 依据 ev_111111111111 和 sec_222222222222 组织。

## 生成正文
### 注水流程
注水施工采用分区、分孔、分阶段实施，控制注水压力和流量。

### 质量控制
施工记录应包含压力、流量、时间等。

## 人工补充需补充
- 【需人工补充：现场复核记录】
"""
        mapping = SourceMappingResult(
            node_id="node_inject",
            matches=[SourceMappingMatch(section_id="sec_222222222222", title_path=["投标", "注水"], confidence=0.9)],
            evidence=[
                SourceEvidenceSpan(
                    evidence_id="ev_111111111111",
                    section_id="sec_222222222222",
                    title_path=["投标", "注水"],
                    matched_terms=["注水", "压力", "流量"],
                    quote="注水施工采用分区、分孔、分阶段实施，控制注水压力和流量。",
                    summary="注水施工流程与参数控制。",
                    confidence=0.9,
                )
            ],
        )

        tree = build_generated_content_tree(node_id="node_inject", title="注水工程施工", markdown=markdown, version_id="ver_1", source_mapping=mapping)

        self.assertEqual("ver_1", tree.version_id)
        self.assertGreaterEqual(len(tree.nodes), 1)
        flat = _flatten(tree.nodes)
        titles = [node.title for node in flat]
        self.assertIn("注水流程", titles)
        source_summary = next(node for node in flat if node.title == "主要来源摘要")
        self.assertEqual("ev_111111111111", source_summary.source_links[0].evidence_id)
        flow = next(node for node in flat if node.title == "注水流程")
        self.assertTrue(any(link.section_id == "sec_222222222222" for link in flow.source_links))
        self.assertEqual("covered", flow.source_status)
        self.assertEqual([], flow.mapping_issues)

    def test_replace_content_node_markdown_creates_updated_markdown(self) -> None:
        markdown = """# 注水工程施工

## 生成正文
### 注水流程
原流程。

### 质量控制
原质量控制。
"""
        tree = build_generated_content_tree(node_id="node_inject", title="注水工程施工", markdown=markdown)
        flow = next(node for node in _flatten(tree.nodes) if node.title == "注水流程")

        updated = replace_content_node_markdown(
            markdown,
            node_id="node_inject",
            content_node_id=flow.id,
            replacement_markdown="### 注水流程\n更新后的注水流程。",
        )

        self.assertIn("更新后的注水流程", updated)
        self.assertNotIn("原流程", updated)
        self.assertIn("原质量控制", updated)

    def test_fallback_tree_carries_source_links_after_edit(self) -> None:
        markdown = """# Chapter

## Body
### Flow
Source-based paragraph.
"""
        mapping = SourceMappingResult(
            node_id="node_flow",
            matches=[SourceMappingMatch(section_id="sec_333333333333", title_path=["Bid", "Flow"], confidence=0.9)],
            evidence=[
                SourceEvidenceSpan(
                    evidence_id="ev_444444444444",
                    section_id="sec_333333333333",
                    title_path=["Bid", "Flow"],
                    matched_terms=["Flow"],
                    quote="Flow source paragraph.",
                    summary="Flow source paragraph.",
                    confidence=0.9,
                )
            ],
        )
        original = build_generated_content_tree(node_id="node_flow", title="Chapter", markdown=markdown, source_mapping=mapping)
        edited = markdown.replace("Source-based paragraph.", "Edited paragraph without explicit evidence id.")

        carried = build_generated_content_tree(node_id="node_flow", title="Chapter", markdown=edited, fallback_tree=original)
        flow = next(node for node in _flatten(carried.nodes) if node.title == "Flow")

        self.assertTrue(flow.source_links)
        self.assertEqual("sec_333333333333", flow.source_links[0].section_id)
        self.assertIn(flow.source_status, {"covered", "weak"})
        self.assertEqual([], flow.mapping_issues)

    def test_marks_factual_subsection_without_source_link_as_missing(self) -> None:
        markdown = """# 注水工程施工

## 生成正文
### 注水流程
注水施工采用分区分孔实施，施工过程中应控制压力、流量和记录。

## 人工补充需补充
- 【需人工补充：现场复核记录】
"""
        tree = build_generated_content_tree(node_id="node_inject", title="注水工程施工", markdown=markdown)
        flat = _flatten(tree.nodes)
        flow = next(node for node in flat if node.title == "注水流程")
        manual = next(node for node in flat if node.title == "人工补充需补充")

        self.assertEqual("missing", flow.source_status)
        self.assertIn("no_source_link_for_factual_content", flow.mapping_issues)
        self.assertEqual("not_required", manual.source_status)
        self.assertEqual([], manual.mapping_issues)


def _flatten(nodes):
    output = []
    for node in nodes:
        output.append(node)
        output.extend(_flatten(node.children))
    return output


if __name__ == "__main__":
    unittest.main()
