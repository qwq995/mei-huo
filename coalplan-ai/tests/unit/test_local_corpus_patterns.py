from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from coalplan.application.local_corpus_patterns import (
    analyze_local_corpus,
    build_pattern_library_from_analysis,
    extract_body_cues,
    extract_file_metadata,
    extract_headings,
)


class LocalCorpusPatternsTest(unittest.TestCase):
    def test_extract_file_metadata_from_local_corpus_header(self) -> None:
        metadata = extract_file_metadata(
            "\n".join(
                [
                    r"源文件：D:\Task\方案大模型资料\施工组织设计.pdf",
                    "文件类型：.pdf",
                    "分类：正文施组",
                    "提取状态：从目录页抽取",
                    "目录结构：",
                ]
            )
        )

        self.assertEqual(r"D:\Task\方案大模型资料\施工组织设计.pdf", metadata["source_file"])
        self.assertEqual("从目录页抽取", metadata["extraction_status"])

    def test_extract_body_cues_for_craft_and_safety_patterns(self) -> None:
        craft_cues = extract_body_cues("施工准备完成后进行测量放样，按施工工艺流程组织施工，完成后进行质量检查和验收。", "craft")
        safety_cues = extract_body_cues("现场开展安全技术交底，识别危险源，配置消防和临时用电专项措施，并按应急流程响应。", "safety")

        self.assertTrue(any("工艺正文" in item for item in craft_cues))
        self.assertTrue(any("安全正文" in item for item in safety_cues))

    def test_extract_headings_from_numbered_text(self) -> None:
        text = "\n".join(
            [
                "目录结构：",
                "第一章 工程概况",
                "1.1 主要工程量",
                "1.2 施工条件",
                "这是普通正文，不应作为标题。",
                "第二章 施工进度计划",
            ]
        )

        headings = extract_headings(text)

        self.assertIn("工程概况", headings)
        self.assertIn("主要工程量", headings)
        self.assertIn("施工进度计划", headings)

    def test_analyze_local_corpus_and_build_pattern_library(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "煤火治理施工组织设计.txt").write_text(
                "\n".join(
                    [
                        "目录结构：",
                        "第一章 工程概况",
                        "1.1 主要工程量",
                        "第二章 钻孔与灌浆施工方法",
                        "2.1 施工工艺流程",
                        "第三章 安全保证措施",
                    ]
                ),
                encoding="utf-8",
            )
            (root / "市政雨污管网施工组织设计.txt").write_text(
                "\n".join(
                    [
                        "目录结构：",
                        "第一章 施工部署",
                        "第二章 施工进度计划",
                        "第三章 质量保证体系",
                        "第四章 环境保护及文明施工措施",
                    ]
                ),
                encoding="utf-8",
            )

            analysis = analyze_local_corpus(root)
            library = build_pattern_library_from_analysis(analysis)

        self.assertEqual(2, analysis.sample_count)
        self.assertIn(analysis.corpus_content_kind, {"toc_extraction", "text_extraction"})
        self.assertIn("section_id/evidence_id", analysis.evidence_scope)
        self.assertEqual(1, analysis.project_type_counts["煤火治理"])
        self.assertGreaterEqual(analysis.pattern_stats["craft"].file_count, 1)
        self.assertGreaterEqual(analysis.pattern_stats["craft"].body_excerpt_count, 1)
        self.assertTrue(analysis.pattern_stats["craft"].common_body_cues)
        self.assertGreaterEqual(analysis.pattern_stats["quality"].file_count, 1)
        self.assertIn("本地语料样本数：2", library.patterns["craft"].corpus_basis)
        self.assertIn("钻孔与灌浆施工方法", library.patterns["craft"].corpus_common_headings)
        self.assertIn("质量保证体系", library.patterns["quality"].corpus_common_headings)

        self.assertIn("按来源中的工艺流程和施工程序组织实施步骤。", library.patterns["craft"].auto_writable_moves)
        self.assertTrue(any("正文样本" in item for item in library.patterns["craft"].auto_writable_moves))
        self.assertIn("施工顺序", library.patterns["craft"].required_source_facts)


if __name__ == "__main__":
    unittest.main()
