from __future__ import annotations

import re
import unittest

from coalplan.application.compliance_review import ReviewChapter, match_constraints, match_standard_documents
from coalplan.application.standard_constraint_extraction import classify_standard_sources
from coalplan.domain.standard_constraints import (
    ConstraintAtom,
    ConstraintReviewStatus,
    ConstraintSeverity,
    StandardDocument,
    StandardDocumentStatus,
    StandardMatch,
)


class RecordingAI:
    def __init__(self) -> None:
        self.calls: list[tuple[str, list[str]]] = []

    def complete_json(self, prompt: str, *, schema_name: str) -> dict:
        if schema_name == "standard_document_classification":
            ids = re.findall(r"\[source_id=([^;]+);", prompt)
            self.calls.append((schema_name, ids))
            return {"documents": [{"source_id": item, "category": f"AI分类-{item}", "disciplines": [f"专业-{item}"], "project_types": ["模型项目类型"], "confidence": 0.91} for item in ids]}
        if schema_name == "standard_document_matching":
            ids = re.findall(r"document_id=([^;]+);", prompt)
            self.calls.append((schema_name, ids))
            return {"matches": [{"document_id": item, "applicable": item.endswith("2"), "score": 0.93 if item.endswith("2") else 0.12, "match_reason": f"AI判断-{item}"} for item in ids]}
        if schema_name == "standard_constraint_matching":
            ids = re.findall(r"\[atom_id=([^;]+);", prompt)
            self.calls.append((schema_name, ids))
            selected = ids[-1:] if ids else []
            return {"matches": [{"atom_id": item, "applicable": True, "score": 0.88, "match_reason": "AI语义召回"} for item in selected]}
        return {}


class FailingBatchAI(RecordingAI):
    def complete_json(self, prompt: str, *, schema_name: str) -> dict:
        ids = re.findall(r"\[source_id=([^;]+);", prompt)
        self.calls.append((schema_name, ids))
        if len(ids) > 1:
            raise ValueError("batch response malformed")
        return {"documents": [{"source_id": ids[0], "category": "AI单份恢复", "disciplines": [], "project_types": [], "confidence": 0.8}]}


class OmissionAndMatchingFailureAI(RecordingAI):
    def complete_json(self, prompt: str, *, schema_name: str) -> dict:
        if schema_name == "standard_document_classification":
            ids = re.findall(r"\[source_id=([^;]+);", prompt)
            return {"documents": [{"source_id": ids[0], "category": "AI已分类", "disciplines": [], "project_types": []}]}
        token = "document_id=" if schema_name == "standard_document_matching" else "[atom_id="
        ids = re.findall(r"document_id=([^;]+);", prompt) if token == "document_id=" else re.findall(r"\[atom_id=([^;]+);", prompt)
        self.calls.append((schema_name, ids))
        if len(ids) > 1 or ids[0].endswith("2"):
            raise ValueError("simulated batch failure")
        key = "document_id" if schema_name == "standard_document_matching" else "atom_id"
        return {"matches": [{key: ids[0], "applicable": True, "score": 0.8, "match_reason": "单条恢复"}]}


