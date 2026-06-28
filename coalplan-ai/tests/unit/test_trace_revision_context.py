from __future__ import annotations

import unittest

from coalplan.application.trace_revision_context import (
    build_trace_revision_context,
    build_trace_revision_context_from_labels,
    parse_trace_fact_label,
    render_trace_generation_context,
    render_trace_mapping_context,
    strip_trace_fact_label,
)


class TraceRevisionContextTest(unittest.TestCase):
    def test_trace_diagnostics_split_mapping_and_generation_actions(self) -> None:
        diagnostics = {
            "project_key": "project_3",
            "trace_count": 12,
            "facts": [
                {
                    "fact": "5-8℃",
                    "status": "not_prompted",
                    "suggested_action": "remap_sources",
                    "kind": "parameter",
                },
                {
                    "fact": "GB50194-2014",
                    "status": "prompted_but_omitted",
                    "suggested_action": "regenerate",
                    "kind": "standard",
                },
                {
                    "fact": "200～300mm",
                    "status": "absorbed_in_response",
                    "suggested_action": "accept",
                },
            ],
        }

        context = build_trace_revision_context(diagnostics)

        self.assertEqual("project_3", context.project_key)
        self.assertEqual(["5-8℃"], [fact.fact for fact in context.remap_facts])
        self.assertEqual(["GB50194-2014"], [fact.fact for fact in context.required_generation_facts])
        self.assertEqual(["200～300mm"], [fact.fact for fact in context.accepted_facts])
        self.assertIn("5-8℃ [not_prompted -> remap_sources]", render_trace_mapping_context(context))
        self.assertIn("GB50194-2014 [prompted_but_omitted -> regenerate]", render_trace_generation_context(context))

    def test_not_prompted_fact_becomes_generation_required_after_source_support(self) -> None:
        context = build_trace_revision_context(
            {
                "facts": [
                    {
                        "fact": "108mm",
                        "status": "not_prompted",
                        "suggested_action": "remap_sources",
                    }
                ]
            },
            source_text="钻孔孔径采用108mm，施工中按设计要求控制。",
        )

        self.assertEqual(["108mm"], [fact.fact for fact in context.remap_facts])
        self.assertEqual(["108mm"], [fact.fact for fact in context.required_generation_facts])

    def test_trace_labels_round_trip(self) -> None:
        label = "GB8978-1996 [prompted_but_omitted -> regenerate]"

        self.assertEqual(("GB8978-1996", "prompted_but_omitted", "regenerate"), parse_trace_fact_label(label))
        self.assertEqual("GB8978-1996", strip_trace_fact_label(label))

        context = build_trace_revision_context_from_labels([label])
        self.assertEqual(["GB8978-1996"], [fact.fact for fact in context.required_generation_facts])


if __name__ == "__main__":
    unittest.main()
