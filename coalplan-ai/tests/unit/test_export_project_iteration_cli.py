from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from coalplan.interfaces.cli.export_project_iteration import export_project_iteration
from coalplan.main import build_pipeline
from coalplan.settings import Settings


class ExportProjectIterationCliTest(unittest.TestCase):
    def test_exports_iteration_action_and_gate_files(self) -> None:
        repo_root = Path(__file__).resolve().parents[2]
        sample = (repo_root / "src" / "coalplan" / "assets" / "samples" / "coal_fire_bid.normalized.md").read_text(
            encoding="utf-8-sig"
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            storage_dir = Path(temp_dir) / "storage"
            output_dir = Path(temp_dir) / "plans"
            pipeline = build_pipeline(Settings(storage_dir=storage_dir, llm_provider="fake"))
            project = pipeline.create_project("iteration-export-demo")
            pipeline.ingest_bid_markdown(project.id, file_name="bid.md", content=sample)
            pipeline.prepare_directory(project.id)

            pipeline.current_execution_window = lambda _project_id: {  # type: ignore[method-assign]
                "status": "waiting_for_user",
                "current_phase_id": "outline_detail",
                "allowed_actions": [{"action_id": "outline.control_plan_proposal"}],
            }
            blocked_execution = pipeline.execute_generation_readiness_batch(project.id, group_id="auto_generation")
            self.assertEqual("completed", blocked_execution["status"])
            self.assertGreaterEqual(len(blocked_execution["executed"]), 1)
            self.assertTrue(blocked_execution["artifact_json_path"].endswith("generation_readiness_batch_execution.json"))

            result = export_project_iteration(
                storage_dir=storage_dir,
                project_id=project.id,
                output_dir=output_dir,
                propose_outline_repair=True,
            )

            self.assertEqual(project.id, result["project_id"])
            self.assertTrue((output_dir / "pipeline_gates.json").exists())
            self.assertTrue((output_dir / "pipeline_actions.json").exists())
            self.assertTrue((output_dir / "iteration_plan.json").exists())
            self.assertTrue((output_dir / "iteration_plan.md").exists())
            self.assertTrue((output_dir / "generation_readiness.json").exists())
            self.assertTrue((output_dir / "generation_readiness.md").exists())
            self.assertTrue((output_dir / "current_execution_window.json").exists())
            self.assertTrue((output_dir / "current_execution_window.md").exists())
            self.assertTrue((output_dir / "outline_repair_proposal.json").exists())
            self.assertTrue((output_dir / "outline_repair_proposal.md").exists())
            self.assertIn("readiness_status", result)
            self.assertIn("execution_window_status", result)
            self.assertIn("allowed_now_count", result)
            self.assertIn("deferred_action_count", result)
            self.assertIn("readiness_auto_batch_count", result)
            self.assertIn("Iteration Plan", (output_dir / "iteration_plan.md").read_text(encoding="utf-8"))
            self.assertIn("Generation Readiness", (output_dir / "generation_readiness.md").read_text(encoding="utf-8"))
            self.assertIn("Current Execution Window", (output_dir / "current_execution_window.md").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
