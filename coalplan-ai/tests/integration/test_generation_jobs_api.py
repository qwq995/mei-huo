from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path
from threading import Event

import httpx

from coalplan.main import create_app
from coalplan.settings import Settings


class GenerationJobsApiTest(unittest.TestCase):
    def test_job_lifecycle_and_project_conflict(self) -> None:
        asyncio.run(self._run_flow())

    async def _run_flow(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            app = create_app(Settings(storage_dir=Path(temp_dir), llm_provider="fake"))
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
                created = await client.post("/projects", json={"name": "job-test", "template_id": "coal_fire"})
                self.assertEqual(200, created.status_code)
                project_id = created.json()["id"]
                sample = (Path(__file__).resolve().parents[2] / "src" / "coalplan" / "assets" / "samples" / "coal_fire_bid.normalized.md").read_text(encoding="utf-8-sig")
                uploaded = await client.post(
                    f"/projects/{project_id}/bid-markdown",
                    json={"file_name": "bid.md", "content": sample},
                )
                self.assertEqual(200, uploaded.status_code)

                release = Event()
                original = app.state.pipeline.prepare_directory

                def slow_directory(*args, **kwargs):
                    release.wait(timeout=3)
                    return original(*args, **kwargs)

                app.state.pipeline.prepare_directory = slow_directory
                first = await client.post(
                    f"/projects/{project_id}/jobs",
                    json={"job_type": "directory_generation", "payload": {"force": True}},
                )
                self.assertEqual(202, first.status_code)
                second = await client.post(
                    f"/projects/{project_id}/jobs",
                    json={"job_type": "directory_generation", "payload": {"force": True}},
                )
                self.assertEqual(409, second.status_code)

                release.set()
                job_id = first.json()["job_id"]
                final = None
                for _ in range(80):
                    response = await client.get(f"/projects/{project_id}/jobs/{job_id}")
                    final = response.json()
                    if final["status"] in {"completed", "partial", "failed"}:
                        break
                    await asyncio.sleep(0.05)
                self.assertEqual("completed", final["status"])
                self.assertEqual("completed", final["stage"])
                self.assertGreaterEqual(final["current"], 1)

                recent = await client.get(f"/projects/{project_id}/jobs/active")
                self.assertEqual(job_id, recent.json()[0]["job_id"])

    def test_invalid_job_is_rejected(self) -> None:
        asyncio.run(self._run_invalid())

    async def _run_invalid(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            app = create_app(Settings(storage_dir=Path(temp_dir), llm_provider="fake"))
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
                created = await client.post("/projects", json={"name": "job-invalid", "template_id": "coal_fire"})
                project_id = created.json()["id"]
                response = await client.post(f"/projects/{project_id}/jobs", json={"job_type": "unknown", "payload": {}})
                self.assertEqual(400, response.status_code)
