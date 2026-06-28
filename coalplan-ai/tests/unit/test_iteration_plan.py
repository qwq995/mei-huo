from __future__ import annotations

import unittest

from coalplan.application.iteration_plan import build_iteration_plan, render_iteration_plan_markdown
from coalplan.application.pipeline_action_plan import build_pipeline_action_plan


class IterationPlanTest(unittest.TestCase):
    def test_groups_quality_feedback_and_generation_actions_into_ordered_phases(self) -> None:
        gate_report = {
            "overall_status": "warning",
            "gates": [
                {"name": "input", "status": "passed"},
                {"name": "profile", "status": "passed"},
                {"name": "outline", "status": "passed"},
                {"name": "coverage", "status": "passed"},
                {
                    "name": "detail",
                    "status": "warning",
                    "issues": ["dense nodes need split"],
                    "metrics": {"split_required_count": 1},
                },
                {"name": "mapping", "status": "warning", "issues": ["missing mappings"]},
                {"name": "generation", "status": "warning", "issues": ["failed drafts"]},
                {"name": "revision", "status": "passed"},
                {
                    "name": "quality_feedback",
                    "status": "warning",
                    "issues": [
                        "repair_outline_coverage: missing construction-plan topics",
                        "strengthen_evidence_utilization: mapped facts were omitted",
                    ],
                },
                {"name": "version", "status": "passed"},
            ],
        }
        action_plan = build_pipeline_action_plan(project_id="project_demo", gate_report=gate_report)

        plan = build_iteration_plan(
            project_id="project_demo",
            action_plan=action_plan,
            quality_feedback={"actions": [{"action": "repair_outline_coverage"}]},
        )

        phase_ids = [phase.phase_id for phase in plan.phases]
        self.assertLess(phase_ids.index("outline_detail"), phase_ids.index("mapping_generation"))
        self.assertLess(phase_ids.index("mapping_generation"), phase_ids.index("quality_feedback"))
        self.assertEqual("outline_detail", plan.next_phase_id)
        self.assertEqual("waiting_for_user", plan.status)
        outline_phase = next(phase for phase in plan.phases if phase.phase_id == "outline_detail")
        self.assertTrue(outline_phase.blocks_later_phases)
        self.assertTrue(any(action.action_id == "detail.subsection_proposals" for action in outline_phase.actions))
        generation_phase = next(phase for phase in plan.phases if phase.phase_id == "mapping_generation")
        self.assertGreaterEqual(generation_phase.requires_llm_count, 1)

        markdown = render_iteration_plan_markdown(plan)
        self.assertIn("Iteration Plan", markdown)
        self.assertIn("Map sources and generate chapter versions", markdown)
        self.assertIn("Persist prompts, responses, mappings, evidence, and validation results", markdown)

    def test_revision_decisions_are_visible_even_without_pending_revision_actions(self) -> None:
        action_plan = build_pipeline_action_plan(
            project_id="project_demo",
            gate_report={
                "overall_status": "passed",
                "gates": [
                    {"name": "input", "status": "passed"},
                    {"name": "profile", "status": "passed"},
                    {"name": "outline", "status": "passed"},
                    {"name": "coverage", "status": "passed"},
                    {"name": "detail", "status": "passed"},
                    {"name": "mapping", "status": "passed"},
                    {"name": "generation", "status": "passed"},
                    {"name": "revision", "status": "passed"},
                    {"name": "version", "status": "passed"},
                ],
            },
            revision_decisions=[{"node_id": "a", "decision": "accept"}],
        )

        plan = build_iteration_plan(
            project_id="project_demo",
            action_plan=action_plan,
            revision_decisions=[{"node_id": "a", "decision": "accept"}],
        )

        self.assertTrue(any(phase.phase_id == "revision" for phase in plan.phases))
        self.assertIn("revision decision", plan.summary)

    def test_selected_version_repairs_are_separate_from_final_merge_phase(self) -> None:
        action_plan = build_pipeline_action_plan(
            project_id="project_demo",
            gate_report={
                "overall_status": "warning",
                "gates": [
                    {"name": "input", "status": "passed"},
                    {"name": "profile", "status": "passed"},
                    {"name": "outline", "status": "passed"},
                    {"name": "coverage", "status": "passed"},
                    {"name": "detail", "status": "passed"},
                    {"name": "mapping", "status": "passed"},
                    {"name": "generation", "status": "passed"},
                    {"name": "revision", "status": "passed"},
                    {
                        "name": "version",
                        "status": "warning",
                        "issues": ["Selected version has generated subsection revision actions"],
                        "metrics": {
                            "selected_version_content_revision_actions": 1,
                            "selected_version_content_revision_llm_actions": 1,
                        },
                    },
                    {"name": "merge", "status": "pending"},
                ],
            },
            version_content_targets=[
                {
                    "node_id": "node_water",
                    "version_id": "ver_1",
                    "content_node_id": "gcn_1",
                    "title": "Crack water injection pressure control",
                    "action": "rewrite_subsection",
                    "reason": "omitted_required_source_facts must be absorbed",
                    "evidence_targeted": True,
                    "requires_llm": True,
                }
            ],
        )

        plan = build_iteration_plan(project_id="project_demo", action_plan=action_plan)

        version_review = next(phase for phase in plan.phases if phase.phase_id == "version_review")
        self.assertEqual("version", version_review.gate_to_clear)
        self.assertEqual(1, version_review.requires_llm_count)
        self.assertTrue(any(action.action == "rewrite_subsection" for action in version_review.actions))
        self.assertFalse(any(phase.phase_id == "version_merge" and phase.actions for phase in plan.phases))
        markdown = render_iteration_plan_markdown(plan)
        self.assertIn("Review selected versions, evidence, and generated subsections", markdown)
        self.assertIn("Do not merge while selected versions still have evidence", markdown)


if __name__ == "__main__":
    unittest.main()
