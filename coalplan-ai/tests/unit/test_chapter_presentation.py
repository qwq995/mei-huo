import unittest

from coalplan.application.chapter_presentation import editable_chapter_markdown


class ChapterPresentationTests(unittest.TestCase):
    def test_extracts_editable_body_from_generation_contract(self):
        markdown = """# 灌浆施工

## 主要来源摘要
- evidence_id: ev_1

## 生成正文
### 施工流程
正文内容（atom_id=atom_1）。

## 人工补充需补充
- 【需人工补充：现场压力】
"""

        result = editable_chapter_markdown(markdown)

        self.assertEqual("# 灌浆施工\n\n### 施工流程\n正文内容。\n", result)
        self.assertNotIn("evidence_id", result)
        self.assertNotIn("人工补充", result)

    def test_keeps_plain_user_markdown_editable(self):
        markdown = "# 灌浆施工\n\n## 工艺流程\n按方案组织施工。\n"
        self.assertEqual(markdown, editable_chapter_markdown(markdown))

    def test_supplies_expected_title_when_model_omits_it(self):
        result = editable_chapter_markdown("正文内容。", expected_title="孔口管安装")
        self.assertEqual("# 孔口管安装\n\n正文内容。\n", result)


if __name__ == "__main__":
    unittest.main()
