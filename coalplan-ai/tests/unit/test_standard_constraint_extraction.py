from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from coalplan.application.standard_constraint_extraction import build_standard_blocks, extract_standard_constraints, infer_standard_metadata
from coalplan.domain.standard_constraints import ConstraintReviewStatus, StandardDocumentStatus
from coalplan.infrastructure.database.session import create_session_factory, init_database, sqlite_url_for_storage
from coalplan.infrastructure.database.standard_repository import StandardConstraintRepository
from coalplan.infrastructure.llm.fake_llm import FakeLLMClient


SAMPLE = """# 水工建筑物地下开挖工程施工技术规范

## 1 总则

1.1.1 地下开挖施工不应欠挖。

1.1.2 开挖前应编制施工方案，并履行审批手续。

## 2 质量检查

2.1.1 检查结果必须形成记录并由监理工程师复核。
"""


class StandardConstraintExtractionTest(unittest.TestCase):
    def test_incomplete_markdown_is_kept_as_partial_with_actionable_warning(self) -> None:
        result = extract_standard_constraints(
            file_name="封面页规范.md",
            markdown="# 工程建设标准\n\n发布单位：测试单位",
            source_path="D:/standards/cover-only.md",
            llm=FakeLLMClient(),
        )

        self.assertEqual(StandardDocumentStatus.partial, result.document.status)
        self.assertEqual([], result.atoms)
        self.assertTrue(any("转换不完整" in item for item in result.warnings))

    def test_underscore_standard_code_and_toc_entries_are_handled(self) -> None:
        markdown = """# 水电工程安全技术规程

DL/T 5371-2017

## 目 次

4.8 预应力锚固工程 62

## 施工安全

4.8.1 施工前必须检查作业条件。
"""
        metadata = infer_standard_metadata("DL_T 5371-2017 水电工程安全技术规程.md", markdown)
        blocks = build_standard_blocks(markdown)
        result = extract_standard_constraints(
            file_name="DL_T 5371-2017 水电工程安全技术规程.md",
            markdown=markdown,
            source_path="D:/standards/DL_T 5371-2017.md",
            llm=FakeLLMClient(),
            metadata={**metadata, "category": "安全"},
        )

        self.assertEqual("DL/T 5371-2017", metadata["standard_code"])
        self.assertTrue(any(block.clause_no == "4.8" for block in blocks))
        self.assertEqual(["4.8.1"], [atom.clause_no for atom in result.atoms])

    def test_single_document_is_classified_and_split_into_traceable_atoms(self) -> None:
        metadata = infer_standard_metadata("DL_T 5099-2011 水工建筑物地下开挖工程施工技术规范.md", SAMPLE)
        self.assertEqual("未分类", metadata["category"])
        self.assertEqual([], metadata["disciplines"])
        blocks = build_standard_blocks(SAMPLE)
        self.assertEqual(["1.1.1", "1.1.2", "2.1.1"], [item.clause_no for item in blocks])

        result = extract_standard_constraints(
            file_name="DL_T 5099-2011 水工建筑物地下开挖工程施工技术规范.md",
            markdown=SAMPLE,
            source_path="D:/standards/DL_T 5099.md",
            llm=FakeLLMClient(),
        )

        self.assertEqual(3, len(result.atoms))
        self.assertEqual("施工技术", result.document.category)
        self.assertIn("地下工程", result.document.disciplines)
        self.assertTrue(all(atom.source_text in SAMPLE for atom in result.atoms))
        self.assertTrue(all(atom.status == ConstraintReviewStatus.published for atom in result.atoms))
        self.assertFalse(hasattr(result.atoms[0], "stage"))
        self.assertEqual("禁止性要求", result.atoms[0].constraint_type)

    def test_repository_round_trips_one_document_and_its_constraint_set(self) -> None:
        result = extract_standard_constraints(
            file_name="SL 999-2026 地下工程施工规范.md",
            markdown=SAMPLE,
            source_path="sample.md",
            llm=FakeLLMClient(),
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            session_factory = create_session_factory(sqlite_url_for_storage(Path(temp_dir)))
            init_database(session_factory)
            repository = StandardConstraintRepository(session_factory)
            repository.save_document(result.document)
            repository.replace_atoms(result.document.id, result.atoms)

            loaded = repository.get_document(result.document.id)
            atoms = repository.list_atoms(document_id=loaded.id, status=ConstraintReviewStatus.published)
            self.assertEqual(len(result.atoms), loaded.atom_count)
            self.assertEqual([item.clause_no for item in result.atoms], [item.clause_no for item in atoms])


if __name__ == "__main__":
    unittest.main()
