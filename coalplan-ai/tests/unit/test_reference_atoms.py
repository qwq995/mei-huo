from __future__ import annotations

import unittest
import tempfile
from pathlib import Path

from coalplan.application.reference_atom_retrieval import (
    audit_reference_atom_leakage,
    build_reference_leakage_repair_prompt,
    prefilter_reference_atoms,
    render_reference_atoms_for_prompt,
    retrieve_reference_atoms,
)
from coalplan.application.reference_atomization import atomize_reference_markdown, build_reference_blocks
from coalplan.domain.reference_library import (
    AtomRetrievalQuery,
    ReferenceAtom,
    ReferenceDocument,
    ReferenceDocumentKind,
    ReferenceFactVariable,
    ReferenceReviewStatus,
)
from coalplan.infrastructure.database.reference_repository import ReferenceLibraryRepository
from coalplan.infrastructure.database.session import create_session_factory, init_database, sqlite_url_for_storage


class StubStructuredLLM:
    def __init__(self, responses: list[dict | Exception]) -> None:
        self.responses = list(responses)
        self.prompts: list[str] = []

    def complete_json(self, prompt: str, *, schema_name: str) -> dict:
        self.prompts.append(prompt)
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


class ReferenceAtomTests(unittest.TestCase):
    def test_ai_selects_blocks_but_source_text_builds_atom(self) -> None:
        markdown = (
            "# 洞挖专项施工方案\n\n"
            "## 1 工程概况\n\n审批封面。\n\n"
            "## 2 洞身开挖\n\n测量放样后钻孔，采用3台钻机；完成装药联网检查后实施爆破，并组织通风排烟和安全排险。\n\n"
            "## 2.1 质量检查\n\n检查孔位、孔深、周边孔间距及超欠挖情况，检查结果纳入工序验收记录并由现场负责人复核。\n"
        )
        blocks = build_reference_blocks(markdown)
        selected_ids = [blocks[1].block_id, blocks[2].block_id]
        llm = StubStructuredLLM(
            [
                {
                    "atoms": [
                        {
                            "block_ids": selected_ids,
                            "title_path": ["洞身开挖"],
                            "engineering_object": "隧洞",
                            "specialty": "洞挖",
                            "work_item": "钻爆开挖",
                            "process": "钻孔",
                            "process_stage": "开挖与检查",
                            "chapter_type": "施工方法",
                            "content_functions": ["工艺流程", "质量检查"],
                            "applicability": ["钻爆法隧洞"],
                            "prohibited_scenarios": [],
                            "fact_variables": [{"name": "钻机数量", "value": "3台"}],
                            "quality_score": 0.9,
                            "confidence": 0.95,
                        },
                        {
                            "block_ids": selected_ids,
                            "title_path": ["重复标签不应创建第二原子"],
                            "quality_score": 0.8,
                            "confidence": 0.8,
                        },
                    ]
                }
            ]
        )
        document = ReferenceDocument(
            id="ref-1",
            content_hash="hash",
            source_path="sample.md",
            file_name="sample.md",
            project_name="扎拉",
            project_type="水电/导流隧洞/边坡",
            document_kind=ReferenceDocumentKind.special_plan,
        )

        result = atomize_reference_markdown(
            document=document,
            markdown=markdown,
            llm=llm,
            publish_for_validation=True,
        )

        self.assertEqual(result.llm_call_count, 1)
        self.assertEqual(len(result.atoms), 1)
        self.assertIn("测量放样后钻孔", result.atoms[0].content)
        self.assertIn("检查孔位、孔深", result.atoms[0].content)
        self.assertNotIn("审批封面", result.atoms[0].content)
        self.assertEqual(result.atoms[0].status, ReferenceReviewStatus.published)

    def test_ai_rerank_excludes_same_project_and_unpublished_atoms(self) -> None:
        published = _atom("atom-zala", "扎拉", ReferenceReviewStatus.published)
        same_project = _atom("atom-lawa", "拉哇", ReferenceReviewStatus.published)
        draft = _atom("atom-draft", "安化", ReferenceReviewStatus.ai_candidate)
        query = AtomRetrievalQuery(
            project_name="拉哇",
            project_type="水电/泄洪洞",
            chapter_title="洞身开挖",
            evidence_summary="泄洪洞采用钻爆法开挖。",
        )
        self.assertEqual(prefilter_reference_atoms([published, same_project, draft], query), [published])
        llm = StubStructuredLLM(
            [{"selected": [{"atom_id": published.id, "score": 0.88, "match_reason": "工艺相同", "prompt_use": "借鉴检查闭环"}]}]
        )

        results = retrieve_reference_atoms(atoms=[published, same_project, draft], query=query, llm=llm)

        self.assertEqual([item.atom_id for item in results], [published.id])
        self.assertIn("仅为异项目参考", render_reference_atoms_for_prompt(results))

    def test_drill_and_blast_chapter_accepts_drilling_atom(self) -> None:
        atom = _atom("atom-drilling", "扎拉", ReferenceReviewStatus.published)
        atom.title_path = ["洞身开挖施工", "钻孔"]
        atom.work_item = "钻孔"
        atom.process = "钻爆法"
        query = AtomRetrievalQuery(
            project_name="拉哇",
            project_type="水电/泄洪洞",
            chapter_title="测量放样、钻孔与装药爆破",
        )

        self.assertEqual(["atom-drilling"], [item.id for item in prefilter_reference_atoms([atom], query)])

    def test_atomization_retries_smaller_batches_and_keeps_partial_success(self) -> None:
        markdown = (
            "# 洞挖方案\n\n"
            "## 测量钻孔\n\n测量放样后进行钻孔检查，确认孔位、孔深和孔向后进入装药工序。"
            "钻孔过程按分区定人定位实施，检查结果形成工序记录并由现场技术人员复核，"
            "不符合钻爆设计要求的炮孔应重新造孔，经检查合格后方可进入下一工序。\n\n"
            "## 爆破排险\n\n装药联网检查后爆破，通风散烟后检查盲炮和危石，再组织出渣。"
            "爆破后由专业人员先行检查，确认警戒解除条件，并记录异常处置和复查结果。\n"
        )
        blocks = build_reference_blocks(markdown)
        successful_atom = {
            "atoms": [
                {
                    "block_ids": [blocks[0].block_id],
                    "title_path": ["测量钻孔"],
                    "engineering_object": "隧洞",
                    "process": "钻孔",
                    "quality_score": 0.9,
                    "confidence": 0.9,
                }
            ]
        }
        llm = StubStructuredLLM(
            [
                ValueError("truncated JSON"),
                successful_atom,
                ValueError("second half still invalid"),
            ]
        )
        document = ReferenceDocument(
            id="ref-retry",
            content_hash="hash-retry",
            source_path="retry.md",
            file_name="retry.md",
            project_name="重试样例",
            project_type="水电/隧洞",
            document_kind=ReferenceDocumentKind.special_plan,
        )

        result = atomize_reference_markdown(document=document, markdown=markdown, llm=llm)

        self.assertEqual(3, result.llm_call_count)
        self.assertEqual(1, result.failed_batch_count)
        self.assertEqual(1, len(result.atoms))
        self.assertTrue(result.warnings)

    def test_blasting_query_rejects_cross_process_control_loop_analogies(self) -> None:
        blasting = _atom("atom-blasting", "扎拉", ReferenceReviewStatus.published)
        blasting.title_path = ["隧洞开挖", "钻孔装药爆破"]
        blasting.work_item = "钻爆开挖"
        blasting.process = "装药爆破"
        spray = _atom("atom-spray", "安化", ReferenceReviewStatus.published)
        spray.title_path = ["初期支护", "喷射混凝土"]
        spray.work_item = "支护"
        spray.process = "喷射混凝土"
        bleed = _atom("atom-bleed", "卡拉", ReferenceReviewStatus.published)
        bleed.title_path = ["衬砌混凝土", "泌水处理"]
        bleed.work_item = "混凝土浇筑"
        bleed.process = "泌水处理"
        query = AtomRetrievalQuery(
            project_name="拉哇",
            project_type="水电/泄洪洞",
            chapter_title="测量放样、钻孔与装药爆破 / 工艺流程、施工方法与参数控制",
            evidence_summary="采用钻爆法开挖。",
            writing_topics=["炮孔布置", "装药联网", "起爆与爆后检查"],
            top_k=3,
        )

        self.assertEqual(prefilter_reference_atoms([spray, blasting, bleed], query), [blasting])
        llm = StubStructuredLLM(
            [
                {
                    "selected": [
                        {
                            "atom_id": blasting.id,
                            "score": 0.91,
                            "match_reason": "同为隧洞装药爆破工序",
                            "prompt_use": "借鉴钻孔、装药、联网、起爆和爆后检查闭环",
                        }
                    ]
                }
            ]
        )

        results = retrieve_reference_atoms(atoms=[spray, blasting, bleed], query=query, llm=llm)

        self.assertEqual([item.atom_id for item in results], [blasting.id])

    def test_leakage_audit_flags_reference_only_parameter(self) -> None:
        atom = _atom("atom-zala", "扎拉", ReferenceReviewStatus.published)
        atom.fact_variables = [ReferenceFactVariable(name="钻机数量", value="3台")]
        result = type("Result", (), {"atom_id": atom.id, "atom": atom})()

        issues = audit_reference_atom_leakage(
            generated_markdown="配置3台钻机施工。",
            results=[result],
            trusted_project_text="采用钻爆法施工。",
        )

        self.assertTrue(any(issue.value == "3台" for issue in issues))
        prompt = build_reference_leakage_repair_prompt(
            generated_markdown="配置3台钻机施工。",
            issues=issues,
            trusted_project_text="采用钻爆法施工。",
        )
        self.assertIn("unsupported_value=3台", prompt)
        self.assertIn("需人工补充", prompt)

    def test_reference_repository_is_separate_and_round_trips_atoms(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            session_factory = create_session_factory(sqlite_url_for_storage(Path(temp)))
            init_database(session_factory)
            repository = ReferenceLibraryRepository(session_factory)
            document = ReferenceDocument(
                id="ref-1",
                content_hash="hash-1",
                source_path="D:/readonly/source.md",
                file_name="source.md",
                project_name="扎拉",
                project_type="水电/导流隧洞/边坡",
                document_kind=ReferenceDocumentKind.special_plan,
            )
            atom = _atom("atom-zala", "扎拉", ReferenceReviewStatus.published)
            atom.document_id = document.id

            repository.save_document(document)
            repository.replace_document_content(document.id, chapters=[], atoms=[atom])

            loaded = repository.list_atoms(status=ReferenceReviewStatus.published)
            self.assertEqual(len(loaded), 1)
            self.assertEqual(loaded[0].content, atom.content)
            self.assertEqual(repository.get_document(document.id).source_path, "D:/readonly/source.md")


def _atom(atom_id: str, project_name: str, status: ReferenceReviewStatus) -> ReferenceAtom:
    return ReferenceAtom(
        id=atom_id,
        document_id=f"doc-{atom_id}",
        project_name=project_name,
        project_type="水电/导流隧洞/边坡",
        title_path=["洞身开挖"],
        content="测量放样、钻孔、装药、爆破后检查孔位和超欠挖。",
        start_line=10,
        end_line=20,
        work_item="洞身开挖",
        process="钻爆法",
        quality_score=0.9,
        confidence=0.9,
        status=status,
    )


if __name__ == "__main__":
    unittest.main()
