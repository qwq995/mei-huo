from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path

import httpx

from coalplan.main import create_app
from coalplan.settings import Settings


class PreGenerationOutlineRefineApiTest(unittest.TestCase):
    def test_pre_generation_refine_creates_pending_proposal_and_leaf_tasks(self) -> None:
        asyncio.run(self._run_flow())

    async def _run_flow(self) -> None:
        repo_root = Path(__file__).resolve().parents[2]
        sample = (repo_root / "src" / "coalplan" / "assets" / "samples" / "coal_fire_bid.normalized.md").read_text(
            encoding="utf-8-sig"
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            app = create_app(Settings(storage_dir=Path(temp_dir), llm_provider="fake"))
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
                created = await client.post("/projects", json={"name": "pre-generation-refine", "template_id": "coal_fire"})
                self.assertEqual(200, created.status_code)
                project_id = created.json()["id"]
                uploaded = await client.post(
                    f"/projects/{project_id}/bid-markdown",
                    json={"file_name": "bid.md", "content": sample},
                )
                self.assertEqual(200, uploaded.status_code)
                directory = await client.post(f"/projects/{project_id}/directory")
                self.assertEqual(200, directory.status_code)
                before_nodes = (await client.get(f"/projects/{project_id}/outline-nodes")).json()

                proposal = await client.post(
                    f"/projects/{project_id}/outline/pre-generation-refine",
                    json={"mode": "balanced", "use_local_corpus": True, "project_type": "auto"},
                )
                self.assertEqual(200, proposal.status_code)
                proposal_payload = proposal.json()
                self.assertEqual("outline", proposal_payload["target_type"])
                self.assertEqual("pending", proposal_payload["status"])
                self.assertEqual("coal_fire", proposal_payload["refine_summary"]["project_type"])
                preview_nodes = proposal_payload["preview"]["nodes"]
                self.assertTrue(preview_nodes)
                self.assertTrue(any(node["title"] == "压力流量控制" for node in preview_nodes))
                self.assertTrue(any("结构参考" in " ".join(node.get("source_rules") or []) for node in preview_nodes))
                self.assertTrue(proposal_payload["artifact_json_path"].endswith("pre_generation_outline_refine.json"))
                self.assertTrue(proposal_payload["artifact_markdown_path"].endswith("pre_generation_outline_refine.md"))

                applied = await client.post(f"/projects/{project_id}/outline/proposals/{proposal_payload['id']}/apply")
                self.assertEqual(200, applied.status_code)
                applied_payload = applied.json()
                self.assertEqual("applied", applied_payload["status"])
                self.assertGreater(applied_payload["chapter_task_count"], 0)

                after_nodes = (await client.get(f"/projects/{project_id}/outline-nodes")).json()
                self.assertGreater(len(after_nodes), len(before_nodes))
                pressure_node = next(node for node in after_nodes if node["title"] == "压力流量控制")
                self.assertTrue(pressure_node["parent_id"])
                chapters = await client.get(f"/projects/{project_id}/chapters")
                self.assertEqual(200, chapters.status_code)
                chapter_ids = {item["node_id"] for item in chapters.json()}
                self.assertIn(pressure_node["node_id"], chapter_ids)
                self.assertNotIn(pressure_node["parent_id"], chapter_ids)


if __name__ == "__main__":
    unittest.main()
