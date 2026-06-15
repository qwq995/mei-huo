from __future__ import annotations

import unittest

from coalplan.infrastructure.markdown.section_splitter import MarkdownSectionSplitter


class MarkdownSectionSplitterTest(unittest.TestCase):
    def test_splits_fire_treatment_sections_with_keywords(self) -> None:
        markdown = """# 工程概况
火区位于矿区北部，交通依托既有道路。

## 火区勘查
存在高温、裂隙、塌陷及烟气异常。

3.2.1 注水工程施工
采用分区注水降温，结合温度反馈调整。

3.2.2 钻孔与灌、注浆工程施工
钻孔、洗孔、压水试验、制浆和注浆依次实施。

3.2.3 覆盖封堵工程
清表整形、分层回填、碾压及黄土覆盖。
"""

        sections = MarkdownSectionSplitter().split_sections(markdown, source_file="bid.md")
        titles = [" > ".join(section.title_path) for section in sections]

        self.assertTrue(any("火区勘查" in title for title in titles))
        self.assertTrue(any("注水工程施工" in title for title in titles))
        self.assertTrue(any("钻孔与灌、注浆工程施工" in title for title in titles))
        self.assertTrue(any("覆盖封堵工程" in title for title in titles))
        self.assertTrue(any("注水" in section.keywords for section in sections))
        self.assertTrue(any("灌浆" in section.keywords or "注浆" in section.keywords for section in sections))


if __name__ == "__main__":
    unittest.main()
