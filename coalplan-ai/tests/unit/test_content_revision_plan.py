from __future__ import annotations

import unittest

from coalplan.application.content_revision_plan import build_content_revision_plan, render_content_revision_plan_markdown
from coalplan.application.generated_content_tree import build_generated_content_tree
from coalplan.domain.generation_control import EvidenceUtilizationAudit, RequiredSourceFact
from coalplan.domain.outline import SourceEvidenceSpan, SourceMappingMatch, SourceMappingResult


class ContentRevisionPlanTest(unittest.TestCase):
    def test_missing_factual_subsection_routes_to_remap(self) -> None:
        tree = build_generated_content_tree(
            node_id="node_inject",
            title="注水工程施工",
            markdown="""# 注水工程施工

## 生成正文
### 注水流程
注水施工采用分区分孔实施，施工过程中应控制压力、流量和记录。
""",
        )

        plan = build_content_revision_plan(tree)
        item = next(item for item in plan.items if item.title == "注水流程")

        self.assertEqual("blocked", plan.status)
        self.assertEqual("remap_sources", item.action)
        self.assertTrue(item.requires_llm)
        self.assertEqual(1, plan.metrics["missing_source_count"])

    def test_source_linked_short_subsection_routes_to_rewrite(self) -> None:
        mapping = SourceMappingResult(
            node_id="node_quality",
            matches=[SourceMappingMatch(section_id="sec_123456789abc", title_path=["投标", "质量"], confidence=0.9)],
            evidence=[
                SourceEvidenceSpan(
                    evidence_id="ev_123456789abc",
                    section_id="sec_123456789abc",
                    title_path=["投标", "质量"],
                    matched_terms=["质量", "检查"],
                    quote="质量检查应按工序执行。",
                    summary="质量检查要求。",
                    confidence=0.9,
                )
            ],
        )
        tree = build_generated_content_tree(
            node_id="node_quality",
            title="质量控制",
            markdown="""# 质量控制

## 生成正文
### 检查控制
依据 ev_123456789abc，按工序检查。
""",
            source_mapping=mapping,
        )

        plan = build_content_revision_plan(tree, minimum_subsection_words=40)
        item = next(item for item in plan.items if item.title == "检查控制")

        self.assertEqual("warning", plan.status)
        self.assertEqual("rewrite_subsection", item.action)
        self.assertTrue(item.requires_llm)
        self.assertIn("sec_123456789abc", item.source_section_ids)

    def test_manual_placeholder_routes_to_human_input(self) -> None:
        tree = build_generated_content_tree(
            node_id="node_manual",
            title="设备配置",
            markdown="""# 设备配置

## 生成正文
### 主要设备
【需人工补充：主要机械设备型号、数量和进场时间。】
""",
        )

        plan = build_content_revision_plan(tree)
        item = next(item for item in plan.items if item.title == "主要设备")

        self.assertEqual("request_human_input", item.action)
        self.assertTrue(item.requires_user_confirmation)
        self.assertIn("Content Revision Plan", render_content_revision_plan_markdown(plan))

    def test_omitted_required_fact_routes_matching_subsection_to_rewrite(self) -> None:
        mapping = SourceMappingResult(
            node_id="node_inject",
            matches=[SourceMappingMatch(section_id="sec_abcdef123456", title_path=["bid", "water"], confidence=0.9)],
            evidence=[
                SourceEvidenceSpan(
                    evidence_id="ev_abcdef123456",
                    section_id="sec_abcdef123456",
                    title_path=["bid", "water"],
                    matched_terms=["裂隙注水", "0.2", "0.3MPa"],
                    quote="裂隙注水采用鸭嘴式喷头，注水压力0.2～0.3MPa。",
                    summary="裂隙注水压力与喷头要求。",
                    confidence=0.9,
                )
            ],
        )
        tree = build_generated_content_tree(
            node_id="node_inject",
            title="注水工程施工",
            markdown="""# 注水工程施工

## 鐢熸垚姝ｆ枃
### 裂隙注水
依据 ev_abcdef123456，裂隙注水应分散、间歇实施。
""",
            source_mapping=mapping,
        )
        audit = EvidenceUtilizationAudit(
            node_id="node_inject",
            title="注水工程施工",
            evidence_count=1,
            required_source_facts=[
                RequiredSourceFact(
                    fact_id="ev_abcdef123456:fact_1",
                    evidence_id="ev_abcdef123456",
                    section_id="sec_abcdef123456",
                    fact_type="parameter",
                    text="裂隙注水采用鸭嘴式喷头，注水压力0.2～0.3MPa。",
                    tokens=["鸭嘴式喷头", "0.2", "0.3MPa"],
                )
            ],
            omitted_required_fact_ids=["ev_abcdef123456:fact_1"],
            coverage_ratio=0.2,
        )

        plan = build_content_revision_plan(tree, evidence_audit=audit)
        item = next(item for item in plan.items if item.title == "裂隙注水")

        self.assertEqual("warning", plan.status)
        self.assertEqual("rewrite_subsection", item.action)
        self.assertTrue(item.requires_llm)
        self.assertIn("ev_abcdef123456", item.evidence_ids)
        self.assertIn("sec_abcdef123456", item.source_section_ids)
        self.assertIn("omitted_required_source_facts", item.reason)
        self.assertTrue(any("鸭嘴式喷头" in step for step in item.next_steps))
        self.assertEqual(1, plan.metrics["evidence_targeted_rewrite_count"])


if __name__ == "__main__":
    unittest.main()
