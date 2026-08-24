from __future__ import annotations

import unittest

from coalplan.application.compliance_review import (
    ReviewChapter,
    _deterministic_findings,
    _materialize_findings,
)
from coalplan.domain.standard_constraints import ConstraintAtom, ConstraintSeverity


class ComplianceReviewGuardsTest(unittest.TestCase):
    def test_numeric_lower_bound_is_checked_before_ai_review(self) -> None:
        atom = _atom(review_method="numeric_compare", requirement="作业人员间距不小于5m。")
        chapter = ReviewChapter("node-1", "土方开挖", "version-1", "# 土方开挖\n\n作业人员间距控制为3m。")

        findings, remaining = _deterministic_findings("project-1", "run-1", chapter, [(atom, 0.9, "数值条款")])

        self.assertEqual([], remaining)
        self.assertEqual(1, len(findings))
        self.assertIn("低于条款下限", findings[0].explanation)
        self.assertFalse(findings[0].ai_fixable)

    def test_unverified_model_quote_becomes_manual_confirmation(self) -> None:
        atom = _atom()
        chapter = ReviewChapter("node-1", "施工安全", "version-1", "# 施工安全\n\n已设置警戒。")
        payload = {"violations": [{
            "atom_id": atom.id,
            "verdict": "violated",
            "explanation": "缺少警戒措施。",
            "evidence_quote": "正文中不存在的句子",
            "suggested_fix": "补充措施。",
            "ai_fixable": True,
        }]}

        findings = _materialize_findings("project-1", "run-1", chapter, [(atom, 0.9, "语义匹配")], payload)

        self.assertEqual("needs_confirmation", findings[0].verdict)
        self.assertFalse(findings[0].ai_fixable)
        self.assertEqual("", findings[0].evidence_quote)
        self.assertIn("需人工确认", findings[0].explanation)


def _atom(*, review_method: str = "semantic_review", requirement: str = "爆破作业必须设置警戒。") -> ConstraintAtom:
    return ConstraintAtom(
        id="atom-1",
        document_id="doc-1",
        standard_code="GB 6722",
        standard_name="爆破安全规程",
        clause_no="1.0.1",
        source_text=requirement,
        normalized_requirement=requirement,
        constraint_type="强制性要求",
        review_method=review_method,
        severity=ConstraintSeverity.blocking,
        start_line=1,
        end_line=1,
        confidence=0.9,
    )


if __name__ == "__main__":
    unittest.main()
