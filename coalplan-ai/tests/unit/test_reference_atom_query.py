from __future__ import annotations

import unittest

from coalplan.application.reference_atom_query import classify_atom_retrieval_query
from coalplan.domain.reference_library import AtomRetrievalQuery


class StubLLM:
    def complete_json(self, prompt: str, *, schema_name: str) -> dict:
        return {
            "chapter_module": "process_technology",
            "engineering_system": "underground_tunnel",
            "engineering_object": "隧洞开挖断面",
            "process_family": "drilling_blasting",
            "process_stage": "parameter_control",
            "content_functions": ["workflow", "parameter", "quality_control"],
            "applicability": ["岩石隧洞"],
            "confidence": 0.94,
            "reason": "当前章节要求编写隧洞钻爆参数与控制方法",
        }


class ReferenceAtomQueryTests(unittest.TestCase):
    def test_ai_fills_missing_labels_but_keeps_confirmed_fields(self) -> None:
        query = AtomRetrievalQuery(
            project_name="当前项目", project_type="水电工程", chapter_title="洞身开挖",
            parent_titles=["主要施工方案"], engineering_object="用户确认的泄洪洞",
            evidence_summary="采用钻爆法开挖。", writing_topics=["炮孔参数", "爆后检查"],
        )
        result = classify_atom_retrieval_query(query, llm=StubLLM())
        self.assertEqual("drilling_blasting", result.query.process_family)
        self.assertEqual("underground_tunnel", result.query.engineering_system)
        self.assertEqual("用户确认的泄洪洞", result.query.engineering_object)
        self.assertIn("parameter", result.query.content_functions)


if __name__ == "__main__":
    unittest.main()
