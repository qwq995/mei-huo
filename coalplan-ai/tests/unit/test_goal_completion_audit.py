from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from coalplan.application.goal_completion_audit import (
    audit_generation_goal,
    render_generation_goal_audit_markdown,
)
from coalplan.application.pipeline_stage_gates import PipelineGateReport, PipelineGateStatus
from coalplan.interfaces.cli.audit_generation_goal import _resolve_project_gate_report
from coalplan.interfaces.cli.audit_generation_goal import render_outline_repair_proposal_markdown
from coalplan.main import build_pipeline
from coalplan.settings import Settings


class GoalCompletionAuditTest(unittest.TestCase):
    def test_default_audit_keeps_completion_unproven_without_project_gate_report(self) -> None:
        report = audit_generation_goal()

        self.assertEqual("warning", report.status)
        by_id = {item.requirement_id: item for item in report.requirement_audits}
        self.assertIn("directory_tree_layering", by_id)
        self.assertIn("source_mapping_before_writing", by_id)
        self.assertIn("local_corpus_pattern_skill", by_id)
        self.assertEqual("warning", by_id["project_run_evidence"].status)
        self.assertIn("No project gate report", " ".join(by_id["project_run_evidence"].evidence))

        markdown = render_generation_goal_audit_markdown(report)
        self.assertIn("Generation Goal Completion Audit", markdown)
        self.assertIn("source_mapping_before_writing", markdown)
        self.assertIn("local_corpus_pattern_skill", markdown)

    def test_project_gate_report_can_prove_project_run_requirement(self) -> None:
        gate_report = PipelineGateReport(
            project_id="demo",
            overall_status="passed",
            gates=[
                PipelineGateStatus(name="input", status="passed", summary="ok"),
                PipelineGateStatus(name="mapping", status="passed", summary="ok"),
                PipelineGateStatus(name="version", status="passed", summary="ok"),
            ],
        )

        report = audit_generation_goal(project_gate_report=gate_report)

        by_id = {item.requirement_id: item for item in report.requirement_audits}
        self.assertEqual("passed", by_id["project_run_evidence"].status)
        self.assertTrue(any("overall_status=passed" in item for item in by_id["project_run_evidence"].evidence))
        self.assertNotEqual("blocked", report.status)

    def test_cli_can_build_project_gate_report_from_storage(self) -> None:
        repo_root = Path(__file__).resolve().parents[2]
        sample = (repo_root / "src" / "coalplan" / "assets" / "samples" / "coal_fire_bid.normalized.md").read_text(
            encoding="utf-8-sig"
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            storage_dir = Path(temp_dir) / "storage"
            pipeline = build_pipeline(Settings(storage_dir=storage_dir, llm_provider="fake"))
            project = pipeline.create_project("goal-audit-demo")
            pipeline.ingest_bid_markdown(project.id, file_name="bid.md", content=sample)
            pipeline.prepare_directory(project.id)

            output_gate_json = Path(temp_dir) / "project-gates.json"
            output_proposal_json = Path(temp_dir) / "outline-proposal.json"
            output_proposal_md = Path(temp_dir) / "outline-proposal.md"
            gate_report = _resolve_project_gate_report(
                project_gate_report_path=None,
                storage_dir=storage_dir,
                project_id=project.id,
                project_key=None,
                output_gate_json=output_gate_json,
                repair_profile_before_audit=False,
                propose_outline_repair=True,
                output_outline_proposal_json=output_proposal_json,
                output_outline_proposal_md=output_proposal_md,
            )

            self.assertTrue(output_gate_json.exists())
            self.assertTrue(output_proposal_json.exists())
            self.assertTrue(output_proposal_md.exists())
            self.assertIn("preview", output_proposal_json.read_text(encoding="utf-8"))
            self.assertIn("Outline Repair Proposal", output_proposal_md.read_text(encoding="utf-8"))
            self.assertEqual(project.id, gate_report.project_id)
            self.assertTrue(gate_report.gates)
            report = audit_generation_goal(project_gate_report=gate_report)
            by_id = {item.requirement_id: item for item in report.requirement_audits}
            self.assertIn(by_id["project_run_evidence"].status, {"passed", "warning", "blocked"})
            self.assertTrue(any(f"overall_status={gate_report.overall_status}" in item for item in by_id["project_run_evidence"].evidence))

    def test_outline_repair_proposal_markdown_is_reviewable(self) -> None:
        markdown = render_outline_repair_proposal_markdown(
            {
                "id": "proposal_1",
                "target_type": "outline",
                "target_id": "project_1",
                "status": "pending",
                "suggestion": "补齐缺失目录。",
                "preview": {
                    "nodes": [
                        {
                            "__action": "create",
                            "node_id": "node_1",
                            "title": "编制依据及原则",
                            "level": 1,
                            "source_rules": ["投标文件 > 编制依据"],
                            "auto_fill": ["归纳编制原则。"],
                            "manual_fill": ["【需人工补充：正式规范清单。】"],
                            "special_notes": ["不得补造审批编号。"],
                            "target_word_count": 900,
                        }
                    ]
                },
            }
        )

        self.assertIn("编制依据及原则", markdown)
        self.assertIn("[主要来源]", markdown)
        self.assertIn("[人工补充需补充]", markdown)
        self.assertIn("not been applied automatically", markdown)


if __name__ == "__main__":
    unittest.main()
