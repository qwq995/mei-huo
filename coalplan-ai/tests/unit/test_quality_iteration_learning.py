import unittest

from coalplan.application.quality_iteration_learning import (
    build_quality_iteration_learning_report,
    render_quality_iteration_learning_report,
)


class QualityIterationLearningTest(unittest.TestCase):
    def test_builds_pattern_learning_suggestions_from_quality_iteration(self) -> None:
        payload = {
            "project_id": "project_demo",
            "status": "completed_with_remaining_targets",
            "round_count": 1,
            "rounds": [
                {
                    "audit": {
                        "report": {
                            "source_facts": {
                                "omitted_examples": [
                                    {
                                        "fact": "0.5MPa",
                                        "kind": "parameter",
                                        "context": "grouting construction pressure parameter",
                                    }
                                ]
                            },
                            "headings": {
                                "missing_human_heading_examples": [
                                    "Quality inspection and acceptance records"
                                ]
                            },
                        },
                        "revision_targets": {
                            "targets": [
                                {
                                    "target_type": "content_node",
                                    "action": "rewrite_subsection",
                                    "title": "Grouting pressure control",
                                    "reason": "omitted source fact",
                                    "evidence": ["0.5MPa"],
                                }
                            ]
                        },
                    },
                    "execution": {
                        "source_plan": {
                            "targets": [
                                {
                                    "target_type": "chapter",
                                    "action": "regenerate",
                                    "title": "Grouting construction",
                                    "reason": "generic craft text",
                                }
                            ]
                        }
                    },
                }
            ],
            "final_audit": {
                "report": {
                    "source_facts": {"omitted_examples": []},
                    "headings": {"missing_human_heading_examples": []},
                },
                "revision_targets": {"targets": []},
            },
        }

        report = build_quality_iteration_learning_report(project_id="project_demo", quality_iteration=payload)

        self.assertEqual("warning", report.status)
        types = {item.suggestion_type for item in report.suggestions}
        self.assertIn("strengthen_required_source_facts", types)
        self.assertIn("add_outline_guidance", types)
        self.assertIn("add_revision_signal", types)
        markdown = render_quality_iteration_learning_report(report)
        self.assertIn("Quality Iteration Learning Report", markdown)
        self.assertIn("suggestion", markdown.lower())

    def test_learns_from_content_revision_targets(self) -> None:
        payload = {
            "project_id": "project_demo",
            "status": "completed_with_remaining_targets",
            "round_count": 0,
            "content_revision_targets": [
                {
                    "node_id": "node_grouting",
                    "version_id": "ver_1",
                    "content_node_id": "gcn_pressure",
                    "target_type": "content_node",
                    "title": "Grouting pressure and flow controls",
                    "action": "remap_sources",
                    "source_status": "missing",
                    "reason": "The subsection is factual but has no source section or evidence link.",
                    "source_section_ids": [],
                    "evidence_ids": [],
                    "next_steps": ["Re-run source mapping with subsection title and body."],
                },
                {
                    "node_id": "node_grouting",
                    "version_id": "ver_1",
                    "content_node_id": "gcn_dense",
                    "target_type": "content_node",
                    "title": "Grouting construction method, resources, quality, safety, and acceptance",
                    "action": "split_subsection",
                    "source_status": "covered",
                    "reason": "The subsection is dense and mixes process, resources, quality, safety, environment, and acceptance.",
                    "source_section_ids": ["sec_123"],
                    "evidence_ids": ["ev_456"],
                    "next_steps": ["Create child nodes and regenerate one by one."],
                },
            ],
            "rounds": [],
            "final_audit": {
                "report": {
                    "source_facts": {"omitted_examples": []},
                    "headings": {"missing_human_heading_examples": []},
                },
                "revision_targets": {"targets": []},
            },
        }

        report = build_quality_iteration_learning_report(project_id="project_demo", quality_iteration=payload)

        self.assertEqual("warning", report.status)
        self.assertEqual(2, report.metrics["content_revision_target_count"])
        types = {item.suggestion_type for item in report.suggestions}
        self.assertIn("add_revision_signal", types)
        self.assertIn("increase_detail_or_split", types)
        evidence = "\n".join(item for suggestion in report.suggestions for item in suggestion.evidence)
        self.assertIn("content_node:remap_sources:Grouting pressure and flow controls", evidence)
        self.assertIn("content_node:split_subsection:Grouting construction method", evidence)

    def test_learns_required_source_facts_from_evidence_targeted_content_rewrite(self) -> None:
        payload = {
            "project_id": "project_demo",
            "status": "completed_with_remaining_targets",
            "round_count": 0,
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
                        "Insert or explicitly route omitted required source fact `ev_water:fact_1` from evidence `ev_water` / section `sec_water`: crack water injection uses duckbill nozzle and pressure 0.2-0.3MPa."
                    ],
                }
            ],
            "rounds": [],
            "final_audit": {
                "report": {
                    "source_facts": {"omitted_examples": []},
                    "headings": {"missing_human_heading_examples": []},
                },
                "revision_targets": {"targets": []},
            },
        }

        report = build_quality_iteration_learning_report(project_id="project_demo", quality_iteration=payload)

        self.assertEqual("warning", report.status)
        self.assertEqual(1, report.metrics["evidence_targeted_content_revision_target_count"])
        types = {item.suggestion_type for item in report.suggestions}
        self.assertIn("strengthen_required_source_facts", types)
        self.assertIn("add_revision_signal", types)
        evidence = "\n".join(item for suggestion in report.suggestions for item in suggestion.evidence)
        self.assertIn("duckbill nozzle", evidence)
        self.assertIn("evidence_targeted", evidence)
        signal = next(item for item in report.suggestions if item.suggestion_type == "add_revision_signal")
        self.assertTrue(any("evidence-targeted subsection rewrite" in item for item in signal.suggested_text))

    def test_learns_from_generation_metadata_targets(self) -> None:
        payload = {
            "project_id": "project_demo",
            "status": "completed_with_remaining_targets",
            "round_count": 0,
            "generation_metadata_targets": [
                {
                    "node_id": "node_craft",
                    "version_id": "ver_2",
                    "title": "Water injection construction",
                    "action": "expand_subsections",
                    "reason": "Pattern craft organization coverage is low.",
                    "next_actions": ["Split this dense chapter into source-derived subsections before regenerating."],
                    "pattern_audits": [
                        {
                            "pattern_key": "craft",
                            "suggested_action": "expand_subsections",
                            "coverage_ratio": 0.375,
                            "missing_points": [
                                "process flow and construction sequence",
                                "quality inspection, test, acceptance, and records",
                                "safety, environment, and civilized construction controls",
                            ],
                            "covered_points": ["construction object and method"],
                        }
                    ],
                }
            ],
            "rounds": [],
            "final_audit": {
                "report": {
                    "source_facts": {"omitted_examples": []},
                    "headings": {"missing_human_heading_examples": []},
                },
                "revision_targets": {"targets": []},
            },
        }

        report = build_quality_iteration_learning_report(project_id="project_demo", quality_iteration=payload)

        self.assertEqual("warning", report.status)
        self.assertEqual(1, report.metrics["generation_metadata_target_count"])
        types = {item.suggestion_type for item in report.suggestions}
        self.assertIn("add_outline_guidance", types)
        self.assertIn("increase_detail_or_split", types)
        guidance = next(item for item in report.suggestions if item.suggestion_type == "add_outline_guidance")
        self.assertEqual("craft", guidance.pattern_key)
        self.assertIn("process flow and construction sequence", guidance.evidence)


if __name__ == "__main__":
    unittest.main()
