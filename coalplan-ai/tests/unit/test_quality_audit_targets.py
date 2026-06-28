import unittest

from coalplan.application.quality_audit_targets import (
    build_quality_audit_revision_targets,
    render_quality_audit_revision_targets,
)


class QualityAuditTargetsTest(unittest.TestCase):
    def test_missing_human_heading_creates_outline_target_when_no_node_matches(self) -> None:
        report = {
            "headings": {"missing_human_heading_examples": ["Temporary power layout"]},
            "source_facts": {"omitted_examples": []},
            "common_topics": {},
        }

        plan = build_quality_audit_revision_targets(
            project_id="project_demo",
            report=report,
            outline_nodes=[{"node_id": "node_overview", "title": "Project overview"}],
        )

        self.assertEqual("warning", plan.status)
        self.assertEqual("outline", plan.targets[0].target_type)
        self.assertEqual("propose_outline_repair", plan.targets[0].action)
        self.assertTrue(plan.targets[0].requires_user_confirmation)
        self.assertIn("Quality Audit Revision Targets", render_quality_audit_revision_targets(plan))

    def test_omitted_fact_routes_to_matching_content_node(self) -> None:
        report = {
            "headings": {},
            "source_facts": {
                "omitted_examples": [
                    {
                        "fact": "0.5MPa",
                        "kind": "parameter",
                        "context": "Grouting pressure control uses 0.5MPa and staged injection.",
                    }
                ]
            },
            "common_topics": {},
        }
        outline_nodes = [
            {
                "node_id": "node_grouting",
                "title": "Grouting construction",
                "source_rules": ["grouting pressure injection"],
            }
        ]
        workspaces = {
            "node_grouting": {
                "selected_version_id": "version_1",
                "versions": [
                    {
                        "id": "version_1",
                        "markdown": "Grouting construction method.",
                        "content_tree": {
                            "nodes": [
                                {
                                    "id": "content_pressure",
                                    "title": "Grouting pressure control",
                                    "body": "Explain staged injection and pressure control.",
                                    "source_links": [{"matched_terms": ["grouting", "pressure", "injection"]}],
                                    "children": [],
                                }
                            ]
                        },
                    }
                ],
            }
        }

        plan = build_quality_audit_revision_targets(
            project_id="project_demo",
            report=report,
            outline_nodes=outline_nodes,
            workspaces=workspaces,
        )

        self.assertEqual("content_node", plan.targets[0].target_type)
        self.assertEqual("rewrite_subsection", plan.targets[0].action)
        self.assertEqual("node_grouting", plan.targets[0].node_id)
        self.assertEqual("version_1", plan.targets[0].version_id)
        self.assertEqual("content_pressure", plan.targets[0].content_node_id)
        self.assertTrue(plan.targets[0].requires_llm)


if __name__ == "__main__":
    unittest.main()
