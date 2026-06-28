from __future__ import annotations

import unittest

from coalplan.application.map_chapter_sources import build_source_mapping_prompt
from coalplan.application.quality_feedback import build_quality_feedback_plan, render_quality_feedback_mapping_context
from coalplan.application.run_generation_pipeline import _mapping_control_context
from coalplan.domain.documents import SourceTocItem
from coalplan.domain.generation_control import ChapterGenerationPolicy
from coalplan.domain.profile import ProjectProfile
from coalplan.domain.templates import TemplateNode


class SourceMappingPromptTest(unittest.TestCase):
    def test_source_mapping_prompt_includes_mapping_control_context(self) -> None:
        prompt = build_source_mapping_prompt(
            profile=ProjectProfile(project_name="demo"),
            toc_items=[SourceTocItem(section_id="sec_111111111111", title_path=["bid", "grouting"], level=2, char_count=100)],
            node=TemplateNode(id="node_grout", title="grouting", level=2, source_rules=["grouting source"]),
            mapping_context="\n".join(
                [
                    "## Mapping Policy Requirements",
                    "- writing_pattern_key: craft",
                    "- pattern_required_source_facts:",
                    "  - 控制参数",
                    "## Revision Control Requirements",
                    "- action: remap_sources",
                ]
            ),
        )

        self.assertIn("Mapping Control Context", prompt)
        self.assertIn("writing_pattern_key: craft", prompt)
        self.assertIn("控制参数", prompt)
        self.assertIn("remap_sources", prompt)
        self.assertIn("sec_111111111111", prompt)

    def test_mapping_control_context_includes_pattern_prompt_cards(self) -> None:
        policy = ChapterGenerationPolicy(
            node_id="node_grout",
            title="grouting",
            writing_pattern_key="craft",
            pattern_prompt_cards=[
                {
                    "pattern_key": "craft",
                    "source_mapping_requirements": ["Map process, pressure, flow, inspection, and acceptance evidence."],
                    "human_only_items": ["approved final pressure"],
                }
            ],
        )

        context = _mapping_control_context(policy)

        self.assertIn("pattern_prompt_cards", context)
        self.assertIn("source_mapping_requirements", context)
        self.assertIn("Map process, pressure, flow, inspection, and acceptance evidence.", context)
        self.assertIn("approved final pressure", context)

    def test_source_mapping_prompt_can_receive_quality_feedback_trace_hints(self) -> None:
        feedback = build_quality_feedback_plan(
            {
                "project_key": "demo",
                "word_counts": {"generated_vs_human_ratio": 0.8},
                "headings": {"human_heading_coverage_ratio": 0.8},
                "source_facts": {"absorption_ratio": 0.8, "candidate_count": 20},
                "common_topics": {},
                "recommendations": [],
            },
            trace_diagnostics={
                "trace_count": 1,
                "buckets": {"not_prompted": 1, "prompted_but_omitted": 0},
                "facts": [
                    {
                        "fact": "GB50194-2014 temporary-power basis",
                        "status": "not_prompted",
                        "suggested_action": "remap_sources",
                    }
                ],
            },
        )

        prompt = build_source_mapping_prompt(
            profile=ProjectProfile(project_name="demo"),
            toc_items=[
                SourceTocItem(
                    section_id="sec_222222222222",
                    title_path=["bid", "temporary power"],
                    level=2,
                    char_count=100,
                )
            ],
            node=TemplateNode(id="node_power", title="temporary power", level=2, source_rules=["power source"]),
            mapping_context=render_quality_feedback_mapping_context(feedback),
        )

        self.assertIn("Quality Feedback Mapping Requirements", prompt)
        self.assertIn("GB50194-2014", prompt)
        self.assertIn("not_prompted", prompt)
        self.assertIn("missing_evidence", prompt)


if __name__ == "__main__":
    unittest.main()
