from __future__ import annotations

import unittest

from coalplan.application.evidence_utilization import audit_evidence_utilization
from coalplan.domain.outline import SourceEvidenceSpan
from coalplan.domain.templates import TemplateNode


class EvidenceUtilizationTest(unittest.TestCase):
    def test_detects_manual_placeholder_supported_by_source_evidence(self) -> None:
        node = TemplateNode(
            id="overview",
            title="工程概况",
            level=2,
            manual_fill=["主要工程量清单", "合同工期要求"],
        )
        evidence = [
            SourceEvidenceSpan(
                evidence_id="ev_1",
                section_id="sec_scope",
                title_path=["投标文件", "工程概况"],
                quote="本合同主要工程量为：土方明挖9.3万m3，石方洞挖196.2万m3。",
                summary="主要工程量",
                matched_terms=["工程量", "土方明挖", "石方洞挖"],
                confidence=0.9,
            ),
            SourceEvidenceSpan(
                evidence_id="ev_2",
                section_id="sec_schedule",
                title_path=["投标文件", "工期要求"],
                quote="合同计划开工时间为2021年6月15日，完工时间为2027年7月31日。",
                summary="合同工期",
                matched_terms=["开工", "完工", "工期"],
                confidence=0.9,
            ),
        ]
        markdown = "\n".join(
            [
                "# 工程概况",
                "## 主要来源摘要",
                "- sec_scope",
                "## 生成正文",
                "本节依据投标文件概述工程建设内容。",
                "## 人工补充需补充",
                "- 【需人工补充：主要工程量清单】",
                "- 【需人工补充：合同工期要求】",
            ]
        )

        audit = audit_evidence_utilization(node=node, markdown=markdown, evidence=evidence)

        self.assertIn("主要工程量清单", audit.manual_items_with_source_support)
        self.assertIn("合同工期要求", audit.manual_items_with_source_support)
        self.assertIn("manual_item_has_source_support", {issue.code for issue in audit.issues})

    def test_generic_manual_section_does_not_count_as_supported_placeholder(self) -> None:
        node = TemplateNode(
            id="overview",
            title="工程概况",
            level=2,
            manual_fill=["合同工期要求"],
        )
        evidence = [
            SourceEvidenceSpan(
                evidence_id="ev_schedule",
                section_id="sec_schedule",
                title_path=["投标文件", "工期要求"],
                quote="合同计划开工时间为2021年4月15日，完工时间为2027年10月31日。",
                summary="合同工期",
                matched_terms=["开工", "完工", "工期"],
                confidence=0.9,
            )
        ]
        markdown = "\n".join(
            [
                "# 工程概况",
                "## 主要来源摘要",
                "- evidence_id: ev_schedule；section_id: sec_schedule",
                "## 生成正文",
                "本工程合同计划开工时间为2021年4月15日，完工时间为2027年10月31日。",
                "## 人工补充需补充",
                "- 无需人工补充；真实缺失项由模型依据来源证据判断。",
            ]
        )

        audit = audit_evidence_utilization(node=node, markdown=markdown, evidence=evidence)

        self.assertEqual([], audit.manual_items_with_source_support)
        self.assertNotIn("manual_item_has_source_support", {issue.code for issue in audit.issues})

    def test_marks_evidence_used_when_specific_facts_appear_in_markdown(self) -> None:
        node = TemplateNode(id="overview", title="工程概况", level=2)
        evidence = [
            SourceEvidenceSpan(
                evidence_id="ev_1",
                section_id="sec_scope",
                title_path=["投标文件", "工程概况"],
                quote="土方明挖9.3万m3，石方洞挖196.2万m3。",
                summary="工程量",
                matched_terms=["工程量"],
            )
        ]
        markdown = "\n".join(
            [
                "# 工程概况",
                "## 主要来源摘要",
                "- evidence_id: ev_1；section_id: sec_scope；原文列明土方明挖9.3万m3。",
                "## 生成正文",
                "本工程土方明挖9.3万m3，石方洞挖196.2万m3。",
                "## 人工补充需补充",
                "- 无。",
            ]
        )

        audit = audit_evidence_utilization(node=node, markdown=markdown, evidence=evidence)

        self.assertEqual(["ev_1"], audit.used_evidence_ids)
        self.assertEqual(1.0, audit.coverage_ratio)
        self.assertFalse(audit.issues)

    def test_detects_required_source_facts_omitted_from_generated_body(self) -> None:
        node = TemplateNode(id="water", title="注水工程施工", level=3)
        evidence = [
            SourceEvidenceSpan(
                evidence_id="ev_pressure",
                section_id="sec_water",
                title_path=["投标文件", "注水工程施工", "地面注水施工"],
                quote=(
                    "先用0.5 - 0.8MPa高压风枪吹扫裂隙内浮煤及碎屑，"
                    "吹扫5 - 15分钟后，以0.3 - 0.5m³/min流量清水冲洗3 - 5分钟。"
                ),
                summary="裂隙注水预处理压力、流量和时间控制要求。",
                matched_terms=["注水", "压力", "流量"],
                confidence=0.95,
            )
        ]
        markdown = "\n".join(
            [
                "# 注水工程施工",
                "## 主要来源摘要",
                "- evidence_id: ev_pressure；section_id: sec_water；原文列明裂隙注水预处理参数。",
                "## 生成正文",
                "裂隙注水前应对裂隙进行吹扫、冲洗和封堵，并做好过程监测记录。",
                "## 人工补充需补充",
                "- 无。",
            ]
        )

        audit = audit_evidence_utilization(node=node, markdown=markdown, evidence=evidence)

        self.assertTrue(audit.required_source_facts)
        self.assertTrue(audit.omitted_required_fact_ids)
        self.assertEqual("omitted_required_source_facts", audit.issues[0].code)
        self.assertIn("0.5 - 0.8MPa", audit.issues[0].terms[0])

    def test_required_source_facts_pass_when_body_preserves_parameters(self) -> None:
        node = TemplateNode(id="water", title="注水工程施工", level=3)
        evidence = [
            SourceEvidenceSpan(
                evidence_id="ev_pressure",
                section_id="sec_water",
                title_path=["投标文件", "注水工程施工", "地面注水施工"],
                quote="初始注水压力控制在0.2 - 0.3MPa，流量控制在0.1 - 0.2m³/min。",
                summary="裂隙注水压力和流量控制。",
                matched_terms=["注水", "压力", "流量"],
                confidence=0.95,
            )
        ]
        markdown = "\n".join(
            [
                "# 注水工程施工",
                "## 主要来源摘要",
                "- evidence_id: ev_pressure；section_id: sec_water。",
                "## 生成正文",
                "裂隙注水作业初始注水压力控制在0.2 - 0.3MPa，流量控制在0.1 - 0.2m³/min。",
                "## 人工补充需补充",
                "- 无。",
            ]
        )

        audit = audit_evidence_utilization(node=node, markdown=markdown, evidence=evidence)

        self.assertFalse(audit.omitted_required_fact_ids)
        self.assertFalse([issue for issue in audit.issues if issue.code == "omitted_required_source_facts"])

    def test_location_node_does_not_require_unrelated_craft_quantities(self) -> None:
        node = TemplateNode(
            id="location",
            title="1.1.1 火区位置",
            level=4,
            source_rules=["项目地理位置、行政区划、火区边界、坐标和治理范围。"],
            manual_fill=["火区中心坐标、治理面积、治理边界。"],
        )
        evidence = [
            SourceEvidenceSpan(
                evidence_id="ev_location",
                section_id="sec_location",
                title_path=["工程概况", "项目地理位置"],
                quote="北一火区中心地理位置坐标为东经 106°08′40″，北纬 39°06′24″，面积为 76067.92m2。",
                summary="火区位置、坐标和面积。",
                matched_terms=["位置", "坐标", "面积"],
                confidence=0.9,
            ),
            SourceEvidenceSpan(
                evidence_id="ev_quantities",
                section_id="sec_quantities",
                title_path=["工程概况", "项目范围与治理内容", "具体施工内容"],
                quote="帷幕灌浆工程：帷幕灌浆钻孔 5994 米、注水泥粉煤灰浆 3.16 万立方米。降温注水工程：降温注水 3.8 万立方米。",
                summary="灌浆、钻孔和注水工程量。",
                matched_terms=["灌浆", "钻孔", "注水", "工程量"],
                confidence=0.9,
            ),
        ]
        markdown = "\n".join(
            [
                "# 1.1.1 火区位置",
                "## 主要来源摘要",
                "- evidence_id: ev_location；section_id: sec_location。",
                "## 生成正文",
                "北一火区中心地理位置坐标为东经 106°08′40″，北纬 39°06′24″，面积为 76067.92m2。",
                "## 人工补充需补充",
                "- 无。",
            ]
        )

        audit = audit_evidence_utilization(node=node, markdown=markdown, evidence=evidence)

        self.assertNotIn("ev_quantities", audit.unused_high_value_evidence_ids)
        self.assertFalse([issue for issue in audit.issues if issue.code == "omitted_required_source_facts"])

    def test_quantity_node_still_requires_craft_quantities(self) -> None:
        node = TemplateNode(
            id="quantities",
            title="第三节 灭火工程量及进度安排",
            level=2,
            source_rules=["主要工程量、施工内容和进度安排。"],
        )
        evidence = [
            SourceEvidenceSpan(
                evidence_id="ev_quantities",
                section_id="sec_quantities",
                title_path=["工程概况", "项目范围与治理内容", "具体施工内容"],
                quote="帷幕灌浆工程：帷幕灌浆钻孔 5994 米、注水泥粉煤灰浆 3.16 万立方米。降温注水工程：降温注水 3.8 万立方米。",
                summary="灌浆、钻孔和注水工程量。",
                matched_terms=["工程量", "灌浆", "注水"],
                confidence=0.9,
            )
        ]
        markdown = "\n".join(
            [
                "# 第三节 灭火工程量及进度安排",
                "## 主要来源摘要",
                "- evidence_id: ev_quantities；section_id: sec_quantities。",
                "## 生成正文",
                "本节根据投标文件组织灭火工程量和进度安排。",
                "## 人工补充需补充",
                "- 无。",
            ]
        )

        audit = audit_evidence_utilization(node=node, markdown=markdown, evidence=evidence)

        self.assertIn("omitted_required_source_facts", {issue.code for issue in audit.issues})

    def test_detects_quality_feedback_required_fact_omitted_from_body_and_manual_block(self) -> None:
        node = TemplateNode(id="quality", title="质量控制依据", level=2)
        evidence = [
            SourceEvidenceSpan(
                evidence_id="ev_standard",
                section_id="sec_standard",
                title_path=["投标文件", "质量控制目标和法律法规", "法律法规及技术标准"],
                quote="施工过程中应遵守GB50194-2014《施工现场临时用电安全技术规范》。",
                summary="临时用电安全技术标准包含GB50194-2014。",
                matched_terms=["质量", "技术标准"],
                confidence=0.9,
            )
        ]
        markdown = "\n".join(
            [
                "# 质量控制依据",
                "## 主要来源摘要",
                "- evidence_id: ev_standard；section_id: sec_standard。",
                "## 生成正文",
                "本节依据投标文件组织质量、安全和施工记录控制。",
                "## 人工补充需补充",
                "- 无。",
            ]
        )

        audit = audit_evidence_utilization(
            node=node,
            markdown=markdown,
            evidence=evidence,
            required_fact_hints=["GB50194-2014 [prompted_but_omitted -> regenerate]"],
        )

        self.assertEqual(["GB50194-2014"], audit.feedback_required_fact_hints)
        self.assertEqual(["GB50194-2014"], audit.omitted_feedback_fact_hints)
        self.assertIn("omitted_feedback_required_facts", {issue.code for issue in audit.issues})

    def test_quality_feedback_required_fact_can_be_explained_in_manual_block(self) -> None:
        node = TemplateNode(id="quality", title="质量控制依据", level=2)
        markdown = "\n".join(
            [
                "# 质量控制依据",
                "## 主要来源摘要",
                "- sec_standard。",
                "## 生成正文",
                "本节依据投标文件组织质量、安全和施工记录控制。",
                "## 人工补充需补充",
                "- 【需人工补充：GB50194-2014 属于临时用电专项章节，本节不展开引用。】",
            ]
        )

        audit = audit_evidence_utilization(
            node=node,
            markdown=markdown,
            evidence=[],
            required_fact_hints=["GB50194-2014"],
        )

        self.assertEqual([], audit.omitted_feedback_fact_hints)
        self.assertNotIn("omitted_feedback_required_facts", {issue.code for issue in audit.issues})


if __name__ == "__main__":
    unittest.main()
