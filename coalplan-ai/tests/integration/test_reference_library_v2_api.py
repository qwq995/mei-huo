from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path

import httpx

from coalplan.application.reference_atom_v2 import finalize_v2_atom
from coalplan.domain.reference_library import ReferenceAtom, ReferenceDocument, ReferenceDocumentKind, ReferenceReviewStatus
from coalplan.main import create_app
from coalplan.settings import Settings


class ReferenceLibraryV2ApiTest(unittest.TestCase):
    def test_bulk_publish_gate_and_hybrid_retrieval_preview(self) -> None:
        asyncio.run(self._run_flow())

    async def _run_flow(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            app = create_app(Settings(storage_dir=Path(temp_dir), llm_provider="fake"))
            library = app.state.reference_library
            document = ReferenceDocument(
                id="doc-v2-api", content_hash="hash-v2-api", source_path="D:/source.md", file_name="source.md",
                project_name="历史水电项目", project_type="水电/隧洞", document_kind=ReferenceDocumentKind.construction_organization,
            )
            valid = finalize_v2_atom(ReferenceAtom(
                id="atom-v2-valid", document_id=document.id, project_name=document.project_name,
                project_type=document.project_type, title_path=["施工技术", "钻孔爆破"],
                content="测量放样后进行钻孔，装药前检查炮孔，联网复核后起爆；通风排烟结束后检查盲炮、危石和超欠挖，异常处置完成并复查合格后组织出渣，全部检查结果形成工序记录。交接前由现场技术人员复核记录完整性和下一工序作业条件。",
                raw_excerpt="测量放样后进行钻孔，装药前检查炮孔，联网复核后起爆；通风排烟结束后检查盲炮、危石和超欠挖，异常处置完成并复查合格后组织出渣，全部检查结果形成工序记录。交接前由现场技术人员复核记录完整性和下一工序作业条件。",
                start_line=10, end_line=20, atom_type="process", chapter_module="process_technology",
                engineering_system="underground_tunnel", engineering_object="隧洞", process_family="钻孔爆破",
                process_stage="main_operation", content_functions=["workflow", "inspection", "record"],
                quality_score=0.9, confidence=0.9, status=ReferenceReviewStatus.pending_publish,
            ))
            blocked = finalize_v2_atom(ReferenceAtom(
                id="atom-v2-blocked", document_id=document.id, project_name=document.project_name,
                project_type=document.project_type, title_path=["零散文字"],
                content="做好施工准备并加强检查。", start_line=30, end_line=30,
            ))
            library.save_document(document)
            library.replace_document_content(document.id, chapters=[], atoms=[valid, blocked])

            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
                result = await client.post(
                    "/reference-library/atoms/bulk-publish",
                    json={"atom_ids": [valid.id, blocked.id]},
                )
                self.assertEqual(200, result.status_code)
                self.assertEqual([valid.id], result.json()["published"])
                self.assertEqual(blocked.id, result.json()["blocked"][0]["atom_id"])

                retrieved = await client.post(
                    "/reference-library/retrieve-v2",
                    json={
                        "project_name": "当前工程", "project_type": "水电/隧洞", "chapter_title": "钻孔爆破施工",
                        "chapter_module": "process_technology", "engineering_system": "underground_tunnel",
                        "engineering_object": "隧洞", "process_family": "钻孔爆破",
                        "content_functions": ["workflow", "inspection"], "top_k": 3,
                    },
                )
                self.assertEqual(200, retrieved.status_code)
                self.assertEqual(valid.id, retrieved.json()[0]["atom"]["id"])
                self.assertIn("工艺族一致", retrieved.json()[0]["match_reasons"])

                searched = await client.get(
                    "/reference-library/atoms/search",
                    params={"query": "通风排烟", "status": "published", "page": 1, "page_size": 1},
                )
                self.assertEqual(200, searched.status_code)
                self.assertEqual(1, searched.json()["total"])
                self.assertEqual(valid.id, searched.json()["items"][0]["id"])
                self.assertFalse(searched.json()["has_more"])

                query = type("Query", (), {
                    "project_name": "当前工程", "excluded_project_names": [],
                    "chapter_module": "process_technology", "engineering_system": "underground_tunnel",
                    "process_family": "钻孔爆破",
                })()
                candidates = library.list_v2_retrieval_candidates(query, limit=10)
                self.assertEqual([valid.id], [item.id for item in candidates])


if __name__ == "__main__":
    unittest.main()
