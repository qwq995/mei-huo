from __future__ import annotations

import unittest

from coalplan.application.current_execution_window import build_current_execution_window


class CurrentExecutionWindowTest(unittest.TestCase):
    def test_user_confirmation_phase_defers_later_llm_actions(self) -> None:
        window = build_current_execution_window(
            {
                "project_id": "project_demo",
                "status": "blocked",
                "phases": [
                    {
                        "phase_id": "outline_detail",
                        "title": "Repair editable outline",
                        "blocks_later_phases": True,
                        "stop_conditions": ["Pause until the user reviews and applies proposals."],
                        "actions": [
                            {
                                "action_id": "outline.control_plan_proposal",
                                "stage": "coverage",
                                "action": "propose_outline_repair",
                                "priority": "normal",
                                "title": "Create proposal",
                                "requires_user_confirmation": True,
                                "requires_llm": False,
                            }
                        ],
                    },
                    {
                        "phase_id": "mapping_generation",
                        "title": "Generate chapters",
                        "actions": [
                            {
                                "action_id": "generation.generate",
                                "stage": "generation",
                                "action": "generate_chapters",
                                "priority": "high",
                                "title": "Generate",
                                "requires_llm": True,
                                "requires_user_confirmation": False,
                            }
                        ],
                    },
                ],
            }
        )

        self.assertEqual("waiting_for_user", window.status)
        self.assertEqual("outline_detail", window.current_phase_id)
        self.assertEqual(["outline.control_plan_proposal"], [item.action_id for item in window.allowed_actions])
        self.assertEqual(["generation.generate"], [item.action_id for item in window.deferred_actions])
        self.assertEqual("outline_detail", window.deferred_actions[0].blocked_by_phase_id)
        self.assertIn("Pause until", window.deferred_actions[0].blocked_reason or "")

    def test_pending_outline_proposal_becomes_apply_action(self) -> None:
        window = build_current_execution_window(
            {
                "project_id": "project_demo",
                "status": "blocked",
                "phases": [
                    {
                        "phase_id": "outline_detail",
                        "title": "Repair editable outline",
                        "blocks_later_phases": True,
                        "actions": [
                            {
                                "action_id": "outline.control_plan_proposal",
                                "stage": "coverage",
                                "action": "propose_outline_repair",
                                "priority": "normal",
                                "title": "Create proposal",
                                "requires_user_confirmation": True,
                            }
                        ],
                    }
                ],
            },
            pending_proposals=[
                {
                    "id": "proposal_1",
                    "target_type": "outline",
                    "target_id": "project_demo",
                    "suggestion": "补齐目录",
                    "status": "pending",
                    "created_at": "2026-06-28T00:00:00",
                }
            ],
        )

        action = window.allowed_actions[0]
        self.assertEqual("outline.apply_pending_proposal.proposal_1", action.action_id)
        self.assertEqual("proposal_1", action.proposal_id)
        self.assertIn("/outline/proposals/proposal_1/apply", action.endpoint or "")
        self.assertFalse(action.requires_llm)
        self.assertTrue(action.requires_user_confirmation)

    def test_pending_outline_proposal_blocks_later_auto_phase(self) -> None:
        window = build_current_execution_window(
            {
                "project_id": "project_demo",
                "status": "action_required",
                "phases": [
                    {
                        "phase_id": "mapping_generation",
                        "title": "Map and generate",
                        "actions": [
                            {
                                "action_id": "generation.generate",
                                "stage": "generation",
                                "action": "generate_chapters",
                                "priority": "high",
                                "title": "Generate",
                                "requires_llm": True,
                                "requires_user_confirmation": False,
                            }
                        ],
                    }
                ],
            },
            pending_proposals=[
                {
                    "id": "proposal_late",
                    "target_type": "outline",
                    "target_id": "project_demo",
                    "suggestion": "Review outline before generation.",
                    "status": "pending",
                }
            ],
        )

        self.assertEqual("waiting_for_user", window.status)
        self.assertEqual("outline_detail", window.current_phase_id)
        self.assertEqual("outline.apply_pending_proposal.proposal_late", window.allowed_actions[0].action_id)
        self.assertEqual("proposal_late", window.allowed_actions[0].proposal_id)
        self.assertEqual(["generation.generate"], [item.action_id for item in window.deferred_actions])
        self.assertEqual("outline_detail", window.deferred_actions[0].blocked_by_phase_id)


if __name__ == "__main__":
    unittest.main()
