from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from coalplan.application.pattern_library_admin import (
    apply_generated_pattern_library,
    build_reviewable_pattern_skill_from_corpus,
    build_pattern_library_candidate_from_learning_report,
)
from coalplan.application.pattern_library_coverage import audit_pattern_library_coverage, render_pattern_library_coverage_markdown
from coalplan.application.pattern_skill_export import (
    export_pattern_skill_markdown,
    export_pattern_skill_package,
    validate_pattern_library,
)
from coalplan.application.serialization import dump_model, to_json_text
from coalplan.application.writing_pattern_library import (
    WritingPatternLibrary,
    build_pattern_prompt_card,
    load_writing_pattern_library,
    match_patterns_for_text,
    render_pattern_prompt_card,
    render_pattern_for_prompt,
    render_pattern_matches_for_prompt,
)


class WritingPatternLibraryTest(unittest.TestCase):
    def test_loads_local_corpus_pattern_library(self) -> None:
        library = load_writing_pattern_library()

        self.assertIn("craft", library.patterns)
        self.assertIn("overview", library.patterns)
        self.assertIn("质量", "".join(library.patterns["quality"].aliases))
        self.assertIn("本地语料样本数：34", "".join(library.patterns["craft"].corpus_basis))
        self.assertIn("施工工艺流程", library.patterns["craft"].corpus_common_headings)

    def test_renders_prompt_rules_with_human_only_items(self) -> None:
        rendered = render_pattern_for_prompt("craft")

        self.assertIn("pattern_key: craft", rendered)
        self.assertIn("required_source_facts", rendered)
        self.assertIn("human_only_items", rendered)
        self.assertIn("revision_signals", rendered)
        self.assertIn("local_corpus_common_headings", rendered)
        self.assertIn("evidence_scope", rendered)
        self.assertIn("organization_policy", rendered)
        self.assertIn("source_mapping_requirements", rendered)
        self.assertIn("detail_design_rules", rendered)
        self.assertIn("generation_moves", rendered)

    def test_builds_reusable_prompt_card_for_generation_stages(self) -> None:
        library = load_writing_pattern_library()
        card = build_pattern_prompt_card(library.patterns["craft"], match_score="primary guidance")
        rendered = render_pattern_prompt_card(card)

        self.assertEqual("craft", card.pattern_key)
        self.assertIn("section_id/evidence_id", card.evidence_scope)
        self.assertTrue(card.outline_guidance)
        self.assertTrue(card.organization_policy)
        self.assertTrue(card.source_mapping_requirements)
        self.assertTrue(card.detail_design_rules)
        self.assertTrue(card.generation_moves)
        self.assertTrue(card.revision_checks)
        self.assertIn("primary guidance", rendered)
        self.assertIn("Do not imitate human reference wording", rendered)
        self.assertIn("never invent the fact from the pattern", rendered)

    def test_matches_patterns_from_template_text(self) -> None:
        matches = match_patterns_for_text("钻孔 灌浆 施工工艺 质量检查", limit=2)

        self.assertGreaterEqual(len(matches), 1)
        self.assertEqual("craft", matches[0].pattern_key)
        self.assertGreater(matches[0].score, 0)
        self.assertTrue(matches[0].required_source_facts)

    def test_renders_matched_patterns_for_prompt(self) -> None:
        rendered = render_pattern_matches_for_prompt("工程概况 施工范围", primary_key="overview")

        self.assertIn("match_score", rendered)
        self.assertIn("pattern_key: overview", rendered)

    def test_apply_generated_pattern_library_writes_backup(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp = Path(temp_dir)
            active = temp / "writing_patterns.json"
            generated = temp / "writing_patterns.generated.json"
            library = load_writing_pattern_library()
            active.write_text(to_json_text(dump_model(library)), encoding="utf-8")
            generated_library = library.model_copy(update={"version": "unit-test-generated"})
            generated.write_text(to_json_text(dump_model(generated_library)), encoding="utf-8")

            result = apply_generated_pattern_library(generated_path=generated, active_path=active)

            self.assertTrue(result["applied"])
            self.assertTrue(Path(result["backup_path"]).exists())
            self.assertTrue(Path(result["apply_log_path"]).exists())
            self.assertTrue(Path(result["apply_history_path"]).exists())
            self.assertIn(result["coverage_status"], {"passed", "warning", "blocked"})
            self.assertIn("coverage_report", result)
            self.assertIn("unit-test-generated", Path(result["apply_log_path"]).read_text(encoding="utf-8"))
            history = json.loads(Path(result["apply_history_path"]).read_text(encoding="utf-8"))
            self.assertEqual(1, len(history))
            self.assertEqual("unit-test-generated", history[-1]["library_version"])
            self.assertEqual(result["coverage_status"], history[-1]["coverage_status"])
            self.assertEqual(1, result["apply_history_count"])
            self.assertIn("unit-test-generated", active.read_text(encoding="utf-8"))

    def test_exports_reviewable_pattern_skill_markdown(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            output_path = Path(temp_dir) / "writing-skill.md"

            result = export_pattern_skill_markdown(output_path=output_path)

            self.assertTrue(output_path.exists())
            self.assertIn("Construction Organization Writing Skill", result["markdown"])
            self.assertIn("### craft", result["markdown"])
            self.assertIn("section_id", result["markdown"])
            self.assertIn("evidence_id", result["markdown"])
            self.assertIn("never a factual source", result["markdown"])
            self.assertIn("not to make generated paragraphs identical", result["markdown"])
            self.assertIn("local_corpus_common_headings", result["markdown"])
            self.assertIn("How To Use In The Pipeline", result["markdown"])
            self.assertIn("Chapter Markdown Contract", result["markdown"])
            self.assertIn("Revision Decision Hints", result["markdown"])
            self.assertIn("quality_feedback_required_facts", result["markdown"])
            self.assertIn("Prompt card", result["markdown"])
            self.assertIn("source_mapping_requirements", result["markdown"])
            self.assertIn("Coverage Audit", result["markdown"])
            self.assertIn("coverage_report", result)
            self.assertEqual(str(output_path.resolve()), result["output_path"])

    def test_learning_candidate_preserves_evidence_targeted_revision_signal_for_skill_export(self) -> None:
        learning_report = {
            "project_id": "project_demo",
            "status": "warning",
            "suggestions": [
                {
                    "pattern_key": "craft",
                    "suggestion_type": "strengthen_required_source_facts",
                    "severity": "warning",
                    "reason": "Source facts were available but not absorbed into generated text.",
                    "evidence": [
                        "Insert omitted required source fact `ev_water:fact_1` from evidence `ev_water` / section `sec_water`: crack water injection uses duckbill nozzle and pressure 0.2-0.3MPa."
                    ],
                    "suggested_text": [
                        "Add these fact types or representative terms to `required_source_facts` or source-mapping requirements."
                    ],
                },
                {
                    "pattern_key": "craft",
                    "suggestion_type": "add_revision_signal",
                    "severity": "warning",
                    "reason": "Evidence-targeted subsection rewrite was required.",
                    "evidence": [
                        "content_node:rewrite_subsection:Crack water injection pressure control:evidence_targeted"
                    ],
                    "suggested_text": [
                        "Treat evidence-targeted subsection rewrite as a source-fact absorption failure: the next retry must carry the omitted fact id, evidence id, section id, and fact text."
                    ],
                },
            ],
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            result = build_pattern_library_candidate_from_learning_report(
                learning_report=learning_report,
                output_dir=temp_dir,
            )

            craft = result["generated_library"]["patterns"]["craft"]
            self.assertIn(
                "Treat evidence-targeted subsection rewrite as a source-fact absorption failure",
                "\n".join(craft["revision_signals"]),
            )
            self.assertIn("duckbill nozzle", "\n".join(craft["corpus_basis"]))
            added_items = "\n".join(
                value
                for change in result["changes"]
                for values in (change.get("added_items") or {}).values()
                for value in values
            )
            self.assertIn("source-fact absorption failure", added_items)
            skill = export_pattern_skill_markdown(
                library=WritingPatternLibrary.model_validate(result["generated_library"])
            )
            self.assertIn("evidence-targeted subsection rewrite", skill["markdown"])

    def test_exports_reusable_pattern_skill_package(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir) / "construction-org-writing-patterns"

            result = export_pattern_skill_package(output_dir=output_dir)

            self.assertEqual(str(output_dir.resolve()), result["output_dir"])
            self.assertTrue((output_dir / "SKILL.md").exists())
            self.assertTrue((output_dir / "references" / "writing-pattern-cards.md").exists())
            self.assertTrue((output_dir / "references" / "writing-pattern-cards.json").exists())
            self.assertTrue((output_dir / "references" / "pipeline-control.md").exists())
            self.assertTrue((output_dir / "references" / "pipeline-blueprint.md").exists())
            self.assertTrue((output_dir / "references" / "pattern-library-coverage.md").exists())
            self.assertTrue((output_dir / "manifest.json").exists())
            self.assertIn("Required References", (output_dir / "SKILL.md").read_text(encoding="utf-8"))
            self.assertIn("pipeline-blueprint.md", (output_dir / "SKILL.md").read_text(encoding="utf-8"))
            self.assertIn("Coverage Audit", (output_dir / "SKILL.md").read_text(encoding="utf-8"))
            cards = (output_dir / "references" / "writing-pattern-cards.md").read_text(encoding="utf-8")
            self.assertIn("Writing Pattern Cards", cards)
            self.assertIn("source_mapping_requirements", cards)
            self.assertIn("not source evidence", cards)
            cards_json = json.loads((output_dir / "references" / "writing-pattern-cards.json").read_text(encoding="utf-8"))
            self.assertEqual("local-corpus-34", cards_json["version"])
            self.assertIn("cards", cards_json)
            self.assertIn("craft", cards_json["cards"])
            self.assertIn("stage_usage", cards_json)
            self.assertIn("source_mapping", cards_json["stage_usage"])
            self.assertIn("source_mapping_requirements", cards_json["cards"]["craft"])
            self.assertIn("revision_checks", cards_json["cards"]["craft"])
            self.assertIn("Structural guidance only", cards_json["evidence_scope"])
            blueprint = (output_dir / "references" / "pipeline-blueprint.md").read_text(encoding="utf-8")
            self.assertIn("Pipeline Blueprint", blueprint)
            self.assertIn("Selected Version Review", blueprint)
            self.assertIn("return_to_version_review", blueprint)
            pipeline_control = (output_dir / "references" / "pipeline-control.md").read_text(encoding="utf-8")
            self.assertIn("Evidence-targeted subsection rewrites", pipeline_control)
            self.assertIn("Version review", pipeline_control)
            self.assertIn("after version review is clear", pipeline_control)
            coverage = (output_dir / "references" / "pattern-library-coverage.md").read_text(encoding="utf-8")
            self.assertIn("Pattern Library Coverage Audit", coverage)
            self.assertIn("construction-org-writing-patterns", result["manifest"]["name"])
            self.assertIn(result["manifest"]["coverage_status"], {"passed", "warning", "blocked"})
            self.assertIn("pipeline_blueprint", result["manifest"]["files"])
            self.assertIn("writing_pattern_cards_json", result["manifest"]["files"])
            self.assertIn("pipeline_blueprint", result["package_paths"])
            self.assertIn("writing_pattern_cards_json", result["package_paths"])
            self.assertIn("coverage_report", result["package_paths"])

    def test_builds_reviewable_pattern_skill_from_local_corpus(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp = Path(temp_dir)
            corpus = temp / "corpus"
            output = temp / "reviewable-skill-build"
            corpus.mkdir()
            (corpus / "coal-fire.txt").write_text(
                "\n".join(
                    [
                        "目录结构：",
                        "第一章 工程概况",
                        "1.1 主要工程量",
                        "第二章 钻孔与灌浆施工工艺",
                        "第三章 质量保证措施",
                        "第四章 安全保证措施",
                    ]
                ),
                encoding="utf-8",
            )
            (corpus / "municipal.txt").write_text(
                "\n".join(
                    [
                        "目录结构：",
                        "第一章 施工部署",
                        "第二章 施工进度计划",
                        "第三章 环境保护及文明施工措施",
                    ]
                ),
                encoding="utf-8",
            )

            result = build_reviewable_pattern_skill_from_corpus(corpus_dir=corpus, output_dir=output)

            self.assertEqual(2, result["analysis"]["sample_count"])
            self.assertTrue(Path(result["analysis_json_path"]).exists())
            self.assertTrue(Path(result["generated_path"]).exists())
            self.assertTrue(Path(result["coverage_json_path"]).exists())
            self.assertTrue(Path(result["coverage_markdown_path"]).exists())
            self.assertTrue(Path(result["skill_manifest_path"]).exists())
            package_dir = Path(result["skill_package_dir"])
            self.assertTrue((package_dir / "SKILL.md").exists())
            self.assertTrue((package_dir / "references" / "writing-pattern-cards.json").exists())
            self.assertIn(result["coverage_report"]["status"], {"passed", "warning", "blocked"})
            self.assertEqual(
                result["coverage_report"]["status"],
                result["skill_package"]["manifest"]["coverage_status"],
            )

    def test_pattern_skill_validation_flags_missing_required_patterns(self) -> None:
        library = load_writing_pattern_library()
        reduced = library.model_copy(update={"patterns": {"craft": library.patterns["craft"]}})

        issues = validate_pattern_library(reduced)

        codes = {issue["code"] for issue in issues}
        self.assertIn("missing_required_pattern", codes)

    def test_pattern_coverage_audit_reports_required_pattern_depth(self) -> None:
        library = load_writing_pattern_library()

        report = audit_pattern_library_coverage(library)

        self.assertIn(report.status, {"passed", "warning"})
        self.assertEqual(0, report.metrics["missing_required_pattern_count"])
        self.assertGreaterEqual(report.metrics["coverage_ratio"], 1)
        self.assertTrue(report.pattern_audits)
        rendered = render_pattern_library_coverage_markdown(report)
        self.assertIn("Pattern Library Coverage Audit", rendered)
        self.assertIn("Pattern Audits", rendered)

    def test_pattern_coverage_audit_blocks_missing_required_patterns(self) -> None:
        library = load_writing_pattern_library()
        reduced = library.model_copy(update={"patterns": {"craft": library.patterns["craft"]}})

        report = audit_pattern_library_coverage(reduced)

        self.assertEqual("blocked", report.status)
        codes = {issue.code for issue in report.issues}
        self.assertIn("missing_required_pattern", codes)
        self.assertGreater(report.metrics["missing_required_pattern_count"], 0)


if __name__ == "__main__":
    unittest.main()
