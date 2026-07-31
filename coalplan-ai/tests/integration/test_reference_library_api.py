from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path

import httpx

from coalplan.domain.reference_library import (
    ReferenceAtom,
    ReferenceDocument,
    ReferenceDocumentKind,
    ReferenceReviewStatus,
)
from coalplan.main import create_app
from coalplan.settings import Settings


class ReferenceLibraryApiTest(unittest.TestCase):
    def test_swagger_lists_reference_library_and_status_can_be_reviewed(self) -> None:
        asyncio.run(self._run_flow())

    async def _run_flow(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            app = create_app(Settings(storage_dir=Path(temp_dir), llm_provider="fake"))
            library = app.state.reference_library
            document = ReferenceDocument(
                id="ref-api",
                content_hash="hash-api",
                source_path="D:/readonly/example.md",
                file_name="example.md",
                project_name="扎拉",
                project_type="水电/导流隧洞/边坡",
                document_kind=ReferenceDocumentKind.special_plan,
            )
            atom = ReferenceAtom(
                id="atom-api",
                document_id=document.id,
                project_name=document.project_name,
                project_type=document.project_type,
                title_path=["洞身开挖"],
                content="测量放样后钻孔，爆破通风后检查并组织出渣和初期支护。",
                start_line=10,
                end_line=20,
                quality_score=0.9,
                confidence=0.9,
            )
            library.save_document(document)
            library.replace_document_content(document.id, chapters=[], atoms=[atom])

            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
                openapi = (await client.get("/openapi.json")).json()
                self.assertIn("/reference-library/import-ai", openapi["paths"])
                self.assertIn("/reference-library/retrieve", openapi["paths"])
                self.assertIn("/reference-library/upload-markdown", openapi["paths"])

                documents = await client.get("/reference-library/documents")
                self.assertEqual(200, documents.status_code)
                self.assertEqual(documents.json()[0]["id"], document.id)

                updated = await client.patch(
                    f"/reference-library/atoms/{atom.id}/status",
                    json={"status": ReferenceReviewStatus.published.value},
                )
                self.assertEqual(200, updated.status_code)
                self.assertEqual(updated.json()["status"], ReferenceReviewStatus.published.value)

                atoms = await client.get(
                    "/reference-library/atoms",
                    params={"status": ReferenceReviewStatus.published.value},
                )
                self.assertEqual([item["id"] for item in atoms.json()], [atom.id])

                summary = await client.get("/reference-library/summary")
                self.assertEqual(200, summary.status_code)
                self.assertEqual(1, summary.json()["published_count"])
                self.assertIn("workflow", summary.json())

                uploaded = await client.post(
                    "/reference-library/upload-markdown",
                    json={
                        "file_name": "优秀洞挖施组.md",
                        "content": "# 洞挖施工\n\n## 钻孔爆破\n测量放样、钻孔、装药、联网、爆破后通风检查。",
                        "project_name": "示例水电站",
                        "project_type": "水电/隧洞",
                        "max_batches": 1,
                    },
                )
                self.assertEqual(200, uploaded.status_code)
                self.assertIn("candidate_count", uploaded.json())
                self.assertTrue(Path(uploaded.json()["document"]["source_path"]).exists())


if __name__ == "__main__":
    unittest.main()
