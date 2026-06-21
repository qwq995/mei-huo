from __future__ import annotations

import unittest

from coalplan.infrastructure.validation.markdown_contract import MarkdownContractValidator


class OutputContractTest(unittest.TestCase):
    def test_accepts_valid_chapter_markdown(self) -> None:
        markdown = """# 火区位置

## 主要来源摘要
- 来源：工程概况 > 火区位置；摘要：项目位于矿区北部。
## 生成正文
本节依据投标技术文件整理火区位置，不写入未经核验的坐标。
## 人工补充需补充
- 【需人工补充：火区中心坐标】"""
        result = MarkdownContractValidator().validate(markdown, expected_title="火区位置", source_count=1, missing_items=["火区中心坐标"])
        self.assertTrue(result.passed, result.issues)

    def test_accepts_optional_special_notes(self) -> None:
        markdown = """# 注水工程

## 主要来源摘要
- 来源：施工方案 > 注水工程；摘要：按温度反馈调整注水。
## 生成正文
注水参数应依据现场复核结果确认。
## 人工补充需补充
- 【需人工补充：注水压力和流量】
## 特殊备注
- 注水压力、流量不得脱离现场试验和监测数据。"""
        result = MarkdownContractValidator().validate(markdown, expected_title="注水工程", source_count=1, missing_items=["注水压力和流量"])
        self.assertTrue(result.passed, result.issues)


    def test_accepts_table_source_summary(self) -> None:
        title = "\u5730\u4e0b\u6d1e\u5ba4\u5f00\u6316\u4e0e\u652f\u62a4\u5de5\u7a0b"
        source_heading = "\u4e3b\u8981\u6765\u6e90\u6458\u8981"
        body_heading = "\u751f\u6210\u6b63\u6587"
        manual_heading = "\u4eba\u5de5\u8865\u5145\u9700\u8865\u5145"
        manual_item = "\u3010\u9700\u4eba\u5de5\u8865\u5145\uff1a\u73b0\u573a\u56f4\u5ca9\u7c7b\u522b\u3011"
        markdown = (
            f"# {title}\n\n"
            f"## {source_heading}\n"
            "| evidence_id | section_id | \u4f9d\u636e\u6458\u8981 |\n"
            "| --- | --- | --- |\n"
            "| ev_111111111111 | sec_222222222222 | \u5730\u4e0b\u6d1e\u5ba4\u5f00\u6316\u4e0e\u652f\u62a4\u65bd\u5de5\u4f9d\u636e\u3002 |\n\n"
            f"## {body_heading}\n"
            "\u672c\u7ae0\u4f9d\u636e\u6295\u6807\u6587\u4ef6\u4e2d\u5730\u4e0b\u6d1e\u5ba4\u5f00\u6316\u4e0e\u652f\u62a4\u76f8\u5173\u5185\u5bb9\u7ec4\u7ec7\u6b63\u6587\u3002\n\n"
            f"## {manual_heading}\n"
            f"- {manual_item}"
        )
        result = MarkdownContractValidator().validate(markdown, expected_title=title, source_count=1, missing_items=["现场围岩类别"])
        self.assertTrue(result.passed, result.issues)

    def test_rejects_json_and_missing_contract_parts(self) -> None:
        markdown = '{"title": "火区位置"}'
        result = MarkdownContractValidator().validate(markdown, expected_title="火区位置", source_count=1, missing_items=["坐标"])

        self.assertFalse(result.passed)
        codes = {issue.code for issue in result.issues}
        self.assertIn("json_output", codes)
        self.assertIn("missing_title", codes)
        self.assertIn("missing_required_heading", codes)

    def test_rejects_unexpected_second_level_heading(self) -> None:
        markdown = """# 火区位置

## 主要来源摘要
- 来源：工程概况；摘要：位置说明。
## 生成正文
正文。
## 实施计划
不允许新增模块。
## 人工补充需补充
- 【需人工补充：坐标】"""
        result = MarkdownContractValidator().validate(markdown, expected_title="火区位置", source_count=1, missing_items=["坐标"])
        self.assertFalse(result.passed)
        self.assertIn("unexpected_heading", {issue.code for issue in result.issues})

    def test_rejects_likely_guessed_final_parameter(self) -> None:
        markdown = """# 火区位置

## 主要来源摘要
- 来源：工程概况；摘要：位置说明。
## 生成正文
最终坐标为 123。
## 人工补充需补充
- 【需人工补充：坐标】"""
        result = MarkdownContractValidator().validate(markdown, expected_title="火区位置", source_count=1, missing_items=["坐标"])
        self.assertFalse(result.passed)
        self.assertIn("possible_guessed_fact", {issue.code for issue in result.issues})


if __name__ == "__main__":
    unittest.main()
