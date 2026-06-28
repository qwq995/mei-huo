from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from coalplan.application.pattern_card_usage_audit import (
    audit_pattern_card_usage,
    compare_pattern_card_usage_reports,
    render_pattern_card_usage_comparison,
    render_pattern_card_usage_audit,
    write_pattern_card_usage_comparison,
    write_pattern_card_usage_audit,
)
from coalplan.application.serialization import to_json_text


class PatternCardUsageAuditTest(unittest.TestCase):
    def test_audit_reports_missing_and_actionable_pattern_cards(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            chapters = root / "chapters"
            chapters.mkdir()
            (chapters / "node_1.md").write_text(
                "# craft\n\n## 生成正文\n\nGeneric construction paragraph.\n",
                encoding="utf-8",
            )
            (chapters / "node_1.generation_metadata.json").write_text(
                to_json_text(
                    {
                        "node_id": "node_1",
                        "title": "Craft chapter",
                        "selected_pattern_keys": [],
                        "generation_policy": {
                            "pattern_prompt_cards": [
                                {
                                    "pattern_key": "craft",
                                    "generation_moves": ["Write process controls", "Record acceptance evidence"],
                                    "source_mapping_requirements": ["Map process and acceptance evidence."],
                                    "human_only_items": ["approved final pressure"],
                                }
                            ]
                        },
                    }
                ),
                encoding="utf-8",
            )
            (chapters / "node_2.md").write_text(
                "# overview\n\n## 生成正文\n\nProject name and scope.\n",
                encoding="utf-8",
            )
            (chapters / "node_2.generation_metadata.json").write_text(
                to_json_text(
                    {
                        "node_id": "node_2",
                        "title": "Old metadata chapter",
                        "selected_pattern_keys": [],
                        "generation_policy": {"detail_level": "normal"},
                    }
                ),
                encoding="utf-8",
            )

            report = audit_pattern_card_usage(root)
            markdown = render_pattern_card_usage_audit(report)
            paths = write_pattern_card_usage_audit(report, root / "audit")
            self.assertTrue(Path(paths["json"]).exists())

            self.assertEqual(2, report["summary"]["chapter_count"])
            self.assertEqual(1, report["summary"]["chapters_with_prompt_cards"])
            self.assertEqual(1, report["summary"]["prompt_card_actionable_total"])
            self.assertEqual(1, report["summary"]["missing_prompt_card_count"])
            self.assertIn("Write process controls", markdown)
            self.assertIn("pattern_card_usage_audit.json", paths["json"])

    def test_compare_reports_shows_traceability_improvement(self) -> None:
        baseline = {
            "artifact_root": "old",
            "summary": {
                "chapter_count": 2,
                "chapters_with_prompt_cards": 0,
                "prompt_card_total": 0,
                "prompt_card_actionable_total": 0,
                "missing_prompt_card_count": 2,
                "warning_count": 2,
            },
            "items": [
                {"node_id": "node_1", "title": "Craft", "prompt_card_count": 0, "prompt_card_actionable_count": 0, "actionable_count": 1, "audit_status": "warning", "issues": ["missing cards"]},
                {"node_id": "node_2", "title": "Overview", "prompt_card_count": 0, "prompt_card_actionable_count": 0, "actionable_count": 0, "audit_status": "warning", "issues": ["missing cards"]},
            ],
        }
        candidate = {
            "artifact_root": "new",
            "summary": {
                "chapter_count": 2,
                "chapters_with_prompt_cards": 2,
                "prompt_card_total": 4,
                "prompt_card_actionable_total": 1,
                "missing_prompt_card_count": 0,
                "warning_count": 1,
            },
            "items": [
                {"node_id": "node_1", "title": "Craft", "prompt_card_count": 2, "prompt_card_actionable_count": 1, "actionable_count": 1, "audit_status": "warning", "issues": ["needs rewrite"]},
                {"node_id": "node_2", "title": "Overview", "prompt_card_count": 2, "prompt_card_actionable_count": 0, "actionable_count": 0, "audit_status": "passed", "issues": []},
            ],
        }

        comparison = compare_pattern_card_usage_reports(baseline, candidate)
        markdown = render_pattern_card_usage_comparison(comparison)
        with tempfile.TemporaryDirectory() as temp_dir:
            paths = write_pattern_card_usage_comparison(comparison, Path(temp_dir))
            self.assertTrue(Path(paths["json"]).exists())

        self.assertEqual("traceability_improved", comparison["verdict"])
        self.assertEqual(2, comparison["summary_delta"]["chapters_with_prompt_cards_delta"])
        self.assertEqual(-2, comparison["summary_delta"]["missing_prompt_card_count_delta"])
        self.assertIn("Pattern Card Usage Comparison", markdown)
        self.assertIn("traceability_improved", markdown)


if __name__ == "__main__":
    unittest.main()
