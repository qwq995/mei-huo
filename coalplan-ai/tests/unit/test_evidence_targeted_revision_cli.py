from __future__ import annotations

import unittest

from tools.run_evidence_targeted_revision import _audit_delta, _audit_summary


class EvidenceTargetedRevisionCliTest(unittest.TestCase):
    def test_audit_summary_and_delta_show_resolved_omitted_facts(self) -> None:
        before = {
            "coverage_ratio": 0.2,
            "required_source_facts": [
                {
                    "fact_id": "ev_1:fact_1",
                    "evidence_id": "ev_1",
                    "section_id": "sec_1",
                    "fact_type": "parameter",
                    "text": "注水压力 0.2 - 0.3MPa。",
                },
                {
                    "fact_id": "ev_2:fact_1",
                    "evidence_id": "ev_2",
                    "section_id": "sec_2",
                    "fact_type": "quantity",
                    "text": "降温注水 3.8 万立方米。",
                },
            ],
            "omitted_required_fact_ids": ["ev_1:fact_1", "ev_2:fact_1"],
            "unused_high_value_evidence_ids": ["ev_1", "ev_2"],
            "issues": [{"code": "omitted_required_source_facts"}],
        }
        after = {
            "coverage_ratio": 0.8,
            "required_source_facts": before["required_source_facts"],
            "omitted_required_fact_ids": ["ev_2:fact_1"],
            "unused_high_value_evidence_ids": ["ev_2"],
            "issues": [{"code": "omitted_required_source_facts"}],
        }

        summary = _audit_summary(before)
        delta = _audit_delta(before, after)

        self.assertEqual(2, summary["omitted_required_fact_count"])
        self.assertIn("omitted_required_source_facts", summary["issue_codes"])
        self.assertEqual(["ev_1:fact_1"], delta["resolved_required_fact_ids"])
        self.assertEqual(["ev_1"], delta["resolved_unused_evidence_ids"])
        self.assertEqual(0.2, delta["coverage_ratio_before"])
        self.assertEqual(0.8, delta["coverage_ratio_after"])


if __name__ == "__main__":
    unittest.main()
