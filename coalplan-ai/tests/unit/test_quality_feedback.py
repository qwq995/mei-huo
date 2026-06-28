import unittest

from coalplan.application.quality_feedback import (
    apply_quality_feedback_to_generation_plan,
    build_quality_outline_repair_proposal_nodes,
    build_quality_feedback_plan,
    quality_feedback_required_fact_hints,
    render_quality_feedback_mapping_context,
    render_quality_feedback_prompt_context,
    render_quality_feedback_plan,
)
from coalplan.domain.generation_control import ChapterGenerationPolicy, GenerationControlPlan


class QualityFeedbackTest(unittest.TestCase):
    def test_feedback_plan_converts_audit_recommendations_to_actions(self) -> None:
        report = {
            "project_key": "demo",
            "word_counts": {"generated_vs_human_ratio": 0.16},
            "headings": {
                "human_heading_coverage_ratio": 0.08,
                "generated_count": 12,
                "human_count": 160,
                "missing_human_heading_examples": ["施工临时设施布置", "用水布置"],
            },
            "source_facts": {
                "candidate_count": 20,
                "absorbed_count": 2,
                "omitted_count": 18,
                "absorption_ratio": 0.1,
                "omitted_examples": [{"fact": "GB50194-2014"}, {"fact": "1.5MPa"}],
            },
            "common_topics": {
                "deployment": {"covered": False},
                "quality": {"covered": True},
                "safety": {"covered": False},
                "environment": {"covered": False},
            },
            "recommendations": [
                {"action": "increase_detail_budget"},
                {"action": "repair_outline_coverage"},
                {"action": "strengthen_evidence_utilization"},
            ],
        }

        feedback = build_quality_feedback_plan(report)

        self.assertEqual("demo", feedback.project_key)
        self.assertEqual(
            [
                "increase_detail_budget",
                "repair_outline_coverage",
                "strengthen_evidence_utilization",
                "add_missing_common_topics",
            ],
            [action.action for action in feedback.actions],
        )
        self.assertTrue(any(trigger.action == "expand_subsections" for trigger in feedback.revision_triggers))
        self.assertTrue(any(trigger.action == "regenerate" for trigger in feedback.revision_triggers))

    def test_feedback_plan_proposes_policy_adjustments(self) -> None:
        current = GenerationControlPlan(
            project_id="p1",
            chapter_policies=[
                ChapterGenerationPolicy(
                    node_id="n1",
                    title="General",
                    detail_level="brief",
                    target_word_count=500,
                    max_source_matches=6,
                    max_evidence_spans=8,
                ),
                ChapterGenerationPolicy(
                    node_id="n2",
                    title="Dense craft",
                    detail_level="subsection_required",
                    target_word_count=1600,
                    split_required=True,
                    max_source_matches=14,
                    max_evidence_spans=28,
                ),
            ],
        )
        report = {
            "project_key": "demo",
            "word_counts": {"generated_vs_human_ratio": 0.12},
            "headings": {"human_heading_coverage_ratio": 0.8},
            "source_facts": {"absorption_ratio": 0.8, "candidate_count": 20},
            "common_topics": {},
            "recommendations": [{"action": "increase_detail_budget"}],
        }

        feedback = build_quality_feedback_plan(report, current_plan=current)
        next_plan = apply_quality_feedback_to_generation_plan(current, feedback)

        first = next(item for item in next_plan.chapter_policies if item.node_id == "n1")
        second = next(item for item in next_plan.chapter_policies if item.node_id == "n2")
        self.assertEqual(1000, first.target_word_count)
        self.assertEqual("normal", first.detail_level)
        self.assertGreaterEqual(first.max_evidence_spans, 18)
        self.assertEqual(3200, second.target_word_count)
        self.assertEqual("subsection_required", second.detail_level)
        self.assertTrue(second.split_required)

    def test_organization_pattern_gaps_are_merged_into_outline_feedback(self) -> None:
        report = {
            "project_key": "demo",
            "word_counts": {"generated_vs_human_ratio": 0.8},
            "headings": {
                "human_heading_coverage_ratio": 0.1,
                "missing_human_heading_examples": ["施工平面布置"],
            },
            "source_facts": {"absorption_ratio": 0.8, "candidate_count": 20},
            "common_topics": {},
            "organization_patterns": {
                "average_coverage_ratio": 0.25,
                "applicable_pattern_count": 1,
                "audits": [
                    {
                        "pattern_key": "craft",
                        "applicable": True,
                        "missing_points": ["工艺流程和施工程序", "质量检查、试验和验收"],
                    }
                ],
            },
            "recommendations": [{"action": "repair_outline_coverage"}],
        }

        feedback = build_quality_feedback_plan(report)

        outline = next(action for action in feedback.actions if action.action == "repair_outline_coverage")
        self.assertIn("施工平面布置", outline.missing_heading_examples)
        self.assertIn("craft: 工艺流程和施工程序", outline.missing_heading_examples)
        self.assertTrue(any("pattern cards" in step for step in outline.next_steps))
        self.assertTrue(any(trigger.title == "organization pattern coverage" for trigger in feedback.revision_triggers))

    def test_evidence_feedback_increases_fact_carryover_budget(self) -> None:
        current = GenerationControlPlan(
            chapter_policies=[
                ChapterGenerationPolicy(
                    node_id="n1",
                    title="Quality",
                    detail_level="normal",
                    max_source_matches=8,
                    max_evidence_spans=10,
                )
            ],
        )
        report = {
            "project_key": "demo",
            "word_counts": {"generated_vs_human_ratio": 0.8},
            "headings": {"human_heading_coverage_ratio": 0.8},
            "source_facts": {
                "candidate_count": 30,
                "absorbed_count": 3,
                "omitted_count": 27,
                "absorption_ratio": 0.1,
                "omitted_examples": [{"fact": "GB/T 123"}],
            },
            "common_topics": {},
            "recommendations": [{"action": "strengthen_evidence_utilization"}],
        }

        feedback = build_quality_feedback_plan(report, current_plan=current)
        next_plan = apply_quality_feedback_to_generation_plan(current, feedback)

        action = feedback.actions[0]
        policy = next_plan.chapter_policies[0]
        self.assertEqual("strengthen_evidence_utilization", action.action)
        self.assertIn("GB/T 123", action.omitted_source_facts)
        self.assertEqual(12, policy.max_source_matches)
        self.assertEqual(24, policy.max_evidence_spans)

    def test_combined_feedback_merges_policy_adjustments_for_same_node(self) -> None:
        current = GenerationControlPlan(
            chapter_policies=[
                ChapterGenerationPolicy(
                    node_id="n1",
                    title="Craft",
                    detail_level="normal",
                    target_word_count=1000,
                    max_source_matches=8,
                    max_evidence_spans=10,
                )
            ],
        )
        report = {
            "project_key": "demo",
            "word_counts": {"generated_vs_human_ratio": 0.12},
            "headings": {"human_heading_coverage_ratio": 0.8},
            "source_facts": {
                "candidate_count": 30,
                "absorbed_count": 3,
                "omitted_count": 27,
                "absorption_ratio": 0.1,
                "omitted_examples": [{"fact": "GB/T 123"}],
            },
            "common_topics": {},
            "recommendations": [
                {"action": "increase_detail_budget"},
                {"action": "strengthen_evidence_utilization"},
            ],
        }

        feedback = build_quality_feedback_plan(report, current_plan=current)
        next_plan = apply_quality_feedback_to_generation_plan(current, feedback)

        policy = next_plan.chapter_policies[0]
        self.assertEqual(2000, policy.target_word_count)
        self.assertEqual("deep", policy.detail_level)
        self.assertEqual(12, policy.max_source_matches)
        self.assertEqual(24, policy.max_evidence_spans)

    def test_render_feedback_plan_is_traceable_markdown(self) -> None:
        report = {
            "project_key": "demo",
            "word_counts": {"generated_vs_human_ratio": 0.2},
            "headings": {"human_heading_coverage_ratio": 0.8},
            "source_facts": {"absorption_ratio": 0.8, "candidate_count": 20},
            "common_topics": {},
            "recommendations": [{"action": "increase_detail_budget"}],
        }

        markdown = render_quality_feedback_plan(build_quality_feedback_plan(report))

        self.assertIn("# Quality Feedback Plan: demo", markdown)
        self.assertIn("## increase_detail_budget", markdown)
        self.assertIn("generated_vs_human_ratio=0.2", markdown)

    def test_quality_feedback_renders_generation_prompt_context(self) -> None:
        report = {
            "project_key": "demo",
            "word_counts": {"generated_vs_human_ratio": 0.8},
            "headings": {
                "human_heading_coverage_ratio": 0.1,
                "missing_human_heading_examples": ["Temporary facilities layout"],
            },
            "source_facts": {
                "absorption_ratio": 0.1,
                "omitted_examples": [{"fact": "Use GB50194-2014 as the temporary-power basis."}],
            },
            "common_topics": {"safety": {"covered": False}},
            "recommendations": [
                {"action": "repair_outline_coverage"},
                {"action": "strengthen_evidence_utilization"},
            ],
        }

        context = render_quality_feedback_prompt_context(build_quality_feedback_plan(report))

        self.assertIn("Quality Audit Feedback Requirements", context)
        self.assertIn("Temporary facilities layout", context)
        self.assertIn("GB50194-2014", context)
        self.assertIn("verify them against mapped source sections", context)

    def test_trace_diagnostics_become_revision_triggers_and_prompt_context(self) -> None:
        report = {
            "project_key": "demo",
            "word_counts": {"generated_vs_human_ratio": 0.8},
            "headings": {"human_heading_coverage_ratio": 0.8},
            "source_facts": {"absorption_ratio": 0.8, "candidate_count": 20},
            "common_topics": {},
            "recommendations": [],
        }
        trace = {
            "trace_count": 3,
            "buckets": {"not_prompted": 1, "prompted_but_omitted": 1},
            "facts": [
                {"fact": "GB50194-2014", "status": "not_prompted", "suggested_action": "remap_sources"},
                {"fact": "DZ/T 0227-2010", "status": "prompted_but_omitted", "suggested_action": "regenerate"},
            ],
        }

        feedback = build_quality_feedback_plan(report, trace_diagnostics=trace)
        context = render_quality_feedback_prompt_context(feedback)
        mapping_context = render_quality_feedback_mapping_context(feedback)

        self.assertTrue(any(action.target == "traceability" for action in feedback.actions))
        self.assertTrue(any(trigger.action == "remap_sources" for trigger in feedback.revision_triggers))
        self.assertTrue(any(trigger.action == "regenerate" for trigger in feedback.revision_triggers))
        self.assertIn("DZ/T 0227-2010", context)
        self.assertIn("Trace Revision Generation Requirements", context)
        self.assertIn("Quality Feedback Mapping Requirements", mapping_context)
        self.assertIn("Trace Revision Mapping Requirements", mapping_context)
        self.assertIn("GB50194-2014", mapping_context)
        self.assertIn("missing_evidence", mapping_context)

    def test_quality_feedback_required_fact_hints_filter_by_current_source_text(self) -> None:
        report = {
            "project_key": "demo",
            "word_counts": {"generated_vs_human_ratio": 0.8},
            "headings": {"human_heading_coverage_ratio": 0.8},
            "source_facts": {
                "absorption_ratio": 0.1,
                "omitted_examples": [
                    {"fact": "GB50194-2014"},
                    {"fact": "0.3 - 0.5MPa"},
                ],
            },
            "common_topics": {},
            "recommendations": [{"action": "strengthen_evidence_utilization"}],
        }

        feedback = build_quality_feedback_plan(report)
        hints = quality_feedback_required_fact_hints(
            feedback,
            source_text="本节来源包含施工现场临时用电安全技术规范GB50194-2014。",
        )

        self.assertEqual(["GB50194-2014"], hints)

    def test_trace_feedback_required_fact_hints_are_source_filtered(self) -> None:
        feedback = build_quality_feedback_plan(
            {
                "project_key": "demo",
                "word_counts": {"generated_vs_human_ratio": 0.8},
                "headings": {"human_heading_coverage_ratio": 0.8},
                "source_facts": {"absorption_ratio": 0.8, "candidate_count": 20},
                "common_topics": {},
                "recommendations": [],
            },
            trace_diagnostics={
                "trace_count": 2,
                "buckets": {"not_prompted": 1, "prompted_but_omitted": 1},
                "facts": [
                    {
                        "fact": "108mm",
                        "status": "not_prompted",
                        "suggested_action": "remap_sources",
                    },
                    {
                        "fact": "GB8978-1996",
                        "status": "prompted_but_omitted",
                        "suggested_action": "regenerate",
                    },
                ],
            },
        )

        hints = quality_feedback_required_fact_hints(
            feedback,
            source_text="本章来源明确钻孔孔径采用108mm，并执行污水综合排放标准GB8978-1996。",
        )

        self.assertEqual(["108mm", "GB8978-1996"], hints)

    def test_quality_feedback_builds_outline_repair_proposal_nodes(self) -> None:
        report = {
            "project_key": "demo",
            "word_counts": {"generated_vs_human_ratio": 0.8},
            "headings": {
                "human_heading_coverage_ratio": 0.1,
                "missing_human_heading_examples": [
                    "1. Temporary facilities layout ........ 12",
                    "2. Temporary facilities layout ........ 12",
                    "Construction water arrangement",
                ],
            },
            "source_facts": {"absorption_ratio": 0.8},
            "common_topics": {},
            "recommendations": [{"action": "repair_outline_coverage"}],
        }

        nodes = build_quality_outline_repair_proposal_nodes(
            feedback_plan=build_quality_feedback_plan(report),
            existing_titles={"Existing"},
            start_sort_order=50,
        )

        self.assertEqual(2, len(nodes))
        self.assertEqual("create", nodes[0]["__action"])
        self.assertEqual("Temporary facilities layout", nodes[0]["title"])
        self.assertEqual(50, nodes[0]["sort_order"])
        self.assertEqual(60, nodes[1]["sort_order"])


if __name__ == "__main__":
    unittest.main()