class AIStandardClassificationMatchingTest(unittest.TestCase):
    def test_document_classification_uses_ai_batches_of_ten(self) -> None:
        llm = RecordingAI()
        sources = [{"source_id": f"s{index}", "file_name": f"规范{index}.md", "markdown": "# 总则\n内容"} for index in range(21)]

        result = classify_standard_sources(sources=sources, llm=llm)

        self.assertEqual([10, 10, 1], [len(ids) for schema, ids in llm.calls if schema == "standard_document_classification"])
        self.assertEqual("AI分类-s7", result["s7"]["category"])
        self.assertEqual(["专业-s7"], result["s7"]["disciplines"])

    def test_failed_classification_batch_is_split_until_each_document_recovers(self) -> None:
        llm = FailingBatchAI()
        sources = [{"source_id": f"s{index}", "file_name": f"规范{index}.md", "markdown": "# 总则"} for index in range(4)]

        result = classify_standard_sources(sources=sources, llm=llm)

        self.assertEqual(4, len(result))
        self.assertTrue(all(item["category"] == "AI单份恢复" for item in result.values()))
        self.assertTrue(any(len(ids) > 1 for _, ids in llm.calls))
        self.assertEqual(4, sum(len(ids) == 1 for _, ids in llm.calls))

    def test_document_and_clause_matching_follow_ai_results_and_preserve_user_decision(self) -> None:
        llm = RecordingAI()
        documents = [_document("doc1"), _document("doc2")]
        matches = match_standard_documents(
            documents=documents,
            project_text="上下文故意不包含任何规范名称",
            llm=llm,
            existing_matches=[StandardMatch(document_id="doc2", score=0.2, match_reason="用户曾排除", decision="excluded")],
        )
        by_id = {item.document_id: item for item in matches}
        self.assertEqual("suggested", by_id["doc1"].decision)
        self.assertEqual("excluded", by_id["doc2"].decision)
        self.assertEqual("AI判断-doc2", by_id["doc2"].match_reason)

        atoms = [_atom("atom1", "doc2"), _atom("atom2", "doc2")]
        selected = match_constraints(
            atoms=atoms,
            chapter=ReviewChapter(node_id="n1", title="无词语重合章节", version_id="v1", markdown="正文也无重合"),
            llm=llm,
        )
        self.assertEqual(["atom2"], [item[0].id for item in selected])
        self.assertEqual("AI语义召回", selected[0][2])

    def test_ai_omission_and_failed_match_batches_keep_partial_results(self) -> None:
        llm = OmissionAndMatchingFailureAI()
        classified = classify_standard_sources(
            sources=[
                {"source_id": "s1", "file_name": "规范1.md", "markdown": "# 总则"},
                {"source_id": "s2", "file_name": "规范2.md", "markdown": "# 总则"},
            ],
            llm=llm,
        )
        self.assertEqual("AI已分类", classified["s1"]["category"])
        self.assertEqual("其他", classified["s2"]["category"])
        self.assertIn("未返回", classified["s2"]["classification_warning"])

        warnings: list[str] = []
        matches = match_standard_documents(
            documents=[_document("doc1"), _document("doc2")],
            project_text="项目上下文",
            llm=llm,
            warnings=warnings,
        )
        by_id = {item.document_id: item for item in matches}
        self.assertEqual("selected", by_id["doc1"].decision)
        self.assertEqual("suggested", by_id["doc2"].decision)
        self.assertTrue(any("人工确认" in item for item in warnings))

        warnings.clear()
        selected = match_constraints(
            atoms=[_atom("atom1", "doc1"), _atom("atom2", "doc2")],
            chapter=ReviewChapter(node_id="n1", title="章节", version_id="v1", markdown="正文"),
            llm=llm,
            warnings=warnings,
        )
        self.assertEqual(["atom1"], [item[0].id for item in selected])
        self.assertTrue(any("已跳过" in item for item in warnings))


def _document(document_id: str) -> StandardDocument:
    return StandardDocument(
        id=document_id,
        standard_code=document_id.upper(),
        name=f"规范 {document_id}",
        category="AI分类",
        file_name=f"{document_id}.md",
        content_hash=f"hash-{document_id}",
        status=StandardDocumentStatus.ready,
    )


def _atom(atom_id: str, document_id: str) -> ConstraintAtom:
    return ConstraintAtom(
        id=atom_id,
        document_id=document_id,
        standard_name="测试规范",
        source_text="一条与章节字面无关的约束原文",
        normalized_requirement="由模型决定是否匹配",
        constraint_type="一般技术要求",
        severity=ConstraintSeverity.warning,
        start_line=1,
        end_line=1,
        confidence=0.9,
        status=ConstraintReviewStatus.published,
    )


if __name__ == "__main__":
    unittest.main()
