from __future__ import annotations

import unittest

from coalplan.application.word_count_targets import estimate_word_count_targets
from coalplan.domain.templates import TemplateNode


class WordCountTargetsTest(unittest.TestCase):
    def test_estimates_from_reference_markdown_title_match(self) -> None:
        node = TemplateNode(
            id="node_overview",
            title="1.1 工程概况",
            level=2,
            source_rules=["工程概况"],
            auto_fill=["整理工程范围"],
            manual_fill=["图纸版本"],
        )
        reference = """# 施工组织设计

## 1.1 工程概况
拉哇水电站位于金沙江上游。本合同工程包括泄洪系统、导流洞、边坡支护、交通洞等施工内容。主要工程量包括土石方明挖、洞挖、混凝土、锚杆、锚索、灌浆等。
"""

        estimates = estimate_word_count_targets([node], reference)

        self.assertEqual("node_overview", estimates[0].node_id)
        self.assertEqual("reference_title_match", estimates[0].method)
        self.assertGreaterEqual(estimates[0].target_word_count, 350)

    def test_fallback_when_reference_missing(self) -> None:
        node = TemplateNode(
            id="node_quality",
            title="质量安全保证措施",
            level=2,
            source_rules=["质量安全"],
            auto_fill=["组织保证措施"],
            manual_fill=["审批要求"],
        )

        estimates = estimate_word_count_targets([node], "")

        self.assertEqual("fallback_by_level_and_title", estimates[0].method)
        self.assertGreaterEqual(estimates[0].target_word_count, 650)


if __name__ == "__main__":
    unittest.main()
