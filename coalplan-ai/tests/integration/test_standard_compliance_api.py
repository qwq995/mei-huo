from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path

import httpx

from coalplan.domain.standard_constraints import ComplianceFinding, ConstraintSeverity
from coalplan.main import create_app
from coalplan.settings import Settings


STANDARD_MD = """# 水工建筑物地下开挖工程施工技术规范

## 1 地下开挖

1.1.1 地下开挖施工不应欠挖施工。
"""


class StandardComplianceApiTest(unittest.TestCase):
    def test_import_match_review_and_ai_repair_flow(self) -> None:
        asyncio.run(self._run_flow())

    async def _run_flow(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            app = create_app(Settings(storage_dir=Path(temp_dir), llm_provider="fake"))
            pipeline = app.state.pipeline
            project = pipeline.create_project("水电地下开挖规范审查", template_id="coal_fire")
            pipeline.ingest_bid_markdown(project.id, file_name="bid.md", content="# 工程概况\n本工程为水电地下洞室爆破开挖工程。")
            pipeline.prepare_directory(project.id)
            node = next(
                (item for item in pipeline.workspace_store.list_outline_nodes(project.id) if "爆破" in item["title"] or "开挖" in item["title"]),
                pipeline.workspace_store.list_outline_nodes(project.id)[0],
            )
            version = pipeline.workspace_store.create_chapter_version(
                project.id,
                node["node_id"],
                title=node["title"],
                markdown=f"# {node['title']}\n\n## 施工方法\n地下开挖采用欠挖施工。",
                source_type="manual",
                created_by="user",
                select=True,
            )
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
                batch_imported = await client.post(
                    "/standards/import-batch",
                    json={
                        "files": [
                            {"file_name": "SL 303-2017 施工组织设计规范.md", "content": "# 总则\n1.0.1 施工组织设计应结合工程实际。"},
                            {"file_name": "GB 6722-2014 爆破安全规程.md", "content": "# 爆破安全\n1.0.1 爆破作业必须设置警戒。"},
                        ],
                        "max_batches_per_document": 1,
                    },
                )
                self.assertEqual(200, batch_imported.status_code, batch_imported.text)
                self.assertEqual(2, batch_imported.json()["completed_count"])
                self.assertEqual(1, batch_imported.json()["classification_batch_count"])
                self.assertTrue(all(Path(item["document"]["source_path"]).is_file() for item in batch_imported.json()["results"]))

                imported = await client.post(
                    "/standards/import-markdown",
                    json={"file_name": "DL_T 5099-2011 水工建筑物地下开挖工程施工技术规范.md", "content": STANDARD_MD},
                )
                self.assertEqual(200, imported.status_code, imported.text)
                self.assertEqual(1, imported.json()["constraint_count"])

                classified = await client.post("/standards/classify-batch", json={"document_ids": [imported.json()["document"]["id"]]})
                self.assertEqual(200, classified.status_code, classified.text)
                self.assertEqual(1, classified.json()["document_count"])
                self.assertEqual(1, classified.json()["classification_batch_count"])

                matched = await client.post(f"/standards/projects/{project.id}/match")
                self.assertEqual(200, matched.status_code, matched.text)
                self.assertEqual("selected", matched.json()[0]["decision"])

                preview = await client.post(f"/standards/projects/{project.id}/chapters/{node['node_id']}/constraint-matches")
                self.assertEqual(200, preview.status_code, preview.text)
                self.assertGreaterEqual(len(preview.json()["matches"]), 1)
                self.assertTrue(any(item["atom"]["clause_no"] == "1.1.1" for item in preview.json()["matches"]))

                job = await client.post(
                    f"/projects/{project.id}/jobs",
                    json={"job_type": "compliance_review", "payload": {}},
                )
                self.assertEqual(202, job.status_code, job.text)
                job_result = None
                for _ in range(80):
                    polled = await client.get(f"/projects/{project.id}/jobs/{job.json()['job_id']}")
                    job_result = polled.json()
                    if job_result["status"] in {"completed", "partial", "failed"}:
                        break
                    await asyncio.sleep(0.05)
                self.assertEqual("completed", job_result["status"], job_result)
                self.assertEqual(1, job_result["result"]["finding_count"])

                reviewed = await client.post(f"/standards/projects/{project.id}/review")
                self.assertEqual(200, reviewed.status_code, reviewed.text)
                self.assertEqual(1, reviewed.json()["finding_count"])
                run_id = reviewed.json()["run"]["id"]
                self.assertEqual("completed", reviewed.json()["run"]["status"])
                finding = reviewed.json()["findings"][0]
                self.assertEqual("1.1.1", finding["clause_no"])
                self.assertIn("欠挖", finding["constraint_text"])
                self.assertFalse(finding["ai_fixable"])

                run_detail = await client.get(f"/standards/projects/{project.id}/review-runs/{run_id}")
                self.assertEqual(200, run_detail.status_code, run_detail.text)
                self.assertEqual(1, len(run_detail.json()["findings"]))
                self.assertGreaterEqual(len(run_detail.json()["constraint_matches"]), 1)

                resolved = await client.patch(
                    f"/standards/projects/{project.id}/findings/{finding['id']}",
                    json={"status": "manually_resolved", "note": "用户已调整施工方法"},
                )
                self.assertEqual("manually_resolved", resolved.json()["status"])

                repairable = ComplianceFinding(
                    id="finding-ai-fix",
                    project_id=project.id,
                    node_id=node["node_id"],
                    chapter_title=node["title"],
                    chapter_version_id=version["id"],
                    atom_id=finding["atom_id"],
                    document_id=finding["document_id"],
                    standard_code=finding["standard_code"],
                    standard_name=finding["standard_name"],
                    clause_no=finding["clause_no"],
                    constraint_text=finding["constraint_text"],
                    severity=ConstraintSeverity.warning,
                    verdict="violated",
                    explanation="正文控制措施不完整",
                    ai_fixable=True,
                    suggested_fix="补充已有依据支持的检查步骤",
                )
                app.state.standard_constraints.save_findings([repairable])
                repaired = await client.post(f"/standards/projects/{project.id}/findings/{repairable.id}/ai-fix")
                self.assertEqual(200, repaired.status_code, repaired.text)
                self.assertEqual("pending_recheck", repaired.json()["finding"]["status"])
                self.assertEqual("compliance_ai_repair", repaired.json()["version"]["source_type"])
                self.assertNotEqual(version["id"], repaired.json()["version"]["id"])

                rechecked = await client.post(f"/standards/projects/{project.id}/findings/{repairable.id}/recheck")
                self.assertEqual(200, rechecked.status_code, rechecked.text)
                self.assertIn(rechecked.json()["finding"]["status"], {"ai_resolved", "open"})

                runs = await client.get(f"/standards/projects/{project.id}/review-runs")
                self.assertEqual(200, runs.status_code, runs.text)
                self.assertGreaterEqual(len(runs.json()), 3)
                original_run = await client.get(f"/standards/projects/{project.id}/review-runs/{run_id}")
                self.assertEqual(1, len(original_run.json()["findings"]))


if __name__ == "__main__":
    unittest.main()
