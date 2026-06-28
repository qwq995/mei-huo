from __future__ import annotations

import unittest

from coalplan.application.pipeline_action_plan import build_pipeline_action_plan


class PipelineActionPlanTest(unittest.TestCase):
    def test_gate_warnings_become_prioritized_actions(self) -> None:
        report = {
            "project_id": "project_demo",
            "overall_status": "warning",
            "gates": [
                {"name": "input", "status": "passed"},
                {"name": "profile", "status": "passed"},
                {"name": "outline", "status": "passed"},
                {"name": "coverage", "status": "warning", "issues": ["missing common deployment topics"]},
                {
                    "name": "detail",
                    "status": "warning",
                    "issues": ["dense chapters require split"],
                    "metrics": {"split_required_count": 2},
                },
                {"name": "mapping", "status": "passed"},
                {"name": "generation", "status": "passed"},
                {"name": "revision", "status": "passed"},
                {
                    "name": "version",
                    "status": "warning",
                    "issues": ["selected version has weak source-linked subsections"],
                    "metrics": {
                        "selected_version_missing_source_subsections": 1,
                        "selected_version_weak_source_subsections": 3,
                        "selected_version_content_revision_actions": 2,
                        "selected_version_content_revision_llm_actions": 1,
                        "selected_version_missing_generation_metadata": 1,
                    },
                },
            ],
        }

        plan = build_pipeline_action_plan(project_id="project_demo", gate_report=report)

        action_ids = [action.action_id for action in plan.actions]
        self.assertIn("outline.control_plan_proposal", action_ids)
        self.assertIn("detail.estimate_word_counts", action_ids)
        self.assertIn("detail.subsection_proposals", action_ids)
        self.assertIn("version.review_content_tree_sources", action_ids)
        self.assertIn("version.review_generation_metadata", action_ids)
        self.assertNotIn("version.select_versions", action_ids)
        self.assertTrue(next(action for action in plan.actions if action.action_id == "outline.control_plan_proposal").requires_user_confirmation)
        self.assertEqual("high", next(action for action in plan.actions if action.action_id == "version.review_content_tree_sources").priority)
        self.assertTrue(next(action for action in plan.actions if action.action_id == "version.review_content_tree_sources").requires_llm)
        self.assertIn("content-revision-plan", next(action for action in plan.actions if action.action_id == "version.review_content_tree_sources").endpoint)
        self.assertIn("generation-metadata", next(action for action in plan.actions if action.action_id == "version.review_generation_metadata").endpoint)

    def test_revision_decisions_become_llm_or_user_actions(self) -> None:
        report = {
            "overall_status": "warning",
            "gates": [
                {"name": "input", "status": "passed"},
                {"name": "profile", "status": "passed"},
                {"name": "outline", "status": "passed"},
                {"name": "coverage", "status": "passed"},
                {"name": "detail", "status": "passed"},
                {"name": "mapping", "status": "passed"},
                {"name": "generation", "status": "passed"},
                {"name": "revision", "status": "warning"},
                {"name": "version", "status": "passed"},
            ],
        }
        decisions = [
            {"node_id": "node_a", "title": "注水工程施工", "decision": "regenerate", "reasons": ["omitted required facts"]},
            {"node_id": "node_b", "title": "钻孔灌浆", "decision": "expand_subsections", "required_changes": ["split dense craft chapter"]},
            {"node_id": "node_c", "title": "工程概况", "decision": "accept"},
        ]

        plan = build_pipeline_action_plan(project_id="project_demo", gate_report=report, revision_decisions=decisions)

        regenerate = next(action for action in plan.actions if action.action_id == "revision.node_a.regenerate")
        split = next(action for action in plan.actions if action.action_id == "revision.node_b.expand_subsections")
        self.assertTrue(regenerate.requires_llm)
        self.assertFalse(regenerate.requires_user_confirmation)
        self.assertTrue(split.requires_user_confirmation)
        self.assertFalse(split.requires_llm)
        self.assertNotIn("revision.node_c.accept", [action.action_id for action in plan.actions])

    def test_version_metadata_targets_become_executable_actions(self) -> None:
        report = {
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
                    "issues": ["Selected version needs local writing pattern review"],
                    "metrics": {
                        "selected_version_pattern_revision_actions": 1,
                        "selected_version_pattern_revision_llm_actions": 1,
                    },
                },
            ],
        }

        plan = build_pipeline_action_plan(
            project_id="project_demo",
            gate_report=report,
            version_metadata_targets=[
                {
                    "node_id": "node_craft",
                    "version_id": "version_2",
                    "title": "钻孔灌浆施工",
                    "action": "regenerate",
                    "reason": "craft pattern points are missing",
                    "requires_llm": True,
                    "requires_user_confirmation": False,
                }
            ],
        )

        action = next(item for item in plan.actions if item.action_id == "version.review_generation_metadata.node_craft.version_2")
        self.assertEqual("node_craft", action.target_id)
        self.assertEqual("version_2", action.target_version_id)
        self.assertEqual("regenerate", action.source_decision)
        self.assertEqual("POST", action.method)
        self.assertIn("/chapters/node_craft/versions/version_2/generation-metadata/revision-action", action.endpoint)
        self.assertTrue(action.requires_llm)

    def test_body_cue_metadata_target_keeps_subsection_expansion_user_confirmed(self) -> None:
        report = {
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
                    "issues": ["Selected version misses craft body-writing cue groups"],
                    "metrics": {
                        "selected_version_pattern_revision_actions": 1,
                        "selected_version_pattern_revision_llm_actions": 1,
                        "selected_version_pattern_revision_user_actions": 1,
                    },
                },
            ],
        }

        plan = build_pipeline_action_plan(
            project_id="project_demo",
            gate_report=report,
            version_metadata_targets=[
                {
                    "node_id": "node_grout",
                    "version_id": "version_3",
                    "title": "灌浆施工",
                    "action": "expand_subsections",
                    "reason": "missing craft cues: 施工准备、工艺流程、过程控制、检查验收",
                    "requires_llm": True,
                    "requires_user_confirmation": True,
                }
            ],
        )

        action = next(item for item in plan.actions if item.action_id == "version.review_generation_metadata.node_grout.version_3")
        self.assertEqual("expand_subsections", action.source_decision)
        self.assertEqual("expand_subsections", action.action)
        self.assertTrue(action.requires_llm)
        self.assertTrue(action.requires_user_confirmation)
        self.assertIn("/chapters/node_grout/versions/version_3/generation-metadata/revision-action", action.endpoint)

    def test_version_content_targets_become_executable_actions(self) -> None:
        report = {
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
            ],
        }

        plan = build_pipeline_action_plan(
            project_id="project_demo",
            gate_report=report,
            version_content_targets=[
                {
                    "node_id": "node_craft",
                    "version_id": "version_2",
                    "content_node_id": "content_3",
                    "title": "钻孔灌浆施工 > 质量检查",
                    "action": "rewrite_subsection",
                    "reason": "omitted_required_source_facts: missing 0.5MPa",
                    "evidence_targeted": True,
                    "requires_llm": True,
                    "requires_user_confirmation": False,
                }
            ],
        )

        action = next(item for item in plan.actions if item.action_id == "version.review_content_tree_sources.node_craft.version_2.content_3")
        self.assertEqual("node_craft", action.target_id)
        self.assertEqual("version_2", action.target_version_id)
        self.assertEqual("content_3", action.target_content_node_id)
        self.assertEqual("rewrite_subsection", action.source_decision)
        self.assertIn("(evidence)", action.title)
        self.assertIn("evidence-targeted", action.reason)
        self.assertEqual("POST", action.method)
        self.assertIn("/chapters/node_craft/versions/version_2/content-nodes/content_3/revision-action", action.endpoint)
        self.assertTrue(action.requires_llm)

    def test_outline_step_targets_become_generation_actions(self) -> None:
        report = {
            "overall_status": "pending",
            "gates": [
                {"name": "input", "status": "passed"},
                {"name": "profile", "status": "passed"},
                {"name": "outline", "status": "passed"},
                {"name": "coverage", "status": "passed"},
                {"name": "detail", "status": "passed"},
                {"name": "mapping", "status": "passed"},
                {"name": "generation", "status": "pending", "issues": ["3 chapters are not generated"]},
                {"name": "revision", "status": "passed"},
                {"name": "version", "status": "passed"},
            ],
        }

        plan = build_pipeline_action_plan(
            project_id="project_demo",
            gate_report=report,
            outline_step_targets=[
                {
                    "step_id": "outline_level_2_root",
                    "reason": "2 个可生成节点待处理：工程概况、施工部署",
                }
            ],
        )

        action = next(item for item in plan.actions if item.action_id == "generation.outline_step.outline_level_2_root")
        fallback = next(item for item in plan.actions if item.action_id == "generation.generate")
        self.assertEqual("generate_outline_step", action.action)
        self.assertEqual("outline_level_2_root", action.target_step_id)
        self.assertEqual("POST", action.method)
        self.assertIn("/outline-generation-steps/outline_level_2_root/generate", action.endpoint)
        self.assertTrue(action.requires_llm)
        self.assertEqual("normal", fallback.priority)

    def test_child_generation_targets_become_branch_generation_actions(self) -> None:
        report = {
            "overall_status": "pending",
            "gates": [
                {"name": "input", "status": "passed"},
                {"name": "profile", "status": "passed"},
                {"name": "outline", "status": "passed"},
                {"name": "coverage", "status": "passed"},
                {"name": "detail", "status": "passed"},
                {"name": "mapping", "status": "passed"},
                {"name": "generation", "status": "pending", "issues": ["split children are not generated"]},
                {"name": "revision", "status": "passed"},
                {"name": "version", "status": "passed"},
            ],
        }

        plan = build_pipeline_action_plan(
            project_id="project_demo",
            gate_report=report,
            child_generation_targets=[
                {
                    "parent_node_id": "node_parent",
                    "title": "灌浆施工",
                    "reason": "3 child chapter(s) need branch generation.",
                    "child_count": 3,
                    "child_node_ids": ["child_1", "child_2", "child_3"],
                }
            ],
        )

        action = next(item for item in plan.actions if item.action_id == "generation.child_branch.node_parent")
        fallback = next(item for item in plan.actions if item.action_id == "generation.generate")
        self.assertEqual("generate_child_chapters", action.action)
        self.assertEqual("node_parent", action.target_id)
        self.assertEqual("POST", action.method)
        self.assertIn("/chapters/node_parent/children/generate", action.endpoint)
        self.assertTrue(action.requires_llm)
        self.assertFalse(action.requires_user_confirmation)
        self.assertEqual("normal", fallback.priority)

    def test_version_evidence_targets_become_review_actions(self) -> None:
        report = {
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
                    "issues": ["Selected version needs evidence utilization review"],
                    "metrics": {
                        "selected_version_evidence_revision_actions": 1,
                        "selected_version_evidence_revision_llm_actions": 1,
                    },
                },
            ],
        }

        plan = build_pipeline_action_plan(
            project_id="project_demo",
            gate_report=report,
            version_evidence_targets=[
                {
                    "node_id": "node_craft",
                    "version_id": "version_2",
                    "title": "注水工程施工",
                    "action": "regenerate",
                    "reason": "omitted_required_source_facts: 0.5MPa",
                    "requires_llm": True,
                    "requires_user_confirmation": False,
                }
            ],
        )

        action = next(item for item in plan.actions if item.action_id == "version.review_evidence_utilization.node_craft.version_2")
        self.assertEqual("review_evidence_utilization", action.action)
        self.assertEqual("regenerate", action.source_decision)
        self.assertEqual("node_craft", action.target_id)
        self.assertEqual("version_2", action.target_version_id)
        self.assertEqual("POST", action.method)
        self.assertIn("/chapters/node_craft/versions/version_2/evidence-audit/revision-action", action.endpoint)
        self.assertTrue(action.requires_llm)

    def test_quality_feedback_gate_becomes_outline_and_regeneration_actions(self) -> None:
        report = {
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
                    "name": "quality_feedback",
                    "status": "warning",
                    "issues": [
                        "repair_outline_coverage: heading tree misses human reference topics",
                        "strengthen_evidence_utilization: traceability facts were omitted",
                    ],
                },
                {"name": "version", "status": "passed"},
            ],
        }

        plan = build_pipeline_action_plan(project_id="project_demo", gate_report=report)
        action_ids = [action.action_id for action in plan.actions]

        self.assertIn("quality_feedback.review_audit_revision_targets", action_ids)
        self.assertIn("quality_feedback.outline_repair_proposal", action_ids)
        self.assertIn("quality_feedback.remap_and_regenerate", action_ids)
        review = next(action for action in plan.actions if action.action_id == "quality_feedback.review_audit_revision_targets")
        self.assertEqual("POST", review.method)
        self.assertEqual("run_quality_iteration", review.action)
        self.assertIn("/quality-iteration", review.endpoint)
        self.assertTrue(review.requires_llm)
        regenerate = next(action for action in plan.actions if action.action_id == "quality_feedback.remap_and_regenerate")
        self.assertTrue(regenerate.requires_llm)
        self.assertEqual("high", regenerate.priority)

    def test_missing_quality_feedback_after_generation_prompts_audit_import(self) -> None:
        report = {
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
                {"name": "quality_feedback", "status": "pending", "summary": "No quality feedback."},
                {"name": "version", "status": "passed"},
            ],
        }

        plan = build_pipeline_action_plan(project_id="project_demo", gate_report=report)

        run_action = next(action for action in plan.actions if action.action_id == "quality_feedback.run_quality_audit")
        self.assertTrue(run_action.requires_user_confirmation)
        self.assertEqual("/projects/project_demo/quality-audit", run_action.endpoint)
        self.assertEqual("high", run_action.priority)

        action = next(action for action in plan.actions if action.action_id == "quality_feedback.apply_audit_report")
        self.assertTrue(action.requires_user_confirmation)
        self.assertEqual("/projects/project_demo/quality-feedback", action.endpoint)


if __name__ == "__main__":
    unittest.main()
