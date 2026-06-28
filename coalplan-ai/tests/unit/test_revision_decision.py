import unittest

from coalplan.application.revision_decision import build_revision_decision
from coalplan.application.run_generation_pipeline import _render_revision_context, _revision_context_required_fact_hints
from coalplan.domain.enums import TaskStatus
from coalplan.domain.generation import ChapterDraft, ChapterTask, SourceMatch
from coalplan.domain.generation_control import ChapterGenerationPolicy, EvidenceUtilizationAudit, RequiredSourceFact
from coalplan.domain.outline import SourceMappingResult
from coalplan.domain.templates import TemplateNode
from coalplan.domain.validation import ValidationIssue


class RevisionDecisionTest(unittest.TestCase):
    def test_failed_format_routes_to_repair_format(self) -> None:
        task = ChapterTask(node_id="n1", title="工程概况", status=TaskStatus.failed)
        draft = ChapterDraft(
            node_id="n1",
            title="工程概况",
            markdown='{"bad": true}',
            validation_status=TaskStatus.failed,
            validation_issues=[ValidationIssue(code="json_output", message="not markdown")],
        )

        decision = build_revision_decision(task=task, draft=draft, node=None, policy=None)

        self.assertEqual("repair_format", decision.decision)
        self.assertEqual("error", decision.severity)
        self.assertIn("json_output", decision.validation_issue_codes)

    def test_no_sources_routes_to_human_input(self) -> None:
        task = ChapterTask(node_id="n1", title="模板章节", status=TaskStatus.passed)
        draft = ChapterDraft(
            node_id="n1",
            title="模板章节",
            markdown="# 模板章节\n\n## 主要来源摘要\n\n## 生成正文\n\n## 人工补充需补充\n",
            validation_status=TaskStatus.passed,
        )

        decision = build_revision_decision(task=task, draft=draft, node=None, policy=None)

        self.assertEqual("request_human_input", decision.decision)
        self.assertEqual("warning", decision.severity)

    def test_empty_source_mapping_routes_to_human_input_even_when_generation_skipped(self) -> None:
        task = ChapterTask(
            node_id="bridge",
            title="桥梁及涵洞工程",
            status=TaskStatus.failed,
            source_mapping=SourceMappingResult(
                node_id="bridge",
                matches=[],
                missing_evidence=["输入目录中未找到桥梁及涵洞工程来源。"],
            ),
            error_message="No reliable source mapping; human input or node disablement is required before factual generation.",
        )

        decision = build_revision_decision(task=task, draft=None, node=None, policy=None)

        self.assertEqual("request_human_input", decision.decision)
        self.assertIn("不应生成确定性正文", decision.reasons[0])
        self.assertIn("输入目录中未找到桥梁及涵洞工程来源。", decision.missing_evidence)

    def test_dense_unsplit_chapter_routes_to_subsection_expansion(self) -> None:
        task = ChapterTask(
            node_id="grout",
            title="钻孔与灌浆工程施工",
            status=TaskStatus.passed,
            source_matches=[SourceMatch(section_id="sec_1", title_path=["钻孔与灌浆"], snippet="灌浆施工", score=0.8)],
            target_word_count=1800,
        )
        draft = ChapterDraft(
            node_id="grout",
            title="钻孔与灌浆工程施工",
            markdown="# 钻孔与灌浆工程施工\n\n## 主要来源摘要\n\n- section_id: sec_1\n\n## 生成正文\n\n灌浆施工。\n\n## 人工补充需补充\n\n- 【需人工补充：参数】",
            source_section_ids=["sec_1"],
            validation_status=TaskStatus.passed,
        )
        node = TemplateNode(id="grout", title="钻孔与灌浆工程施工", level=2)
        policy = ChapterGenerationPolicy(
            node_id="grout",
            title="钻孔与灌浆工程施工",
            detail_level="subsection_required",
            split_required=True,
            target_word_count=1800,
        )

        decision = build_revision_decision(task=task, draft=draft, node=node, policy=policy)

        self.assertEqual("expand_subsections", decision.decision)
        self.assertEqual("warning", decision.severity)

    def test_supported_manual_placeholder_routes_to_regenerate(self) -> None:
        task = ChapterTask(
            node_id="overview",
            title="工程概况",
            status=TaskStatus.passed,
            source_matches=[SourceMatch(section_id="sec_scope", title_path=["投标文件", "工程概况"], snippet="工程量", score=0.9)],
        )
        draft = ChapterDraft(
            node_id="overview",
            title="工程概况",
            markdown="# 工程概况\n\n## 主要来源摘要\n\n- sec_scope\n\n## 生成正文\n\n本节概述工程情况。\n\n## 人工补充需补充\n\n- 【需人工补充：主要工程量清单】\n",
            source_section_ids=["sec_scope"],
            validation_status=TaskStatus.passed,
            evidence_audit=EvidenceUtilizationAudit(
                node_id="overview",
                title="工程概况",
                evidence_count=2,
                used_evidence_ids=[],
                unused_high_value_evidence_ids=["ev_1"],
                coverage_ratio=0.0,
                manual_items_with_source_support=["主要工程量清单"],
            ),
        )

        decision = build_revision_decision(task=task, draft=draft, node=None, policy=None)

        self.assertEqual("regenerate", decision.decision)
        self.assertEqual("warning", decision.severity)
        self.assertIsNotNone(decision.evidence_audit)

    def test_omitted_required_source_fact_routes_to_regenerate(self) -> None:
        task = ChapterTask(
            node_id="water",
            title="注水工程施工",
            status=TaskStatus.passed,
            source_matches=[SourceMatch(section_id="sec_water", title_path=["投标文件", "注水"], snippet="压力", score=0.9)],
        )
        draft = ChapterDraft(
            node_id="water",
            title="注水工程施工",
            markdown="# 注水工程施工\n\n## 主要来源摘要\n\n- sec_water\n\n## 生成正文\n\n注水施工应分区组织。\n\n## 人工补充需补充\n\n- 无。\n",
            source_section_ids=["sec_water"],
            validation_status=TaskStatus.passed,
            evidence_audit=EvidenceUtilizationAudit(
                node_id="water",
                title="注水工程施工",
                evidence_count=1,
                required_source_facts=[
                    RequiredSourceFact(
                        fact_id="ev_1:fact_1",
                        evidence_id="ev_1",
                        section_id="sec_water",
                        fact_type="parameter",
                        text="初始注水压力控制在0.2 - 0.3MPa。",
                        tokens=["0.2 - 0.3MPa"],
                    )
                ],
                omitted_required_fact_ids=["ev_1:fact_1"],
                used_evidence_ids=[],
                unused_high_value_evidence_ids=["ev_1"],
                coverage_ratio=0.0,
            ),
        )

        decision = build_revision_decision(task=task, draft=draft, node=None, policy=None)

        self.assertEqual("regenerate", decision.decision)
        self.assertIn("0.2 - 0.3MPa", "\n".join(decision.required_changes))

    def test_revision_context_carries_omitted_required_source_facts(self) -> None:
        task = ChapterTask(
            node_id="water",
            title="water injection",
            status=TaskStatus.passed,
            source_matches=[SourceMatch(section_id="sec_water", title_path=["bid", "water"], snippet="pressure", score=0.9)],
        )
        draft = ChapterDraft(
            node_id="water",
            title="water injection",
            markdown="# water injection\n\n## 主要来源摘要\n\n- sec_water\n\n## 生成正文\n\nGeneric water injection text.\n\n## 人工补充需补充\n\n- none\n",
            source_section_ids=["sec_water"],
            validation_status=TaskStatus.passed,
            evidence_audit=EvidenceUtilizationAudit(
                node_id="water",
                title="water injection",
                evidence_count=1,
                required_source_facts=[
                    RequiredSourceFact(
                        fact_id="ev_1:fact_1",
                        evidence_id="ev_1",
                        section_id="sec_water",
                        fact_type="parameter",
                        text="Initial water injection pressure is 0.2 - 0.3MPa.",
                        tokens=["0.2 - 0.3MPa"],
                    )
                ],
                omitted_required_fact_ids=["ev_1:fact_1"],
                unused_high_value_evidence_ids=["ev_1"],
                coverage_ratio=0.0,
            ),
        )

        decision = build_revision_decision(task=task, draft=draft, node=None, policy=None)
        context = _render_revision_context(decision)

        self.assertIn("omitted_required_source_facts", context)
        self.assertIn("0.2 - 0.3MPa", context)
        self.assertIn("ev_1", context)
        self.assertIn("Regeneration rules", context)

    def test_revision_context_hints_include_feedback_and_manual_supported_items(self) -> None:
        context = "\n".join(
            [
                "## Evidence Utilization Revision Requirements",
                "- omitted_feedback_required_facts:",
                "  - GB50194-2014 temporary power basis",
                "- manual_items_with_source_support:",
                "  - source already supports duckbill nozzle and 0.2MPa injection pressure",
            ]
        )

        hints = _revision_context_required_fact_hints(
            context,
            source_text="GB50194-2014 temporary power basis; duckbill nozzle and 0.2MPa injection pressure",
        )

        self.assertIn("GB50194-2014 temporary power basis", hints)
        self.assertIn("source already supports duckbill nozzle and 0.2MPa injection pressure", hints)

    def test_pattern_fact_gap_routes_to_remap_sources(self) -> None:
        task = ChapterTask(
            node_id="craft",
            title="grouting craft",
            status=TaskStatus.passed,
            source_matches=[SourceMatch(section_id="sec_method", title_path=["bid", "method"], snippet="general method", score=0.8)],
        )
        draft = ChapterDraft(
            node_id="craft",
            title="grouting craft",
            markdown="# grouting craft\n\n## 涓昏鏉ユ簮鎽樿\n\n- sec_method\n\n## 鐢熸垚姝ｆ枃\n\nThe chapter gives a general construction method.\n\n## 浜哄伐琛ュ厖闇€琛ュ厖\n\n- none\n",
            source_section_ids=["sec_method"],
            validation_status=TaskStatus.passed,
            evidence_audit=EvidenceUtilizationAudit(
                node_id="craft",
                title="grouting craft",
                evidence_count=1,
                required_source_facts=[],
                used_evidence_ids=["ev_method"],
                unused_high_value_evidence_ids=[],
                coverage_ratio=1.0,
            ),
        )
        policy = ChapterGenerationPolicy(
            node_id="craft",
            title="grouting craft",
            writing_pattern_key="craft",
            writing_pattern_matches=["craft"],
            pattern_required_source_facts=["施工对象", "工程量", "控制参数"],
        )

        decision = build_revision_decision(task=task, draft=draft, node=None, policy=policy)

        self.assertEqual("remap_sources", decision.decision)
        self.assertIn("craft", decision.reasons[0])
        self.assertIn("控制参数", "\n".join(decision.required_changes))


if __name__ == "__main__":
    unittest.main()
