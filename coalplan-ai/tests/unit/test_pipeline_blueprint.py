from __future__ import annotations

import unittest

from coalplan.application.pipeline_blueprint import build_pipeline_blueprint, render_pipeline_blueprint_markdown


class PipelineBlueprintTest(unittest.TestCase):
    def test_blueprint_declares_reusable_generation_stages(self) -> None:
        blueprint = build_pipeline_blueprint()
        stage_ids = [stage.stage_id for stage in blueprint.stages]

        self.assertEqual("construction_org_generation_pipeline", blueprint.blueprint_id)
        self.assertTrue(
            {
                "input",
                "profile",
                "outline",
                "coverage",
                "detail",
                "mapping",
                "generation",
                "revision",
                "quality_feedback",
                "version",
                "merge",
            }.issubset(stage_ids)
        )
        self.assertTrue(any("Source mapping is a gate" in item for item in blueprint.invariants))
        mapping = next(stage for stage in blueprint.stages if stage.stage_id == "mapping")
        self.assertIn("mapping/{node_id}.evidence.md", mapping.persisted_artifacts)
        self.assertIn("remap_sources", mapping.failure_routes)
        generation = next(stage for stage in blueprint.stages if stage.stage_id == "generation")
        self.assertEqual("strict Markdown chapter writing under fixed contract", generation.llm_role)
        self.assertIn("database:chapter_versions", generation.persisted_artifacts)
        version = next(stage for stage in blueprint.stages if stage.stage_id == "version")
        self.assertEqual("Selected Version Review", version.title)
        self.assertIn("chapters/{node_id}/versions/{version_id}.evidence_audit.json", version.persisted_artifacts)
        self.assertIn("chapters/{node_id}/versions/{version_id}.generation_metadata.json", version.persisted_artifacts)
        self.assertIn("version.review_evidence_utilization", version.related_actions)
        self.assertIn("version.review_generation_metadata", version.related_actions)
        merge = next(stage for stage in blueprint.stages if stage.stage_id == "merge")
        self.assertIn("only after version review", merge.purpose)
        self.assertIn("return_to_version_review", merge.failure_routes)

    def test_blueprint_markdown_is_reviewable(self) -> None:
        markdown = render_pipeline_blueprint_markdown()

        self.assertIn("# Pipeline Blueprint", markdown)
        self.assertIn("## Invariants", markdown)
        self.assertIn("### mapping", markdown)
        self.assertIn("### quality_feedback", markdown)
        self.assertIn("### version: Selected Version Review", markdown)
        self.assertIn("evidence_audit.json", markdown)
        self.assertIn("quality_feedback.remap_and_regenerate", markdown)


if __name__ == "__main__":
    unittest.main()
