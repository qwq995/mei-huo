import unittest

from coalplan.application.organization_pattern_audit import (
    audit_document_organization,
    audit_pattern_organization,
    render_organization_audit_markdown,
)


class OrganizationPatternAuditTest(unittest.TestCase):
    def test_craft_chapter_missing_expected_points_triggers_subsection_expansion(self) -> None:
        generated = "# 注水工程施工\n\n## 生成正文\n\n本节介绍注水施工方法，按分区组织实施。"
        applicability = "注水工程施工 工艺流程 注水压力 流量 质量检查 安全环保"

        audit = audit_pattern_organization(generated, pattern_key="craft", applicability_text=applicability)

        self.assertTrue(audit.applicable)
        self.assertLess(audit.coverage_ratio or 0, 0.65)
        self.assertEqual("expand_subsections", audit.suggested_action)
        self.assertIn("工艺流程和施工程序", audit.missing_points)
        self.assertIn("质量检查、试验和验收", audit.missing_points)

    def test_safety_chapter_with_control_loop_passes_organization_audit(self) -> None:
        generated = "\n".join(
            [
                "# 安全保证措施",
                "## 生成正文",
                "本工程安全目标为杜绝较大及以上安全事故。",
                "项目部建立安全组织和安全保证体系，明确项目经理、安全员、班组长职责。",
                "施工前开展危险源辨识，重点控制高处作业、临时用电、机械伤害和火灾风险。",
                "现场落实安全措施、防护、警戒、教育培训、技术交底和日常检查。",
                "对隐患检查结果建立整改、复查和奖惩闭环。",
                "编制应急预案，落实应急响应、救援物资、值班和演练。",
            ]
        )

        audit = audit_pattern_organization(generated, pattern_key="safety")

        self.assertTrue(audit.applicable)
        self.assertGreaterEqual(audit.coverage_ratio or 0, 0.8)
        self.assertEqual("accept", audit.suggested_action)

    def test_document_audit_renders_reviewable_pattern_summary(self) -> None:
        generated = "# 钻孔与灌浆工程施工\n\n## 生成正文\n\n施工对象为帷幕灌浆，写明施工方法和压力控制。"
        source = "钻孔与灌浆 工艺流程 质量检查 验收 安全 环保 设备 材料"

        report = audit_document_organization(generated, source_markdown=source, pattern_keys=["craft", "quality"])
        markdown = render_organization_audit_markdown(report)

        self.assertGreaterEqual(report.applicable_pattern_count, 1)
        self.assertIn("Organization Pattern Audit", markdown)
        self.assertIn("craft", markdown)

    def test_source_summary_terms_do_not_count_as_generated_body_organization(self) -> None:
        generated = "\n".join(
            [
                "# 钻孔与灌浆工程施工",
                "## 主要来源摘要",
                "来源包含工艺流程、机械设备、质量检查、验收、安全环保、控制参数。",
                "## 生成正文",
                "本节围绕钻孔与灌浆工程施工组织实施。",
                "## 人工补充需补充",
                "- 无",
            ]
        )

        audit = audit_pattern_organization(
            generated,
            pattern_key="craft",
            applicability_text="钻孔与灌浆 工艺流程 机械设备 质量检查 验收 安全环保 控制参数",
        )

        self.assertLess(audit.coverage_ratio or 0, 0.5)
        self.assertIn("工艺流程和施工程序", audit.missing_points)


if __name__ == "__main__":
    unittest.main()
