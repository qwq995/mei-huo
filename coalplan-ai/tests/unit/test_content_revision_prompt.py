from __future__ import annotations

import unittest

from coalplan.application.run_generation_pipeline import (
    _build_content_revision_prompt,
    _content_revision_required_facts,
)
from coalplan.domain.documents import MarkdownSection
from coalplan.domain.generation import Project
from coalplan.domain.profile import ProjectProfile


class ContentRevisionPromptTest(unittest.TestCase):
    def test_evidence_targeted_revision_facts_are_promoted_to_prompt_section(self) -> None:
        item = {
            "action": "rewrite_subsection",
            "reason": "omitted_required_source_facts must be absorbed",
            "next_steps": [
                (
                    "Insert or explicitly route omitted required source fact `ev_water:fact_1` "
                    "from evidence `ev_water` / section `sec_water`: "
                    "Crack water injection uses duckbill nozzle and pressure 0.2-0.3MPa."
                )
            ],
        }
        facts = _content_revision_required_facts(item)

        prompt = _build_content_revision_prompt(
            project=Project(
                name="demo",
                project_profile=ProjectProfile(project_name="coal fire demo", project_type="coal_fire"),
            ),
            node_id="node_water",
            version={"id": "ver_1", "title": "Water injection"},
            content_node={
                "id": "content_1",
                "title": "Crack water injection",
                "level": 3,
                "title_path": ["Generated body", "Crack water injection"],
                "source_status": "covered",
                "markdown": "### Crack water injection\nGeneric injection text.",
            },
            revision_item=item,
            action="rewrite_subsection",
            source_sections=[
                MarkdownSection(
                    id="sec_water",
                    title_path=["Bid", "Water injection"],
                    level=2,
                    content="Crack water injection uses duckbill nozzle and pressure 0.2-0.3MPa.",
                    source_file="bid.md",
                )
            ],
            user_context="",
            required_facts=facts,
        )

        self.assertEqual(1, len(facts))
        self.assertIn("content_revision_required_facts", prompt)
        self.assertIn("fact_id: ev_water:fact_1", prompt)
        self.assertIn("evidence_id: ev_water", prompt)
        self.assertIn("section_id: sec_water", prompt)
        self.assertIn("duckbill nozzle", prompt)
        self.assertIn("selected_source_sections", prompt)


if __name__ == "__main__":
    unittest.main()
