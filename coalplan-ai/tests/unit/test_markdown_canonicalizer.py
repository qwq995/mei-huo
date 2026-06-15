from __future__ import annotations

import unittest

from coalplan.infrastructure.markdown.canonicalizer import MarkdownCanonicalizer


class MarkdownCanonicalizerTest(unittest.TestCase):
    def test_drops_toc_noise_and_keeps_tables(self) -> None:
        text = """---
title: demo
---
目录
1.1 火区位置........ 3

#工程概况

| 项目 | 数值 |
| --- | --- |
| 治理面积 | 需复核 |

正文内容


"""

        normalized = MarkdownCanonicalizer().canonicalize(text)

        self.assertNotIn("目录", normalized)
        self.assertNotIn("........", normalized)
        self.assertIn("# 工程概况", normalized)
        self.assertIn("| 治理面积 | 需复核 |", normalized)
        self.assertTrue(normalized.endswith("\n"))


if __name__ == "__main__":
    unittest.main()
