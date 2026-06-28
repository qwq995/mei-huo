from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from coalplan.application.serialization import to_json_text
from coalplan.application.targeted_revision_plan import (
    build_targeted_revision_plan,
    load_generation_run_comparison,
    load_revision_plan_input,
    render_targeted_revision_plan,
    write_targeted_revision_plan,
)


class TargetedRevisionPlanTest(unittest.TestCase):
    def test_builds_chapter_level_actions_from_failed_summary(self) -> None:
        summary = {
            "output_root": "run",
            "model": "deepseek-v4-flash",
            "projects": [
                {
                    "key": "project_3",
                    "project_id": "project_demo",
                    "template_id": "coal_fire",
                    "run_status": "partial_failed",
                    "generation_scope": "full",
                    "task_count": 3,
                    "passed_count": 1,
                    "failed": [
                        {
                            "node_id": "n_format",
                            "title": "Format chapter",
                            "status": "failed",
                            "error_message": "Missing section: ## 人工补充需补充",
                        },
                        {
                            "node_id": "n_evidence",
                            "title": "Water injection",
                            "status": "needs_repair",
                            "error_message": "Mapped source evidence was not sufficiently absorbed by the generated chapter: omitted_required_source_facts",
                        },
                    ],
                    "quality_audit": {
                        "recommended_actions": ["strengthen_evidence_utilization"],
                    },
                    "pattern_card_usage": {
                        "missing_prompt_card_count": 1,
                    },
                }
            ],
        }

        plan = build_targeted_revision_plan(summary)
        markdown = render_targeted_revision_plan(plan)

        self.assertEqual("targeted_project_controls_then_chapter_revision", plan["rerun_policy"])
        actions = {item["node_id"]: item for item in plan["projects"][0]["actions"] if item.get("node_id")}
        self.assertEqual("repair_format", actions["n_format"]["action"])
        self.assertEqual("regenerate_evidence_targeted", actions["n_evidence"]["action"])
        self.assertIn("omitted_required_source_facts", "\n".join(actions["n_evidence"]["next_prompt_context"]))
        self.assertIn("strengthen_evidence_utilization", plan["action_counts"])
        self.assertIn("persist_pattern_prompt_cards", plan["action_counts"])
        self.assertIn("Do not repeat the same prompt", markdown)

    def test_outline_quality_action_changes_scope(self) -> None:
        summary = {
            "projects": [
                {
                    "key": "project_4",
                    "project_id": "project_hydro",
                    "task_count": 2,
                    "passed_count": 2,
                    "failed": [],
                    "quality_audit": {"recommended_actions": ["repair_outline_coverage"]},
                }
            ]
        }

        plan = build_targeted_revision_plan(summary)

        self.assertEqual("outline_repair_before_chapter_generation", plan["rerun_policy"])
        self.assertEqual("repair_outline_then_regenerate_affected_chapters", plan["projects"][0]["recommended_scope"])

    def test_loads_inputs_and_writes_plan(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            summary = {"model": "fake", "projects": []}
            comparison = {"verdict": "improved"}
            (root / "deepseek_full_generation_summary.json").write_text(to_json_text(summary), encoding="utf-8")
            compare_dir = root / "compare"
            compare_dir.mkdir()
            (compare_dir / "generation_run_comparison.json").write_text(to_json_text(comparison), encoding="utf-8")

            loaded_summary = load_revision_plan_input(root)
            loaded_comparison = load_generation_run_comparison(compare_dir)
            plan = build_targeted_revision_plan(loaded_summary, comparison=loaded_comparison)
            paths = write_targeted_revision_plan(plan, root / "plan")

            self.assertEqual("fake", loaded_summary["model"])
            self.assertEqual("improved", loaded_comparison["verdict"])
            self.assertTrue(Path(paths["json"]).exists())
            self.assertTrue(Path(paths["markdown"]).exists())


if __name__ == "__main__":
    unittest.main()
