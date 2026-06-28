from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import httpx

from coalplan.main import create_app
from coalplan.settings import Settings


class PatternLibraryApiTest(unittest.TestCase):
    def test_pattern_library_can_be_viewed_and_refreshed_from_local_corpus(self) -> None:
        import asyncio

        asyncio.run(self._run_flow())

    async def _run_flow(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp = Path(temp_dir)
            corpus = temp / "corpus"
            output = temp / "pattern-output"
            corpus.mkdir()
            (corpus / "煤火治理施工组织设计.txt").write_text(
                "\n".join(
                    [
                        "目录结构：",
                        "第一章 工程概况",
                        "1.1 主要工程量",
                        "第二章 钻孔与灌浆施工方法",
                        "第三章 安全保证措施",
                    ]
                ),
                encoding="utf-8",
            )
            (corpus / "市政雨污管网施工组织设计.txt").write_text(
                "\n".join(
                    [
                        "目录结构：",
                        "第一章 施工部署",
                        "第二章 施工进度计划",
                        "第三章 质量保证体系",
                        "第四章 环境保护及文明施工措施",
                    ]
                ),
                encoding="utf-8",
            )

            app = create_app(Settings(storage_dir=temp / "runtime", llm_provider="fake"))
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
                active = await client.get("/pattern-library")
                self.assertEqual(200, active.status_code)
                active_payload = active.json()
                self.assertIn("craft", active_payload["library"]["patterns"])

                history = await client.get("/pattern-library/apply-history")
                self.assertEqual(200, history.status_code)
                history_payload = history.json()
                self.assertIn("history", history_payload)
                self.assertIn("apply_history_path", history_payload)

                refreshed = await client.post(
                    "/pattern-library/analyze",
                    json={"corpus_dir": str(corpus), "output_dir": str(output)},
                )
                self.assertEqual(200, refreshed.status_code)
                refreshed_payload = refreshed.json()
                self.assertEqual(2, refreshed_payload["analysis"]["sample_count"])
                self.assertTrue(Path(refreshed_payload["analysis_json_path"]).exists())
                self.assertTrue(Path(refreshed_payload["generated_path"]).exists())
                self.assertIn("craft", refreshed_payload["generated_library"]["patterns"])

                generated = await client.get(
                    "/pattern-library/generated",
                    params={"generated_path": refreshed_payload["generated_path"]},
                )
                self.assertEqual(200, generated.status_code)
                self.assertTrue(generated.json()["generated_available"])

                audit = await client.post(
                    "/pattern-library/audit",
                    json={
                        "generated_path": refreshed_payload["generated_path"],
                        "corpus_dir": str(corpus),
                        "output_dir": str(output),
                    },
                )
                self.assertEqual(200, audit.status_code)
                audit_payload = audit.json()
                self.assertIn(audit_payload["report"]["status"], {"passed", "warning", "blocked"})
                self.assertTrue(Path(audit_payload["artifact_json_path"]).exists())
                self.assertTrue(Path(audit_payload["artifact_markdown_path"]).exists())
                self.assertIn("pattern_audits", audit_payload["report"])

                built = await client.post(
                    "/pattern-library/build-skill",
                    json={"corpus_dir": str(corpus), "output_dir": str(output / "build-skill")},
                )
                self.assertEqual(200, built.status_code)
                built_payload = built.json()
                self.assertEqual(2, built_payload["analysis"]["sample_count"])
                self.assertTrue(Path(built_payload["generated_path"]).exists())
                self.assertTrue(Path(built_payload["coverage_markdown_path"]).exists())
                self.assertTrue(Path(built_payload["skill_manifest_path"]).exists())
                self.assertTrue(
                    (Path(built_payload["skill_package_dir"]) / "references" / "writing-pattern-cards.json").exists()
                )
                self.assertEqual(
                    built_payload["coverage_report"]["status"],
                    built_payload["skill_package"]["manifest"]["coverage_status"],
                )

                learned = await client.post(
                    "/pattern-library/learn-from-quality-iteration",
                    json={
                        "output_dir": str(output),
                        "learning_report": {
                            "project_id": "project_demo",
                            "status": "warning",
                            "summary": "demo",
                            "metrics": {},
                            "suggestions": [
                                {
                                    "pattern_key": "craft",
                                    "suggestion_type": "strengthen_required_source_facts",
                                    "severity": "warning",
                                    "reason": "source parameters were omitted",
                                    "evidence": ["0.5MPa grouting pressure parameter"],
                                    "suggested_text": [],
                                },
                                {
                                    "pattern_key": "quality",
                                    "suggestion_type": "add_outline_guidance",
                                    "severity": "warning",
                                    "reason": "human heading missing",
                                    "evidence": ["Quality inspection and acceptance records"],
                                    "suggested_text": [],
                                },
                            ],
                        },
                    },
                )
                self.assertEqual(200, learned.status_code)
                learned_payload = learned.json()
                self.assertTrue(Path(learned_payload["generated_path"]).exists())
                self.assertTrue(Path(learned_payload["learning_candidate_markdown_path"]).exists())
                self.assertGreaterEqual(len(learned_payload["changes"]), 2)
                self.assertIn("控制参数", learned_payload["generated_library"]["patterns"]["craft"]["required_source_facts"])

                self.assertEqual([0, 1], [item["suggestion_index"] for item in learned_payload["changes"]])
                craft_change = learned_payload["changes"][0]
                self.assertIn("added_items", craft_change)
                self.assertTrue(craft_change["added_items"])
                self.assertTrue(
                    set(craft_change["added_items"]).intersection({"required_source_facts", "revision_signals", "corpus_basis"})
                )

                selected_learned = await client.post(
                    "/pattern-library/learn-from-quality-iteration",
                    json={
                        "output_dir": str(output / "selected"),
                        "selected_suggestion_indexes": [1],
                        "learning_report": {
                            "project_id": "project_demo",
                            "status": "warning",
                            "summary": "demo",
                            "metrics": {},
                            "suggestions": [
                                {
                                    "pattern_key": "craft",
                                    "suggestion_type": "strengthen_required_source_facts",
                                    "severity": "warning",
                                    "reason": "source parameters were omitted",
                                    "evidence": ["0.5MPa grouting pressure parameter"],
                                    "suggested_text": [],
                                },
                                {
                                    "pattern_key": "quality",
                                    "suggestion_type": "add_outline_guidance",
                                    "severity": "warning",
                                    "reason": "human heading missing",
                                    "evidence": ["Quality inspection and acceptance records"],
                                    "suggested_text": [],
                                },
                            ],
                        },
                    },
                )
                self.assertEqual(200, selected_learned.status_code)
                selected_payload = selected_learned.json()
                self.assertEqual([1], selected_payload["selected_suggestion_indexes"])
                self.assertEqual([1], [item["suggestion_index"] for item in selected_payload["changes"]])
                self.assertNotIn(
                    "鎺у埗鍙傛暟",
                    selected_payload["generated_library"]["patterns"]["craft"]["required_source_facts"],
                )

                learned_generated = await client.get(
                    "/pattern-library/generated",
                    params={"generated_path": learned_payload["generated_path"]},
                )
                self.assertEqual(200, learned_generated.status_code)
                self.assertTrue(learned_generated.json()["generated_available"])

                skill = await client.get("/pattern-library/skill")
                self.assertEqual(200, skill.status_code)
                skill_payload = skill.json()
                self.assertIn("Construction Organization Writing Skill", skill_payload["markdown"])
                self.assertIn("validation_issues", skill_payload)
                self.assertIn("coverage_report", skill_payload)
                self.assertIn(skill_payload["coverage_report"]["status"], {"passed", "warning", "blocked"})

                prompt_cards = await client.get("/pattern-library/prompt-cards")
                self.assertEqual(200, prompt_cards.status_code)
                cards_payload = prompt_cards.json()
                self.assertEqual(active_payload["library"]["version"], cards_payload["version"])
                self.assertIn("craft", cards_payload["cards"])
                self.assertIn("source_mapping", cards_payload["stage_usage"])
                self.assertIn("source_mapping_requirements", cards_payload["cards"]["craft"])
                self.assertIn("revision_checks", cards_payload["cards"]["craft"])
                self.assertIn("Structural guidance only", cards_payload["evidence_scope"])

                generated_prompt_cards = await client.get(
                    "/pattern-library/prompt-cards",
                    params={"generated_path": learned_payload["generated_path"]},
                )
                self.assertEqual(200, generated_prompt_cards.status_code)
                generated_cards_payload = generated_prompt_cards.json()
                self.assertEqual(
                    learned_payload["generated_library"]["version"],
                    generated_cards_payload["version"],
                )
                self.assertIn("craft", generated_cards_payload["cards"])

                skill_path = temp / "writing-skill.md"
                exported = await client.post(
                    "/pattern-library/skill/export",
                    json={"output_path": str(skill_path)},
                )
                self.assertEqual(200, exported.status_code)
                self.assertTrue(skill_path.exists())
                self.assertEqual(str(skill_path.resolve()), exported.json()["output_path"])

                package_dir = temp / "writing-skill-package"
                package = await client.post(
                    "/pattern-library/skill/export",
                    json={"output_dir": str(package_dir)},
                )
                self.assertEqual(200, package.status_code)
                package_payload = package.json()
                self.assertTrue((package_dir / "SKILL.md").exists())
                self.assertTrue((package_dir / "references" / "writing-pattern-cards.md").exists())
                self.assertTrue((package_dir / "references" / "writing-pattern-cards.json").exists())
                self.assertTrue((package_dir / "references" / "pipeline-blueprint.md").exists())
                self.assertTrue((package_dir / "references" / "pattern-library-coverage.md").exists())
                self.assertIn("package_paths", package_payload)
                self.assertEqual(str((package_dir / "SKILL.md").resolve()), package_payload["package_paths"]["skill"])
                self.assertEqual(
                    str((package_dir / "references" / "writing-pattern-cards.json").resolve()),
                    package_payload["package_paths"]["writing_pattern_cards_json"],
                )
                self.assertEqual(
                    str((package_dir / "references" / "pipeline-blueprint.md").resolve()),
                    package_payload["package_paths"]["pipeline_blueprint"],
                )
                self.assertIn("writing_pattern_cards_json", package_payload["manifest"]["files"])
                self.assertIn("pipeline_blueprint", package_payload["manifest"]["files"])
                self.assertIn(
                    "Selected Version Review",
                    (package_dir / "references" / "pipeline-blueprint.md").read_text(encoding="utf-8"),
                )
                self.assertEqual(
                    str((package_dir / "references" / "pattern-library-coverage.md").resolve()),
                    package_payload["package_paths"]["coverage_report"],
                )


if __name__ == "__main__":
    unittest.main()
