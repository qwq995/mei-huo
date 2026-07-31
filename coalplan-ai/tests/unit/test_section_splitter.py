from __future__ import annotations

import unittest

from coalplan.infrastructure.markdown.section_splitter import MarkdownSectionSplitter
from coalplan.infrastructure.markdown.canonicalizer import MarkdownCanonicalizer


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

    def test_repeated_heading_paths_receive_unique_stable_ids(self) -> None:
        markdown = """# 第一卷 商务文件
第一处正文。

# 第一卷 商务文件
第二处正文。
"""
        splitter = MarkdownSectionSplitter()

        first = splitter.split_sections(markdown, source_file="招标文件.md")
        second = splitter.split_sections(markdown, source_file="招标文件.md")

        self.assertEqual(2, len(first))
        self.assertEqual(2, len({item.id for item in first}))
        self.assertEqual([item.id for item in first], [item.id for item in second])

    def test_quantity_line_is_not_treated_as_parent_heading(self) -> None:
        markdown = """# 第九章 技术条款

8 线：110kV输电线路。

9.1.3 承包人负责的工作
承包人应完成施工测量。
"""

        sections = MarkdownSectionSplitter().split_sections(markdown, source_file="招标文件.md")
        paths = [section.title_path for section in sections]

        self.assertFalse(any(any(title.startswith("8 线") for title in path) for path in paths))
        clause = next(section for section in sections if section.title_path[-1].startswith("9.1.3"))
        self.assertEqual(["第九章 技术条款", "9.1.3 承包人负责的工作"], clause.title_path)

    def test_canonicalized_compact_quantity_heading_is_not_a_parent(self) -> None:
        markdown = """# 第九章 技术条款

#8线：110kV施工线路。

#1-2线：110kV备用施工线路。

9.1.3 承包人负责的工作
承包人应完成施工测量。
"""
        normalized = MarkdownCanonicalizer().canonicalize(markdown)

        sections = MarkdownSectionSplitter().split_sections(normalized, source_file="招标文件.md")
        clause = next(section for section in sections if section.title_path[-1].startswith("9.1.3"))

        self.assertEqual(["第九章 技术条款", "9.1.3 承包人负责的工作"], clause.title_path)
        self.assertFalse(any(any(title.startswith("1-2线") for title in item.title_path) for item in sections))


if __name__ == "__main__":
    unittest.main()
