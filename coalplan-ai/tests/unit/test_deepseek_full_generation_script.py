import json
import tempfile
import unittest
from pathlib import Path

from coalplan.application.quality_feedback import build_quality_feedback_plan
from coalplan.domain.enums import RunStatus, TaskStatus

from tools.run_deepseek_full_generation import (
    _build_batch_pattern_learning,
    _build_targeted_revision_artifacts,
    _feedback_summary,
    _find_input_markdown,
    _find_reference_markdown,
    _generate_selected_chapters,
    _pattern_card_usage_summary,
    _selected_generation_node_ids,
    _trace_usage_delta,
    _trace_usage_summary,
    _quality_summary,
    _render_report,
    _skill_snapshot_summary,
)


class DeepSeekFullGenerationScriptTest(unittest.TestCase):
    def test_selected_generation_node_ids_respects_keyword_and_limit(self) -> None:
        nodes = [
            {"node_id": "n3", "title": "Safety", "sort_order": 30},
            {"node_id": "n1", "title": "Water injection craft", "sort_order": 10},
            {"node_id": "n2", "title": "Grouting craft", "sort_order": 20},
        ]

        selected = _selected_generation_node_ids(nodes, limit=1, title_contains=["craft"])

        self.assertEqual(["n1"], selected)

    def test_generate_selected_chapters_marks_partial_failed_without_full_run(self) -> None:
        class ProjectRepo:
            def __init__(self, project):
                self.project = project

            def get(self, _project_id):
                return self.project

            def save(self, _project):
                return None

        class Task:
            def __init__(self, node_id):
                self.node_id = node_id
                self.status = TaskStatus.pending
                self.error_message = ""

        class Run:
            def __init__(self):
                self.status = RunStatus.created
                self.chapter_tasks = [Task("n1"), Task("n2")]

        class Project:
            def __init__(self):
                self.runs = [Run()]

        class Pipeline:
            def __init__(self):
                self.project = Project()
                self.projects = ProjectRepo(self.project)

            def prepare_run(self, _project_id):
                return self.project.runs[-1]

            def generate_one(self, _project_id, node_id):
                task = next(item for item in self.project.runs[-1].chapter_tasks if item.node_id == node_id)
                if node_id == "n2":
                    raise RuntimeError("boom")
                task.status = TaskStatus.passed

        run = _generate_selected_chapters(Pipeline(), "project_demo", ["n1", "n2"])

        self.assertEqual(RunStatus.partial_failed, run.status)
        self.assertEqual(TaskStatus.passed, run.chapter_tasks[0].status)
        self.assertEqual(TaskStatus.failed, run.chapter_tasks[1].status)

    def test_finds_project_three_four_standard_chinese_files(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "投标文档（md版本）.md"
            reference = root / "生成文档（包含信息来源）.md"
            source.write_text("# bid", encoding="utf-8")
            reference.write_text("# generated", encoding="utf-8")

            self.assertEqual(source, _find_input_markdown(root))
            self.assertEqual(reference, _find_reference_markdown(root))

    def test_quality_summary_extracts_gate_metrics(self) -> None:
        summary = _quality_summary(
            {
                "word_counts": {"generated_vs_human_ratio": 0.2},
                "headings": {"human_heading_coverage_ratio": 0.1},
                "source_facts": {"absorption_ratio": 0.3},
                "issues": ["too short"],
                "recommendations": [{"action": "increase_detail_budget"}],
            }
        )

        self.assertEqual(0.2, summary["generated_vs_human_ratio"])
        self.assertEqual(0.1, summary["human_heading_coverage_ratio"])
        self.assertEqual(0.3, summary["source_fact_absorption_ratio"])
        self.assertEqual(1, summary["issue_count"])
        self.assertEqual(["increase_detail_budget"], summary["recommended_actions"])

    def test_pattern_card_usage_summary_extracts_prompt_card_metrics(self) -> None:
        summary = _pattern_card_usage_summary(
            {
                "summary": {
                    "chapter_count": 3,
                    "chapters_with_prompt_cards": 2,
                    "prompt_card_total": 4,
                    "prompt_card_actionable_total": 1,
                    "missing_prompt_card_count": 1,
                    "warning_count": 2,
                }
            }
        )

        self.assertEqual(3, summary["chapter_count"])
        self.assertEqual(2, summary["chapters_with_prompt_cards"])
        self.assertEqual(4, summary["prompt_card_total"])
        self.assertEqual(1, summary["prompt_card_actionable_total"])
        self.assertEqual(1, summary["missing_prompt_card_count"])

    def test_feedback_summary_extracts_actions(self) -> None:
        feedback = build_quality_feedback_plan(
            {
                "project_key": "demo",
                "word_counts": {"generated_vs_human_ratio": 0.2},
                "headings": {"human_heading_coverage_ratio": 0.1, "missing_human_heading_examples": []},
                "source_facts": {"absorption_ratio": 0.8, "candidate_count": 20},
                "common_topics": {},
                "recommendations": [{"action": "increase_detail_budget"}],
            }
        )

        summary = _feedback_summary(feedback)

        self.assertEqual(2, summary["action_count"])
        self.assertEqual(["increase_detail_budget", "repair_outline_coverage"], summary["actions"])
        self.assertEqual(1, summary["revision_trigger_count"])

    def test_skill_snapshot_summary_extracts_coverage_gate(self) -> None:
        summary = _skill_snapshot_summary(
            {
                "output_dir": "out/skill",
                "output_path": "out/skill/SKILL.md",
                "package_paths": {"manifest": "out/skill/manifest.json"},
                "manifest": {
                    "coverage_status": "warning",
                    "coverage_issue_count": 2,
                    "pattern_count": 7,
                },
                "validation_issues": [{"code": "demo"}],
            }
        )

        self.assertEqual("warning", summary["coverage_status"])
        self.assertEqual(2, summary["coverage_issue_count"])
        self.assertEqual(7, summary["pattern_count"])
        self.assertEqual(1, summary["validation_issue_count"])

    def test_trace_usage_summary_prefers_provider_usage_and_estimates_chars(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            trace_dir = Path(temp_dir)
            (trace_dir / "0001_json_Profile.json").write_text(
                json.dumps(
                    {
                        "kind": "json",
                        "elapsed_seconds": 1.25,
                        "prompt": "abcd",
                        "response": "{\"ok\": true}",
                        "usage": {"prompt_tokens": 10, "completion_tokens": 4, "total_tokens": 14},
                    }
                ),
                encoding="utf-8",
            )
            (trace_dir / "0002_markdown.json").write_text(
                json.dumps(
                    {
                        "kind": "markdown",
                        "elapsed_seconds": 2,
                        "prompt": "12345678",
                        "response": "done",
                        "error": "bad output",
                    }
                ),
                encoding="utf-8",
            )

            summary = _trace_usage_summary(trace_dir)

            self.assertEqual(2, summary["call_count"])
            self.assertEqual(1, summary["json_call_count"])
            self.assertEqual(1, summary["markdown_call_count"])
            self.assertEqual(1, summary["error_count"])
            self.assertEqual(3.25, summary["elapsed_seconds_total"])
            self.assertTrue(summary["has_token_usage"])
            self.assertEqual(10, summary["prompt_tokens"])
            self.assertEqual(4, summary["completion_tokens"])
            self.assertEqual(14, summary["total_tokens"])
            self.assertGreater(summary["estimated_total_tokens"], 0)

    def test_trace_usage_delta_is_project_scoped(self) -> None:
        start = {"call_count": 2, "elapsed_seconds_total": 3.5, "prompt_char_total": 10, "has_token_usage": False}
        end = {
            "call_count": 5,
            "json_call_count": 2,
            "markdown_call_count": 1,
            "elapsed_seconds_total": 7.0,
            "prompt_char_total": 30,
            "response_char_total": 12,
            "estimated_total_tokens": 11,
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
        }

        delta = _trace_usage_delta(start, end)

        self.assertEqual(3, delta["call_count"])
        self.assertEqual(3.5, delta["elapsed_seconds_total"])
        self.assertEqual(20, delta["prompt_char_total"])
        self.assertFalse(delta["has_token_usage"])

    def test_build_batch_pattern_learning_writes_candidate_from_quality_reports(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            quality_dir = root / "quality"
            quality_dir.mkdir()
            report = {
                "project_key": "project_demo",
                "word_counts": {"generated_vs_human_ratio": 0.2},
                "headings": {
                    "human_heading_coverage_ratio": 0.1,
                    "missing_human_heading_examples": ["Quality inspection and acceptance records"],
                },
                "source_facts": {
                    "absorption_ratio": 0.1,
                    "omitted_examples": [
                        {"fact": "0.5MPa", "kind": "parameter", "context": "grouting pressure 0.5MPa"}
                    ],
                },
                "common_topics": {},
                "issues": ["too short"],
                "recommendations": [{"action": "strengthen_evidence_utilization"}],
            }
            report_path = quality_dir / "project_demo_quality_audit.json"
            report_path.write_text(json.dumps(report, ensure_ascii=False), encoding="utf-8")
            iteration = {
                "project_id": "project_demo",
                "status": "warning",
                "round_count": 0,
                "rounds": [],
                "final_audit": {"report": report},
                "content_revision_targets": [
                    {
                        "node_id": "node_water",
                        "version_id": "ver_1",
                        "content_node_id": "gcn_crack_water",
                        "target_type": "content_node",
                        "title": "Crack water injection pressure control",
                        "action": "rewrite_subsection",
                        "reason": "omitted_required_source_facts must be absorbed",
                        "evidence_targeted": True,
                        "source_section_ids": ["sec_water"],
                        "evidence_ids": ["ev_water"],
                        "next_steps": [
                            "Insert omitted required source fact `ev_water:fact_1` from evidence `ev_water` / section `sec_water`: crack water injection uses duckbill nozzle and pressure 0.2-0.3MPa."
                        ],
                    }
                ],
                "generation_metadata_targets": [],
            }
            iteration_path = quality_dir / "project_demo_quality_iteration.json"
            iteration_path.write_text(json.dumps(iteration, ensure_ascii=False), encoding="utf-8")

            learning = _build_batch_pattern_learning(
                {
                    "projects": [
                        {
                            "key": "project_demo",
                            "quality_audit_path": str(report_path),
                            "quality_iteration_path": str(iteration_path),
                            "quality_audit": {"issue_count": 1},
                        }
                    ]
                },
                quality_dir=quality_dir,
                output_root=root,
            )

            self.assertEqual("warning", learning["status"])
            self.assertGreaterEqual(learning["suggestion_count"], 1)
            self.assertTrue(Path(learning["learning_report_path"]).exists())
            self.assertTrue(Path(learning["candidate_generated_path"]).exists())
            learning_report = json.loads(Path(learning["learning_report_path"]).read_text(encoding="utf-8"))
            self.assertEqual(1, learning_report["metrics"]["evidence_targeted_content_revision_target_count"])
            candidate = json.loads(Path(learning["candidate_generated_path"]).read_text(encoding="utf-8"))
            self.assertIn(
                "evidence-targeted subsection rewrite",
                "\n".join(candidate["patterns"]["craft"]["revision_signals"]),
            )

    def test_build_batch_pattern_learning_warns_from_iteration_targets_without_quality_issue(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            quality_dir = root / "quality"
            quality_dir.mkdir()
            iteration = {
                "project_id": "project_demo",
                "status": "warning",
                "round_count": 0,
                "rounds": [],
                "final_audit": {},
                "content_revision_targets": [
                    {
                        "target_type": "content_node",
                        "title": "Water injection source fact absorption",
                        "action": "rewrite_subsection",
                        "reason": "omitted_required_source_facts must be absorbed",
                        "evidence_targeted": True,
                        "next_steps": [
                            "Insert omitted required source fact `ev_1:fact_1` from evidence `ev_1` / section `sec_1`: injection pressure 0.2MPa."
                        ],
                    }
                ],
                "generation_metadata_targets": [],
            }
            iteration_path = quality_dir / "project_demo_quality_iteration.json"
            iteration_path.write_text(json.dumps(iteration, ensure_ascii=False), encoding="utf-8")

            learning = _build_batch_pattern_learning(
                {
                    "projects": [
                        {
                            "key": "project_demo",
                            "quality_iteration_path": str(iteration_path),
                            "quality_audit": {"issue_count": 0},
                        }
                    ]
                },
                quality_dir=quality_dir,
                output_root=root,
            )

            self.assertEqual("warning", learning["status"])
            learning_report = json.loads(Path(learning["learning_report_path"]).read_text(encoding="utf-8"))
            self.assertEqual(1, learning_report["metrics"]["evidence_targeted_content_revision_target_count"])

    def test_build_targeted_revision_artifacts_writes_plan_summary(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            summary = {
                "output_root": str(root),
                "model": "fake",
                "projects": [
                    {
                        "key": "project_demo",
                        "project_id": "project_demo",
                        "template_id": "coal_fire",
                        "source_section_count": 3,
                        "outline_node_count": 2,
                        "word_count_estimate_count": 1,
                        "generation_scope": "full",
                        "selected_node_ids": None,
                        "target_word_count_total": 1000,
                        "actual_word_count_total": 0,
                        "task_count": 1,
                        "passed_count": 0,
                        "run_status": "partial_failed",
                        "final_artifact_path": None,
                        "local_final_copy": None,
                        "selected_versions": [],
                        "trace_count_total": 0,
                        "trace_usage": {},
                        "quality_audit": None,
                        "quality_feedback": None,
                        "pattern_card_usage": None,
                        "pattern_card_usage_markdown_path": None,
                        "quality_audit_markdown_path": None,
                        "quality_feedback_markdown_path": None,
                        "failed": [
                            {
                                "node_id": "node_1",
                                "title": "Water injection",
                                "status": "needs_repair",
                                "error_message": "Mapped source evidence was not sufficiently absorbed by the generated chapter: omitted_required_source_facts",
                            }
                        ],
                    }
                ],
            }

            plan_summary = _build_targeted_revision_artifacts(summary, output_root=root)
            summary["targeted_revision_plan"] = plan_summary
            summary.setdefault("input_root", "input")
            summary.setdefault("pattern_skill_snapshot", {})
            summary.setdefault("pattern_learning", {})
            summary.setdefault("trace_usage_total", {})
            report = _render_report(summary)

            self.assertEqual("chapter_level_revision_only", plan_summary["rerun_policy"])
            self.assertEqual(1, plan_summary["action_count"])
            self.assertEqual(1, plan_summary["action_counts"]["regenerate_evidence_targeted"])
            self.assertTrue(Path(plan_summary["json_path"]).exists())
            self.assertTrue(Path(plan_summary["markdown_path"]).exists())
            self.assertIn("targeted revision rerun policy", report)
            self.assertIn("chapter_level_revision_only", report)


if __name__ == "__main__":
    unittest.main()
