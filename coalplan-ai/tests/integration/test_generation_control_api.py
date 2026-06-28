from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import httpx

from coalplan.main import create_app
from coalplan.settings import Settings


class GenerationControlApiTest(unittest.TestCase):
    def test_applying_outline_proposal_unlocks_auto_execution_window(self) -> None:
        import asyncio

        asyncio.run(self._run_outline_proposal_unlock_flow())

    async def _run_outline_proposal_unlock_flow(self) -> None:
        repo_root = Path(__file__).resolve().parents[2]
        sample = (repo_root / "src" / "coalplan" / "assets" / "samples" / "coal_fire_bid.normalized.md").read_text(
            encoding="utf-8-sig"
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            app = create_app(Settings(storage_dir=Path(temp_dir), llm_provider="fake"))
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
                created = await client.post("/projects", json={"name": "proposal-unlock", "template_id": "coal_fire"})
                self.assertEqual(200, created.status_code)
                project_id = created.json()["id"]
                uploaded = await client.post(
                    f"/projects/{project_id}/bid-markdown",
                    json={"file_name": "bid.md", "content": sample},
                )
                self.assertEqual(200, uploaded.status_code)
                directory = await client.post(f"/projects/{project_id}/directory")
                self.assertEqual(200, directory.status_code)

                proposal = await client.post(f"/projects/{project_id}/outline/control-plan-proposal")
                self.assertEqual(200, proposal.status_code)
                proposal_id = proposal.json()["id"]

                blocked_window = await client.get(f"/projects/{project_id}/current-execution-window")
                self.assertEqual(200, blocked_window.status_code)
                blocked_payload = blocked_window.json()
                self.assertEqual("waiting_for_user", blocked_payload["status"])
                self.assertEqual("outline_detail", blocked_payload["current_phase_id"])
                self.assertEqual(proposal_id, blocked_payload["allowed_actions"][0]["proposal_id"])
                self.assertEqual("apply_pending_outline_proposal", blocked_payload["allowed_actions"][0]["action"])

                advisory_execution = await client.post(
                    f"/projects/{project_id}/generation-readiness/execute",
                    json={"group_id": "__missing__", "include_user_confirmation": False, "limit": 1},
                )
                self.assertEqual(200, advisory_execution.status_code)
                advisory_payload = advisory_execution.json()
                self.assertNotEqual("blocked_by_execution_window", advisory_payload["status"])
                self.assertIsNotNone(advisory_payload.get("execution_window_warning"))

                applied = await client.post(f"/projects/{project_id}/outline/proposals/{proposal_id}/apply")
                self.assertEqual(200, applied.status_code)
                self.assertEqual("applied", applied.json()["status"])

                unlocked_window = await client.get(f"/projects/{project_id}/current-execution-window")
                self.assertEqual(200, unlocked_window.status_code)
                unlocked_payload = unlocked_window.json()
                self.assertEqual("auto_runnable", unlocked_payload["status"])
                self.assertNotEqual("outline_detail", unlocked_payload["current_phase_id"])
                self.assertTrue(all(not action["requires_user_confirmation"] for action in unlocked_payload["allowed_actions"]))

                readiness_execution = await client.post(
                    f"/projects/{project_id}/generation-readiness/execute",
                    json={"group_id": "auto_generation", "include_user_confirmation": False, "limit": 1},
                )
                self.assertEqual(200, readiness_execution.status_code)
                execution_payload = readiness_execution.json()
                self.assertNotEqual("blocked_by_execution_window", execution_payload["status"])
                self.assertGreaterEqual(len(execution_payload["executed"]), 1)
                executed_item = execution_payload["executed"][0]
                self.assertTrue(executed_item["node_id"])
                self.assertTrue(executed_item["action"])
                self.assertTrue(executed_item["result_kind"])
                self.assertIn("result", executed_item)

    def test_directory_response_and_control_endpoint_include_generation_control_plan(self) -> None:
        import asyncio

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
                blueprint = await client.get("/pipeline-blueprint")
                self.assertEqual(200, blueprint.status_code)
                blueprint_payload = blueprint.json()
                blueprint_stages = {stage["stage_id"]: stage for stage in blueprint_payload["blueprint"]["stages"]}
                self.assertTrue({"mapping", "generation", "revision", "quality_feedback", "version", "merge"}.issubset(blueprint_stages))
                self.assertEqual("Selected Version Review", blueprint_stages["version"]["title"])
                self.assertIn("version.review_evidence_utilization", blueprint_stages["version"]["related_actions"])
                self.assertIn("return_to_version_review", blueprint_stages["merge"]["failure_routes"])
                self.assertIn("Pipeline Blueprint", blueprint_payload["markdown"])

                created = await client.post("/projects", json={"name": "控制计划接口测试", "template_id": "coal_fire"})
                self.assertEqual(200, created.status_code)
                project_id = created.json()["id"]

                uploaded = await client.post(
                    f"/projects/{project_id}/bid-markdown",
                    json={"file_name": "bid.md", "content": sample},
                )
                self.assertEqual(200, uploaded.status_code)

                directory = await client.post(f"/projects/{project_id}/directory")
                self.assertEqual(200, directory.status_code)
                directory_payload = directory.json()
                self.assertIn("generation_control", directory_payload)
                self.assertIsNotNone(directory_payload["generation_control"]["plan"])
                self.assertEqual("template", directory_payload["outline_source"])
                self.assertGreater(len(directory_payload["outline"]["outline"]["generation_steps"]), 0)

                outline_steps = await client.get(f"/projects/{project_id}/outline-generation-steps")
                self.assertEqual(200, outline_steps.status_code)
                outline_steps_payload = outline_steps.json()
                self.assertIn(outline_steps_payload["status"], {"pending", "running", "warning", "completed"})
                self.assertGreater(len(outline_steps_payload["steps"]), 0)
                self.assertTrue(all("nodes" in step and "status" in step for step in outline_steps_payload["steps"]))
                self.assertTrue(outline_steps_payload["artifact_json_path"].endswith("outline_generation_step_progress.json"))
                step_id = outline_steps_payload["steps"][0]["step_id"]
                step_run = await client.post(f"/projects/{project_id}/outline-generation-steps/{step_id}/generate")
                self.assertEqual(200, step_run.status_code)
                step_run_payload = step_run.json()
                self.assertEqual(step_id, step_run_payload["step_id"])
                self.assertIn(step_run_payload["status"], {"completed", "partial_failed", "failed"})
                self.assertIn("progress", step_run_payload)
                self.assertTrue(step_run_payload["artifact_json_path"].endswith(".json"))

                quality_audit = await client.post(
                    f"/projects/{project_id}/quality-audit",
                    json={"apply_feedback": True},
                )
                self.assertEqual(200, quality_audit.status_code)
                quality_audit_payload = quality_audit.json()
                self.assertEqual(project_id, quality_audit_payload["project_id"])
                self.assertIn("word_counts", quality_audit_payload["report"])
                self.assertTrue(quality_audit_payload["artifact_paths"]["quality_audit_json"].endswith("quality_audit_report.json"))
                self.assertTrue(quality_audit_payload["artifact_paths"]["quality_audit_md"].endswith("quality_audit_report.md"))
                self.assertIn("revision_targets", quality_audit_payload)
                self.assertTrue(quality_audit_payload["revision_targets"]["artifact_json_path"].endswith("quality_audit_revision_targets.json"))
                self.assertIsNotNone(quality_audit_payload["feedback"])

                quality_targets = await client.get(f"/projects/{project_id}/quality-audit/revision-targets")
                self.assertEqual(200, quality_targets.status_code)
                quality_targets_payload = quality_targets.json()
                self.assertEqual(project_id, quality_targets_payload["project_id"])
                self.assertIn("targets", quality_targets_payload)

                quality_targets_exec = await client.post(
                    f"/projects/{project_id}/quality-audit/revision-targets/execute",
                    json={"include_user_confirmation": False, "limit": 3},
                )
                self.assertEqual(200, quality_targets_exec.status_code)
                quality_targets_exec_payload = quality_targets_exec.json()
                self.assertIn(quality_targets_exec_payload["status"], {"completed", "partial_failed", "failed"})
                self.assertIn("executed", quality_targets_exec_payload)
                self.assertIn("skipped", quality_targets_exec_payload)
                self.assertIn("failed", quality_targets_exec_payload)
                self.assertTrue(quality_targets_exec_payload["artifact_json_path"].endswith("quality_audit_revision_execution.json"))

                quality_iteration = await client.post(
                    f"/projects/{project_id}/quality-iteration",
                    json={"max_rounds": 1, "include_user_confirmation": False, "limit_per_round": 2},
                )
                self.assertEqual(200, quality_iteration.status_code)
                quality_iteration_payload = quality_iteration.json()
                self.assertIn(
                    quality_iteration_payload["status"],
                    {"completed", "completed_with_remaining_targets", "partial_failed", "no_auto_actions"},
                )
                self.assertEqual(1, quality_iteration_payload["round_count"])
                self.assertIn("final_audit", quality_iteration_payload)
                self.assertIn("content_revision_targets", quality_iteration_payload)
                self.assertIn("generation_metadata_targets", quality_iteration_payload)
                self.assertTrue(quality_iteration_payload["artifact_json_path"].endswith("quality_iteration.json"))
                self.assertTrue(quality_iteration_payload["artifact_markdown_path"].endswith("quality_iteration.md"))
                self.assertIn("learning_report", quality_iteration_payload)
                self.assertTrue(quality_iteration_payload["learning_report"]["artifact_json_path"].endswith("quality_iteration_learning.json"))
                iteration_json = Path(quality_iteration_payload["artifact_json_path"]).read_text(encoding="utf-8-sig")
                iteration_md = Path(quality_iteration_payload["artifact_markdown_path"]).read_text(encoding="utf-8-sig")
                self.assertIn("learning_report", iteration_json)
                self.assertIn("content_revision_targets", iteration_json)
                self.assertIn("generation_metadata_targets", iteration_json)
                self.assertIn("content_revision_targets", iteration_md)
                self.assertIn("generation_metadata_targets", iteration_md)
                self.assertIn("Learning Report", iteration_md)

                learning_report = await client.get(f"/projects/{project_id}/quality-iteration/learning-report")
                self.assertEqual(200, learning_report.status_code)
                learning_payload = learning_report.json()
                self.assertEqual(project_id, learning_payload["project_id"])
                self.assertIn("suggestions", learning_payload)
                self.assertIn("content_revision_target_count", learning_payload["metrics"])
                self.assertIn("generation_metadata_target_count", learning_payload["metrics"])

                control = await client.get(f"/projects/{project_id}/generation-control-plan")
                self.assertEqual(200, control.status_code)
                plan = control.json()["plan"]
                self.assertGreater(len(plan["outline_coverage"]), 0)
                self.assertGreater(len(plan["chapter_policies"]), 0)
                self.assertTrue(any(policy.get("pattern_prompt_cards") for policy in plan["chapter_policies"]))
                self.assertTrue(any(item["topic"] == "质量管理" for item in plan["outline_coverage"]))

                gates = await client.get(f"/projects/{project_id}/pipeline-gates")
                self.assertEqual(200, gates.status_code)
                gate_payload = gates.json()
                self.assertIn(gate_payload["overall_status"], {"pending", "passed", "warning", "blocked"})
                gate_names = {item["name"] for item in gate_payload["gates"]}
                self.assertTrue({"input", "profile", "outline", "coverage", "detail", "mapping", "generation"}.issubset(gate_names))
                self.assertEqual("passed", next(item for item in gate_payload["gates"] if item["name"] == "input")["status"])

                actions = await client.get(f"/projects/{project_id}/pipeline-actions")
                self.assertEqual(200, actions.status_code)
                action_payload = actions.json()
                self.assertIn(action_payload["overall_status"], {"pending", "passed", "warning", "blocked"})
                self.assertIn("actions", action_payload)
                self.assertTrue(
                    all({"action_id", "stage", "action", "priority", "title"}.issubset(item) for item in action_payload["actions"])
                )
                outline_generation_actions = [
                    item for item in action_payload["actions"] if item["action_id"].startswith("generation.outline_step.")
                ]
                self.assertTrue(outline_generation_actions)
                self.assertTrue(outline_generation_actions[0]["target_step_id"])
                self.assertEqual("generate_outline_step", outline_generation_actions[0]["action"])

                readiness = await client.get(f"/projects/{project_id}/generation-readiness")
                self.assertEqual(200, readiness.status_code)
                readiness_payload = readiness.json()
                self.assertEqual(project_id, readiness_payload["project_id"])
                self.assertIn(readiness_payload["status"], {"pending", "generation_required", "revision_required", "waiting_for_user", "ready_for_merge"})
                self.assertGreater(len(readiness_payload["nodes"]), 0)
                self.assertTrue(
                    all({"node_id", "status", "next_action", "mapping_status"}.issubset(item) for item in readiness_payload["nodes"])
                )
                self.assertIn("batches", readiness_payload)
                self.assertTrue(all({"group_id", "execution_mode", "items"}.issubset(item) for item in readiness_payload["batches"]))
                self.assertTrue(readiness_payload["artifact_json_path"].endswith("generation_readiness.json"))
                self.assertTrue(readiness_payload["artifact_markdown_path"].endswith("generation_readiness.md"))
                readiness_execution = await client.post(
                    f"/projects/{project_id}/generation-readiness/execute",
                    json={"group_id": "auto_generation", "include_user_confirmation": False, "limit": 1},
                )
                self.assertEqual(200, readiness_execution.status_code)
                readiness_execution_payload = readiness_execution.json()
                self.assertIn(readiness_execution_payload["status"], {"completed", "partial_failed", "failed", "blocked_by_execution_window"})
                self.assertIn("executed", readiness_execution_payload)
                self.assertIn("skipped", readiness_execution_payload)
                self.assertIn("failed", readiness_execution_payload)
                if readiness_execution_payload["executed"]:
                    executed_item = readiness_execution_payload["executed"][0]
                    self.assertTrue(executed_item["node_id"])
                    self.assertTrue(executed_item["action"])
                    self.assertTrue(executed_item["result_kind"])
                self.assertTrue(readiness_execution_payload["artifact_json_path"].endswith("generation_readiness_batch_execution.json"))
                self.assertTrue(readiness_execution_payload["artifact_markdown_path"].endswith("generation_readiness_batch_execution.md"))
                readiness_execution_md = Path(readiness_execution_payload["artifact_markdown_path"]).read_text(encoding="utf-8-sig")
                self.assertIn("Generation Readiness Batch Execution", readiness_execution_md)
                self.assertIn("Readiness Delta", readiness_execution_md)
                if readiness_execution_payload["executed"]:
                    self.assertIn("result_kind", readiness_execution_md)

                iteration = await client.get(f"/projects/{project_id}/iteration-plan")
                self.assertEqual(200, iteration.status_code)
                iteration_payload = iteration.json()
                self.assertEqual(project_id, iteration_payload["project_id"])
                self.assertIn(iteration_payload["status"], {"action_required", "waiting_for_user", "ready_to_merge_or_complete", "pending", "warning", "blocked"})
                self.assertTrue(any(phase["phase_id"] in {"outline_detail", "mapping_generation"} for phase in iteration_payload["phases"]))
                self.assertTrue(iteration_payload["artifact_json_path"].endswith("iteration_plan.json"))
                self.assertTrue(iteration_payload["artifact_markdown_path"].endswith("iteration_plan.md"))

                execution_window = await client.get(f"/projects/{project_id}/current-execution-window")
                self.assertEqual(200, execution_window.status_code)
                execution_payload = execution_window.json()
                self.assertEqual(project_id, execution_payload["project_id"])
                self.assertIn(execution_payload["status"], {"waiting_for_user", "auto_runnable", "idle", "complete"})
                self.assertIn("allowed_actions", execution_payload)
                self.assertIn("deferred_actions", execution_payload)
                self.assertTrue(execution_payload["artifact_json_path"].endswith("current_execution_window.json"))
                self.assertTrue(execution_payload["artifact_markdown_path"].endswith("current_execution_window.md"))
                if execution_payload["allowed_actions"]:
                    current_phase_id = execution_payload["current_phase_id"]
                    self.assertTrue(all(item["phase_id"] == current_phase_id for item in execution_payload["allowed_actions"]))
                    self.assertTrue(all(item.get("blocked_by_phase_id") == current_phase_id for item in execution_payload["deferred_actions"]))
                if execution_payload["status"] == "waiting_for_user":
                    blocked_generate = await client.post(f"/projects/{project_id}/generate")
                    self.assertEqual(409, blocked_generate.status_code)
                    self.assertEqual("blocked_by_execution_window", blocked_generate.json()["detail"]["error"])
                    if readiness_payload["nodes"]:
                        blocked_revision = await client.post(
                            f"/projects/{project_id}/chapters/{readiness_payload['nodes'][0]['node_id']}/revision-action",
                            json={"action": "regenerate"},
                        )
                        self.assertEqual(409, blocked_revision.status_code)
                        self.assertEqual("blocked_by_execution_window", blocked_revision.json()["detail"]["error"])

                feedback = await client.post(
                    f"/projects/{project_id}/quality-feedback",
                    json={
                        "report": {
                            "project_key": "api_demo",
                            "word_counts": {"generated_vs_human_ratio": 0.12},
                            "headings": {
                                "human_heading_coverage_ratio": 0.1,
                                "generated_count": 10,
                                "human_count": 100,
                                "missing_human_heading_examples": ["施工临时设施布置", "用电布置"],
                            },
                            "source_facts": {
                                "candidate_count": 20,
                                "absorbed_count": 2,
                                "omitted_count": 18,
                                "absorption_ratio": 0.1,
                                "omitted_examples": [{"fact": "GB50194-2014"}],
                            },
                            "common_topics": {},
                            "recommendations": [
                                {"action": "increase_detail_budget"},
                                {"action": "repair_outline_coverage"},
                                {"action": "strengthen_evidence_utilization"},
                            ],
                        },
                        "trace_diagnostics": {
                            "trace_count": 2,
                            "buckets": {"not_prompted": 1, "prompted_but_omitted": 1},
                            "facts": [
                                {
                                    "fact": "GB50194-2014",
                                    "status": "not_prompted",
                                    "suggested_action": "remap_sources",
                                },
                                {
                                    "fact": "0.5MPa",
                                    "status": "prompted_but_omitted",
                                    "suggested_action": "regenerate",
                                },
                            ],
                        },
                    },
                )
                self.assertEqual(200, feedback.status_code)
                feedback_payload = feedback.json()
                self.assertEqual("api_demo", feedback_payload["feedback"]["project_key"])
                self.assertTrue(any(item["action"] == "increase_detail_budget" for item in feedback_payload["feedback"]["actions"]))
                self.assertTrue(any(item["target"] == "traceability" for item in feedback_payload["feedback"]["actions"]))
                self.assertTrue(any(item["action"] == "remap_sources" for item in feedback_payload["feedback"]["revision_triggers"]))
                self.assertTrue(any(item["action"] == "regenerate" for item in feedback_payload["feedback"]["revision_triggers"]))

                feedback_iteration = await client.get(f"/projects/{project_id}/iteration-plan")
                self.assertEqual(200, feedback_iteration.status_code)
                feedback_iteration_payload = feedback_iteration.json()
                self.assertTrue(any(phase["phase_id"] == "quality_feedback" for phase in feedback_iteration_payload["phases"]))
                self.assertTrue(any("quality" in phase["phase_id"] for phase in feedback_iteration_payload["phases"]))

                stored_feedback = await client.get(f"/projects/{project_id}/quality-feedback")
                self.assertEqual(200, stored_feedback.status_code)
                self.assertEqual("api_demo", stored_feedback.json()["feedback"]["project_key"])

                quality_proposal = await client.post(f"/projects/{project_id}/quality-feedback/outline-proposal")
                self.assertEqual(200, quality_proposal.status_code)
                quality_proposal_payload = quality_proposal.json()
                self.assertEqual("outline", quality_proposal_payload["target_type"])
                self.assertTrue(any(node.get("__action") == "create" for node in quality_proposal_payload["preview"]["nodes"]))

                adjusted_control = await client.get(f"/projects/{project_id}/generation-control-plan")
                self.assertEqual(200, adjusted_control.status_code)
                adjusted_policies = adjusted_control.json()["plan"]["chapter_policies"]
                self.assertTrue(any(policy.get("target_word_count") for policy in adjusted_policies))
                self.assertTrue(any(policy.get("max_evidence_spans", 0) >= 24 for policy in adjusted_policies))

                before_nodes = await client.get(f"/projects/{project_id}/outline-nodes")
                self.assertEqual(200, before_nodes.status_code)
                before_count = len(before_nodes.json())

                proposal = await client.post(f"/projects/{project_id}/outline/control-plan-proposal")
                self.assertEqual(200, proposal.status_code)
                proposal_payload = proposal.json()
                self.assertEqual("outline", proposal_payload["target_type"])
                self.assertTrue(any(node.get("__action") == "create" for node in proposal_payload["preview"]["nodes"]))

                applied = await client.post(f"/projects/{project_id}/outline/proposals/{proposal_payload['id']}/apply")
                self.assertEqual(200, applied.status_code)
                self.assertEqual("applied", applied.json()["status"])

                after_nodes = await client.get(f"/projects/{project_id}/outline-nodes")
                self.assertEqual(200, after_nodes.status_code)
                after_payload = after_nodes.json()
                self.assertGreater(len(after_payload), before_count)
                self.assertTrue(any(node["title"] == "质量管理体系及保证措施" for node in after_payload))

                batch_subsection_proposal = await client.post(f"/projects/{project_id}/outline/subsection-proposals")
                self.assertEqual(200, batch_subsection_proposal.status_code)
                batch_payload = batch_subsection_proposal.json()
                self.assertEqual("outline", batch_payload["target_type"])
                self.assertTrue(any(node.get("parent_id") for node in batch_payload["preview"]["nodes"]))
                applied_batch_subsections = await client.post(
                    f"/projects/{project_id}/outline/proposals/{batch_payload['id']}/apply"
                )
                self.assertEqual(200, applied_batch_subsections.status_code)

                dense_node = next(node for node in after_payload if "灌" in node["title"] or "钻孔" in node["title"])
                subsection_proposal = await client.post(
                    f"/projects/{project_id}/chapters/{dense_node['node_id']}/subsection-proposal"
                )
                if subsection_proposal.status_code == 200:
                    subsection_payload = subsection_proposal.json()
                    self.assertTrue(any(node.get("parent_id") == dense_node["node_id"] for node in subsection_payload["preview"]["nodes"]))
                    applied_subsections = await client.post(
                        f"/projects/{project_id}/outline/proposals/{subsection_payload['id']}/apply"
                    )
                    self.assertEqual(200, applied_subsections.status_code)
                else:
                    self.assertEqual(400, subsection_proposal.status_code)
                final_nodes = (await client.get(f"/projects/{project_id}/outline-nodes")).json()
                self.assertTrue(any(node.get("parent_id") == dense_node["node_id"] for node in final_nodes))

                for _ in range(3):
                    window_before_generate = await client.get(f"/projects/{project_id}/current-execution-window")
                    self.assertEqual(200, window_before_generate.status_code)
                    window_payload = window_before_generate.json()
                    if window_payload["status"] != "waiting_for_user":
                        break
                    pending_action = next(
                        (
                            item
                            for item in window_payload.get("allowed_actions", [])
                            if item.get("action") == "apply_pending_outline_proposal" and item.get("proposal_id")
                        ),
                        None,
                    )
                    if pending_action is None:
                        break
                    applied_pending = await client.post(
                        f"/projects/{project_id}/outline/proposals/{pending_action['proposal_id']}/apply"
                    )
                    self.assertEqual(200, applied_pending.status_code)

                generated = await client.post(f"/projects/{project_id}/generate")
                self.assertEqual(200, generated.status_code)

                latest_nodes = (await client.get(f"/projects/{project_id}/outline-nodes")).json()
                generated_node_id = dense_node["node_id"]
                candidate_node_ids = [
                    item["node_id"]
                    for item in latest_nodes
                    if item["node_id"] == dense_node["node_id"] or item.get("parent_id") == dense_node["node_id"]
                ]
                generated_workspace_payload = None
                selected_version_id = None
                for candidate_node_id in candidate_node_ids:
                    generated_workspace = await client.get(f"/projects/{project_id}/chapters/{candidate_node_id}/workspace")
                    self.assertEqual(200, generated_workspace.status_code)
                    payload = generated_workspace.json()
                    if payload.get("selected_version_id"):
                        generated_node_id = candidate_node_id
                        generated_workspace_payload = payload
                        selected_version_id = payload["selected_version_id"]
                        break
                self.assertTrue(selected_version_id)
                evidence_audit = await client.get(
                    f"/projects/{project_id}/chapters/{generated_node_id}/versions/{selected_version_id}/evidence-audit"
                )
                self.assertEqual(200, evidence_audit.status_code)
                evidence_payload = evidence_audit.json()
                self.assertEqual(generated_node_id, evidence_payload["node_id"])
                self.assertIn("coverage_ratio", evidence_payload)
                self.assertTrue(evidence_payload["artifact_path"].endswith(".evidence_audit.json"))
                evidence_action = await client.post(
                    f"/projects/{project_id}/chapters/{generated_node_id}/versions/{selected_version_id}/evidence-audit/revision-action",
                    json={"action": "regenerate"},
                )
                self.assertEqual(200, evidence_action.status_code)
                evidence_action_payload = evidence_action.json()
                self.assertEqual("chapter_version", evidence_action_payload["kind"])
                self.assertEqual("regenerate", evidence_action_payload["action"])
                self.assertIn("draft", evidence_action_payload)
                generation_metadata = await client.get(
                    f"/projects/{project_id}/chapters/{generated_node_id}/versions/{selected_version_id}/generation-metadata"
                )
                self.assertEqual(200, generation_metadata.status_code)
                generation_metadata_payload = generation_metadata.json()
                self.assertIn("selected_pattern_keys", generation_metadata_payload)
                self.assertIn("pattern_evidence_scope", generation_metadata_payload)
                self.assertIn("structural guidance only", generation_metadata_payload["pattern_evidence_scope"])
                self.assertIn("organization_audit", generation_metadata_payload)
                self.assertIn("metrics", generation_metadata_payload["organization_audit"])
                policy_metadata = generation_metadata_payload.get("generation_policy") or {}
                self.assertTrue(policy_metadata.get("pattern_prompt_cards"))
                self.assertIn("prompt_card_audits", generation_metadata_payload["organization_audit"])
                generation_metadata_action = await client.post(
                    f"/projects/{project_id}/chapters/{generated_node_id}/versions/{selected_version_id}/generation-metadata/revision-action",
                    json={"action": "request_human_input"},
                )
                self.assertEqual(200, generation_metadata_action.status_code)
                generation_metadata_action_payload = generation_metadata_action.json()
                self.assertEqual("human_input_required", generation_metadata_action_payload["kind"])
                self.assertEqual("request_human_input", generation_metadata_action_payload["action"])
                self.assertIn("metrics", generation_metadata_action_payload["audit"])
                content_revision = await client.get(
                    f"/projects/{project_id}/chapters/{generated_node_id}/versions/{selected_version_id}/content-revision-plan"
                )
                self.assertEqual(200, content_revision.status_code)
                content_revision_payload = content_revision.json()
                self.assertEqual(selected_version_id, content_revision_payload["version_id"])
                self.assertIn("candidate_count", content_revision_payload["metrics"])
                self.assertIn("evidence_targeted_rewrite_count", content_revision_payload["metrics"])
                self.assertIn("items", content_revision_payload)
                self.assertGreater(len(content_revision_payload["items"]), 0)
                content_item = next(
                    (
                        item
                        for item in content_revision_payload["items"]
                        if "omitted_required_source_facts" in str(item.get("reason") or "")
                    ),
                    content_revision_payload["items"][0],
                )
                content_action = await client.post(
                    f"/projects/{project_id}/chapters/{generated_node_id}/versions/{selected_version_id}/content-nodes/{content_item['content_node_id']}/revision-action",
                    json={"action": "rewrite_subsection"},
                )
                self.assertEqual(200, content_action.status_code)
                content_action_payload = content_action.json()
                self.assertEqual("content_revision_version", content_action_payload["kind"])
                self.assertNotEqual(selected_version_id, content_action_payload["new_version_id"])
                self.assertTrue(content_action_payload["trace_path"].endswith(".content_revision_trace.json"))
                trace_payload = json.loads(Path(content_action_payload["trace_path"]).read_text(encoding="utf-8-sig"))
                self.assertIn("required_facts", trace_payload)
                self.assertIn("content_revision_required_facts", trace_payload["prompt"])
                self.assertIn("本小节已按小节级修订动作重新组织", content_action_payload["version"]["markdown"])
                version_payload = content_action_payload["version"]
                self.assertIn("generation_metadata", version_payload)
                self.assertIn("content_revision_history", version_payload["generation_metadata"])
                self.assertEqual(
                    content_action_payload["trace_path"],
                    version_payload["generation_metadata"]["last_content_revision_trace_path"],
                )
                self.assertIn("evidence_audit", version_payload)
                self.assertIn("required_source_facts", version_payload["evidence_audit"])
                if trace_payload["required_facts"]:
                    required_fact_ids = {fact["fact_id"] for fact in trace_payload["required_facts"]}
                    omitted_after_revision = set(version_payload["evidence_audit"].get("omitted_required_fact_ids") or [])
                    self.assertFalse(required_fact_ids & omitted_after_revision)

                split_action = await client.post(
                    f"/projects/{project_id}/chapters/{generated_node_id}/versions/{content_action_payload['new_version_id']}/content-nodes/{content_item['content_node_id']}/revision-action",
                    json={"action": "split_subsection"},
                )
                self.assertEqual(200, split_action.status_code)
                split_payload = split_action.json()
                self.assertEqual("outline_proposal", split_payload["kind"])
                self.assertEqual("outline", split_payload["proposal"]["target_type"])
                self.assertTrue(any(node.get("parent_id") == generated_node_id for node in split_payload["proposal"]["preview"]["nodes"]))
                applied_split = await client.post(f"/projects/{project_id}/outline/proposals/{split_payload['proposal']['id']}/apply")
                self.assertEqual(200, applied_split.status_code)
                self.assertGreater(applied_split.json()["chapter_task_count"], 0)
                nodes_after_content_split = (await client.get(f"/projects/{project_id}/outline-nodes")).json()
                split_child = next(
                    node
                    for node in nodes_after_content_split
                    if node.get("parent_id") == generated_node_id
                    and any("content_node_id" in str(value) for value in node.get("source_rules", []))
                )
                self.assertTrue(
                    any(
                        node.get("parent_id") == generated_node_id
                        and any("content_node_id" in str(value) for value in node.get("source_rules", []))
                        for node in nodes_after_content_split
                    )
                )
                chapters_after_split = await client.get(f"/projects/{project_id}/chapters")
                self.assertEqual(200, chapters_after_split.status_code)
                self.assertTrue(any(item["node_id"] == split_child["node_id"] for item in chapters_after_split.json()))

                split_child_generated = await client.post(f"/projects/{project_id}/chapters/{split_child['node_id']}/generate")
                self.assertEqual(200, split_child_generated.status_code)
                self.assertEqual(split_child["node_id"], split_child_generated.json()["node_id"])
                split_child_workspace = await client.get(f"/projects/{project_id}/chapters/{split_child['node_id']}/workspace")
                self.assertEqual(200, split_child_workspace.status_code)
                self.assertTrue(split_child_workspace.json().get("selected_version_id"))

                gates_after_generation = await client.get(f"/projects/{project_id}/pipeline-gates")
                self.assertEqual(200, gates_after_generation.status_code)
                gates_after_payload = gates_after_generation.json()
                after_by_name = {item["name"]: item for item in gates_after_payload["gates"]}
                self.assertIn(after_by_name["generation"]["status"], {"passed", "warning", "blocked"})
                self.assertIn(after_by_name["revision"]["status"], {"passed", "warning", "blocked"})

                revisions = await client.get(f"/projects/{project_id}/revision-decisions")
                self.assertEqual(200, revisions.status_code)
                revision_payload = revisions.json()
                self.assertGreater(len(revision_payload["decisions"]), 0)
                self.assertTrue(all("decision" in item for item in revision_payload["decisions"]))

                actions_after_generation = await client.get(f"/projects/{project_id}/pipeline-actions")
                self.assertEqual(200, actions_after_generation.status_code)
                actions_after_payload = actions_after_generation.json()
                self.assertTrue(any(item["stage"] in {"revision", "version", "merge"} for item in actions_after_payload["actions"]))

                targeted_revision = await client.get(f"/projects/{project_id}/targeted-revision-plan")
                self.assertEqual(200, targeted_revision.status_code)
                targeted_payload = targeted_revision.json()
                self.assertEqual(1, targeted_payload["project_count"])
                self.assertIn(
                    targeted_payload["rerun_policy"],
                    {
                        "no_regeneration_required",
                        "chapter_level_revision_only",
                        "targeted_project_controls_then_chapter_revision",
                        "outline_repair_before_chapter_generation",
                        "partial_validation_before_full_run",
                    },
                )
                self.assertIn("projects", targeted_payload)
                self.assertTrue(targeted_payload["artifact_json_path"].endswith("targeted_revision_plan.json"))
                self.assertTrue(targeted_payload["artifact_markdown_path"].endswith("targeted_revision_plan.md"))
                targeted_markdown = Path(targeted_payload["artifact_markdown_path"]).read_text(encoding="utf-8-sig")
                self.assertIn("Targeted Revision Plan", targeted_markdown)

                directory_after_generation = await client.get(f"/projects/{project_id}/directory")
                self.assertEqual(200, directory_after_generation.status_code)
                self.assertIn("revision_decisions", directory_after_generation.json())


    def test_generation_metadata_expand_subsections_creates_traceable_outline_proposal(self) -> None:
        import asyncio

        asyncio.run(self._run_generation_metadata_expand_flow())

    async def _run_generation_metadata_expand_flow(self) -> None:
        repo_root = Path(__file__).resolve().parents[2]
        sample = (repo_root / "src" / "coalplan" / "assets" / "samples" / "coal_fire_bid.normalized.md").read_text(
            encoding="utf-8-sig"
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            app = create_app(Settings(storage_dir=Path(temp_dir), llm_provider="fake"))
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
                created = await client.post("/projects", json={"name": "metadata-expand", "template_id": "coal_fire"})
                self.assertEqual(200, created.status_code)
                project_id = created.json()["id"]
                uploaded = await client.post(
                    f"/projects/{project_id}/bid-markdown",
                    json={"file_name": "bid.md", "content": sample},
                )
                self.assertEqual(200, uploaded.status_code)
                directory = await client.post(f"/projects/{project_id}/directory")
                self.assertEqual(200, directory.status_code)

                outline_nodes = (await client.get(f"/projects/{project_id}/outline-nodes")).json()
                parent = next(node for node in outline_nodes if node.get("source_rules") or node.get("auto_fill"))
                version = app.state.workspace_store.create_chapter_version(
                    project_id,
                    parent["node_id"],
                    title=parent["title"],
                    markdown="# Thin chapter\n\n## 生成正文\n\n本节仅概括施工组织安排。\n\n## 人工补充需补充\n\n【需人工补充：审批参数。】\n",
                    source_type="manual_edit",
                    created_by="test",
                    select=True,
                    generation_metadata={
                        "selected_pattern_keys": [],
                        "pattern_evidence_scope": "structural guidance only",
                        "generation_policy": {
                            "pattern_prompt_cards": [
                                {
                                    "pattern_key": "craft",
                                    "generation_moves": [
                                        "按施工准备、测量放样、工艺流程、过程控制、检查验收组织工艺正文",
                                        "把人员、设备、材料、作业条件写入工序实施前置条件",
                                    ],
                                    "source_mapping_requirements": [
                                        "Map process, resource, process-control, inspection, and acceptance evidence before writing.",
                                    ],
                                    "human_only_items": ["approved final construction parameters"],
                                    "revision_checks": ["split subsection when craft cue groups are missing"],
                                }
                            ]
                        },
                    },
                )

                action = await client.post(
                    f"/projects/{project_id}/chapters/{parent['node_id']}/versions/{version['id']}/generation-metadata/revision-action",
                    json={"action": "expand_subsections"},
                )
                self.assertEqual(200, action.status_code)
                payload = action.json()
                self.assertEqual("outline_proposal", payload["kind"])
                self.assertEqual("expand_subsections", payload["action"])
                preview_nodes = payload["proposal"]["preview"]["nodes"]
                self.assertTrue(preview_nodes)
                self.assertTrue(any(node.get("parent_id") == parent["node_id"] for node in preview_nodes))
                self.assertTrue(
                    any("Generation metadata audit requested" in " ".join(node.get("source_rules") or []) for node in preview_nodes)
                )
                self.assertTrue(any("section_id/evidence_id" in " ".join(node.get("special_notes") or []) for node in preview_nodes))

                applied = await client.post(f"/projects/{project_id}/outline/proposals/{payload['proposal']['id']}/apply")
                self.assertEqual(200, applied.status_code)
                self.assertEqual("applied", applied.json()["status"])
                self.assertGreater(applied.json()["chapter_task_count"], 0)
                chapters = await client.get(f"/projects/{project_id}/chapters")
                self.assertEqual(200, chapters.status_code)
                chapter_node_ids = {item["node_id"] for item in chapters.json()}
                self.assertTrue(any(node["node_id"] in chapter_node_ids for node in preview_nodes))

                branch_actions = await client.get(f"/projects/{project_id}/pipeline-actions")
                self.assertEqual(200, branch_actions.status_code)
                branch_action_payload = branch_actions.json()
                branch_action = next(
                    (
                        item
                        for item in branch_action_payload["actions"]
                        if item["action_id"] == f"generation.child_branch.{parent['node_id']}"
                    ),
                    None,
                )
                self.assertIsNotNone(branch_action)
                self.assertEqual("generate_child_chapters", branch_action["action"])
                self.assertIn(f"/chapters/{parent['node_id']}/children/generate", branch_action["endpoint"])

                child_generation = await client.post(
                    f"/projects/{project_id}/chapters/{parent['node_id']}/children/generate",
                    json={"recursive": False, "only_pending": False},
                )
                self.assertEqual(200, child_generation.status_code)
                child_payload = child_generation.json()
                self.assertEqual(parent["node_id"], child_payload["parent_node_id"])
                self.assertIn(child_payload["status"], {"completed", "partial_failed", "failed"})
                self.assertGreater(child_payload["candidate_count"], 0)
                self.assertTrue(child_payload["artifact_json_path"].endswith(".json"))
                generated_ids = {item["node_id"] for item in child_payload["generated"]}
                self.assertTrue(generated_ids)
                self.assertTrue(generated_ids <= chapter_node_ids)
                self.assertTrue(all(item.get("selected_version_id") for item in child_payload["generated"]))


if __name__ == "__main__":
    unittest.main()
