import unittest

from coalplan.application.quality_audit import QualityAuditInput, audit_generation_quality, extract_headings


class QualityAuditTest(unittest.TestCase):
    def test_extracts_markdown_and_numbered_headings(self) -> None:
        headings = extract_headings("# 工程概况\n\n1.1 施工方法\n\n二、质量保证措施\n\n普通正文不是标题")

        self.assertIn("工程概况", headings)
        self.assertIn("施工方法", headings)
        self.assertIn("质量保证措施", headings)

    def test_audit_flags_short_generation_and_omitted_source_facts(self) -> None:
        source = "\n".join(
            [
                "# 注水施工",
                "初始注水压力控制在 0.2 - 0.3MPa，钻孔数量为 10 孔。",
                "注水流量 20 m3/min，覆盖厚度 2 m，压实度 95%。",
                "施工工期 30 天，设备 3 台，人员 12 人。",
                "灌浆压力 0.5MPa，孔距 5 m，检查孔 6 孔。",
            ]
        )
        generated = "# 注水施工\n\n## 主要来源摘要\n\n- sec_1\n\n## 生成正文\n\n注水施工应分区组织。\n\n## 人工补充需补充\n\n- 无\n"
        human = "\n".join(["# 注水施工", "1.1 注水范围", "1.2 注水压力", *["人类正文"] * 200])

        report = audit_generation_quality(
            QualityAuditInput(
                project_key="demo",
                generated_markdown=generated,
                source_markdown=source,
                human_markdown=human,
            )
        )

        self.assertLess(report["word_counts"]["generated_vs_human_ratio"], 0.35)
        self.assertGreaterEqual(report["source_facts"]["candidate_count"], 2)
        self.assertEqual(0, report["source_facts"]["absorbed_count"])
        self.assertIn("organization_patterns", report)
        self.assertIsNotNone(report["organization_patterns"]["average_coverage_ratio"])
        self.assertTrue(any("shorter" in issue for issue in report["issues"]))
        self.assertTrue(any("high-value" in issue for issue in report["issues"]))
        actions = {item["action"] for item in report["recommendations"]}
        self.assertIn("increase_detail_budget", actions)
        self.assertIn("repair_outline_coverage", actions)
        self.assertIn("strengthen_evidence_utilization", actions)


if __name__ == "__main__":
    unittest.main()
