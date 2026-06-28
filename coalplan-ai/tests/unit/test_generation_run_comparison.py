from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from coalplan.application.generation_run_comparison import (
    compare_generation_run_summaries,
    load_generation_run_summary,
    render_generation_run_comparison,
    write_generation_run_comparison,
)
from coalplan.application.serialization import to_json_text


class GenerationRunComparisonTest(unittest.TestCase):
    def test_compare_run_summaries_reports_control_traceability_improvement(self) -> None:
        baseline = {
            "output_root": "old",
            "model": "deepseek-v4-flash",
            "projects": [
                {
                    "key": "project_3",
                    "generation_scope": "partial",
                    "task_count": 3,
                    "passed_count": 2,
                    "failed": [{"node_id": "n1", "title": "Water injection", "status": "needs_repair"}],
                    "actual_word_count_total": 1200,
                    "trace_usage": {"call_count": 6, "total_tokens": 1000, "estimated_total_tokens": 1000},
                    "quality_audit": {
                        "issue_count": 1,
                        "recommendation_count": 1,
                        "recommended_actions": ["strengthen_evidence_utilization"],
                        "source_fact_absorption_ratio": 0.2,
                        "human_heading_coverage_ratio": 0.3,
                    },
                    "pattern_card_usage": {
                        "chapter_count": 3,
                        "chapters_with_prompt_cards": 0,
                        "missing_prompt_card_count": 3,
                        "prompt_card_total": 0,
                        "prompt_card_actionable_total": 0,
                    },
                }
            ],
            "trace_usage_total": {"call_count": 6, "total_tokens": 1000},
        }
        candidate = {
            "output_root": "new",
            "model": "deepseek-v4-flash",
            "projects": [
                {
                    "key": "project_3",
                    "generation_scope": "partial",
                    "task_count": 3,
                    "passed_count": 2,
                    "failed": [{"node_id": "n1", "title": "Water injection", "status": "needs_repair"}],
                    "actual_word_count_total": 1800,
                    "trace_usage": {"call_count": 7, "total_tokens": 1300, "estimated_total_tokens": 1300},
                    "quality_audit": {
                        "issue_count": 1,
                        "recommendation_count": 1,
                        "recommended_actions": ["strengthen_evidence_utilization"],
                        "source_fact_absorption_ratio": 0.25,
                        "human_heading_coverage_ratio": 0.35,
                    },
                    "pattern_card_usage": {
                        "chapter_count": 3,
                        "chapters_with_prompt_cards": 3,
                        "missing_prompt_card_count": 0,
                        "prompt_card_total": 6,
                        "prompt_card_actionable_total": 4,
                    },
                }
            ],
            "trace_usage_total": {"call_count": 7, "total_tokens": 1300},
        }

        comparison = compare_generation_run_summaries(baseline, candidate)
        markdown = render_generation_run_comparison(comparison)

        self.assertEqual("control_traceability_improved", comparison["verdict"])
        self.assertEqual(3, comparison["summary_delta"]["chapters_with_prompt_cards_delta"])
        self.assertEqual(-3, comparison["summary_delta"]["missing_prompt_card_count_delta"])
        self.assertEqual(0.05, comparison["projects"][0]["delta"]["source_fact_absorption_ratio_delta"])
        self.assertIn("revise only those chapters", "\n".join(comparison["recommended_next_actions"]))
        self.assertIn("Keep the pattern-card control layer", "\n".join(comparison["recommended_next_actions"]))
        self.assertIn("Generation Run Comparison", markdown)
        self.assertIn("control_traceability_improved", markdown)

    def test_loads_summary_from_directory_and_writes_report(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            summary = {
                "output_root": str(root),
                "model": "fake",
                "projects": [],
                "trace_usage_total": {},
            }
            (root / "deepseek_full_generation_summary.json").write_text(to_json_text(summary), encoding="utf-8")

            loaded = load_generation_run_summary(root)
            comparison = compare_generation_run_summaries(loaded, loaded)
            paths = write_generation_run_comparison(comparison, root / "compare")

            self.assertEqual("fake", loaded["model"])
            self.assertTrue(Path(paths["json"]).exists())
            self.assertTrue(Path(paths["markdown"]).exists())

    def test_regression_verdict_when_pass_rate_drops(self) -> None:
        baseline = {
            "projects": [{"key": "project_3", "task_count": 4, "passed_count": 4, "failed": []}],
        }
        candidate = {
            "projects": [{"key": "project_3", "task_count": 4, "passed_count": 2, "failed": [{"node_id": "a"}, {"node_id": "b"}]}],
        }

        comparison = compare_generation_run_summaries(baseline, candidate)

        self.assertEqual("regressed", comparison["verdict"])
        self.assertLess(comparison["summary_delta"]["pass_rate_delta"], 0)
        self.assertIn("Review candidate failed tasks", comparison["recommended_next_actions"][0])


if __name__ == "__main__":
    unittest.main()
