from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from coalplan.application.reference_corpus_catalog import (
    build_reference_corpus_catalog,
    write_reference_corpus_catalog,
)
from coalplan.domain.reference_library import KnowledgeRole, ReferenceDocumentKind


class ReferenceCorpusCatalogTests(unittest.TestCase):
    def test_catalog_classifies_atom_sources_and_exact_duplicates(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            project = root / "方案大模型资料" / "方案大模型资料" / "2.扎拉项目部" / "技术方案"
            project.mkdir(parents=True)
            content = (
                "# 导流洞洞挖专项施工方案\n\n"
                "## 工程概况\n\n"
                "## 开挖支护施工\n\n"
                + ("开挖支护施工工艺和质量控制。" * 1000)
            )
            first = project / "导流洞洞挖专项施工方案.md"
            duplicate = root / "施组及专项施工方案" / "导流洞洞挖专项施工方案副本.md"
            duplicate.parent.mkdir(parents=True)
            first.write_text(content, encoding="utf-8")
            duplicate.write_text(content, encoding="utf-8")

            catalog = build_reference_corpus_catalog(root)

            self.assertEqual(catalog.document_count, 2)
            self.assertEqual(catalog.unique_document_count, 1)
            self.assertEqual(catalog.exact_duplicate_count, 1)
            source = next(item for item in catalog.documents if item.exact_duplicate_of is None)
            copied = next(item for item in catalog.documents if item.exact_duplicate_of is not None)
            self.assertEqual(source.document_kind, ReferenceDocumentKind.special_plan)
            self.assertEqual(source.knowledge_role, KnowledgeRole.reference_atom_source)
            self.assertTrue(source.atom_candidate)
            self.assertFalse(copied.atom_candidate)

    def test_catalog_keeps_project_evidence_out_of_atom_pool(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            path = root / "方案大模型资料" / "方案大模型资料" / "10.拉哇项目部" / "招标、合同文件" / "招标文件.md"
            path.parent.mkdir(parents=True)
            path.write_text("# 招标文件\n\n## 工程量清单\n\n" + ("合同工程项目。" * 1000), encoding="utf-8")

            catalog = build_reference_corpus_catalog(root)
            entry = catalog.documents[0]

            self.assertEqual(entry.document_kind, ReferenceDocumentKind.tender_document)
            self.assertEqual(entry.knowledge_role, KnowledgeRole.project_evidence)
            self.assertFalse(entry.atom_candidate)

    def test_document_identity_beats_construction_words_in_body(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            bid = root / "某项目" / "投标文件" / "技术标.md"
            bid.parent.mkdir(parents=True)
            bid.write_text(
                "# 投标技术文件\n\n## 施工组织设计\n\n" + "施工方法与质量控制。" * 6000,
                encoding="utf-8",
            )
            contract = root / "某项目施工分包合同.md"
            contract.write_text(
                "# 合同\n\n## 承包范围\n\n施工组织设计由承包人提交。" + "合同条款。" * 10000,
                encoding="utf-8",
            )

            catalog = build_reference_corpus_catalog(root)

            by_name = {item.file_name: item for item in catalog.documents}
            self.assertEqual(by_name["技术标.md"].document_kind, ReferenceDocumentKind.bid_document)
            self.assertEqual(by_name["某项目施工分包合同.md"].document_kind, ReferenceDocumentKind.contract)
            self.assertFalse(by_name["技术标.md"].atom_candidate)
            self.assertFalse(by_name["某项目施工分包合同.md"].atom_candidate)

    def test_catalog_writes_json_csv_and_markdown(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "corpus"
            root.mkdir()
            (root / "中国安能施工方案编写指南.md").write_text("# 编写指南\n\n## 工艺章节\n\n按流程编写。", encoding="utf-8")
            catalog = build_reference_corpus_catalog(root)

            paths = write_reference_corpus_catalog(catalog, Path(temp) / "output")

            self.assertTrue(Path(paths["json"]).exists())
            self.assertTrue(Path(paths["csv"]).exists())
            self.assertTrue(Path(paths["markdown"]).exists())
            self.assertIn("知识用途", Path(paths["markdown"]).read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
