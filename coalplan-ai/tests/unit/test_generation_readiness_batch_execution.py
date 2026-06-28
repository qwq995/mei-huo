from __future__ import annotations

import unittest

from coalplan.application.run_generation_pipeline import _render_generation_readiness_batch_execution


class GenerationReadinessBatchExecutionTest(unittest.TestCase):
    def test_child_branch_failure_renders_next_action_and_endpoint(self) -> None:
        markdown = _render_generation_readiness_batch_execution(
            {
                "project_id": "project_demo",
                "status": "completed",
                "limit": 1,
                "include_user_confirmation": False,
                "respect_execution_window": True,
                "source_readiness": {"status": "generation_required", "summary": "before"},
                "next_readiness": {"status": "revision_required", "summary": "after"},
                "executed": [
                    {
                        "batch": "auto_generation",
                        "node_id": "parent_1",
                        "title": "施工总体方案",
                        "action": "generate_child_chapters",
                        "result_kind": "child_branch_generation",
                        "status": "partial_failed",
                        "generated_count": 0,
                        "failed_count": 1,
                        "item": {"node_id": "parent_1", "next_action": "generate_child_chapters"},
                        "result": {
                            "kind": "child_branch_generation",
                            "status": "partial_failed",
                            "generated": [],
                            "failed": [
                                {
                                    "node_id": "child_1",
                                    "error": "omitted_required_source_facts",
                                    "next_action": "regenerate",
                                    "endpoint": "/projects/project_demo/chapters/child_1/revision-action",
                                }
                            ],
                        },
                    }
                ],
                "skipped": [],
                "failed": [],
            }
        )

        self.assertIn("child_1", markdown)
        self.assertIn("omitted_required_source_facts", markdown)
        self.assertIn("next=regenerate", markdown)
        self.assertIn("/projects/project_demo/chapters/child_1/revision-action", markdown)


if __name__ == "__main__":
    unittest.main()
