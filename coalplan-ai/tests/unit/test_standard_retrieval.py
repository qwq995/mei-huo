from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from coalplan.domain.standard_constraints import (
    ConstraintAtom,
    ConstraintReviewStatus,
    ConstraintSeverity,
    StandardDocument,
    StandardDocumentStatus,
)
from coalplan.infrastructure.database.session import create_session_factory, init_database, sqlite_url_for_storage
from coalplan.infrastructure.database.standard_repository import StandardConstraintRepository


class StandardRetrievalTest(unittest.TestCase):
    def test_document_retrieval_limits_ai_candidate_scope_and_atom_retrieval_respects_documents(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            session_factory = create_session_factory(sqlite_url_for_storage(Path(temp_dir)))
            init_database(session_factory)
            repository = StandardConstraintRepository(session_factory)
            relevant = _document("relevant", "水工地下洞室爆破开挖施工安全技术规范")
            unrelated = _document("unrelated", "房屋建筑装饰装修施工规范")
            repository.save_document(relevant)
            repository.save_document(unrelated)
            repository.replace_atoms(relevant.id, [_atom("relevant-atom", relevant.id, "地下洞室爆破作业应设置警戒范围")])
            repository.replace_atoms(unrelated.id, [_atom("unrelated-atom", unrelated.id, "室内装修涂料施工应检查基层")])

            documents = repository.search_document_candidates("地下洞室爆破开挖")
            self.assertIsNotNone(documents)
            self.assertEqual([relevant.id], [item.id for item in documents or []])

            atoms = repository.search_constraint_candidates("爆破作业警戒", {relevant.id})
            self.assertIsNotNone(atoms)
            self.assertEqual(["relevant-atom"], [item.id for item in atoms or []])

    def test_existing_selected_document_is_kept_when_not_in_lexical_candidates(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            session_factory = create_session_factory(sqlite_url_for_storage(Path(temp_dir)))
            init_database(session_factory)
            repository = StandardConstraintRepository(session_factory)
            document = _document("selected", "一份规范")
            repository.save_document(document)
            repository.replace_atoms(document.id, [])
            candidates = repository.search_document_candidates("完全不同的查询词", include_document_ids={document.id})
            self.assertEqual([document.id], [item.id for item in candidates or []])


def _document(document_id: str, name: str) -> StandardDocument:
    return StandardDocument(
        id=document_id,
        standard_code=f"STD-{document_id}",
        name=name,
        category="AI分类",
        disciplines=["水电"],
        project_types=["水电工程"],
        file_name=f"{document_id}.md",
        content_hash=f"hash-{document_id}",
        status=StandardDocumentStatus.ready,
    )


def _atom(atom_id: str, document_id: str, requirement: str) -> ConstraintAtom:
    return ConstraintAtom(
        id=atom_id,
        document_id=document_id,
        standard_name="测试规范",
        source_text=requirement,
        normalized_requirement=requirement,
        constraint_type="安全控制",
        severity=ConstraintSeverity.warning,
        keywords=["爆破", "警戒"] if "爆破" in requirement else ["装修"],
        start_line=1,
        end_line=1,
        status=ConstraintReviewStatus.published,
    )


if __name__ == "__main__":
    unittest.main()
