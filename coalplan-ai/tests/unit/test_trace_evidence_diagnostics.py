import json
import tempfile
import unittest
from pathlib import Path

from coalplan.application.trace_evidence_diagnostics import (
    diagnose_trace_evidence_absorption,
    render_trace_evidence_diagnostics_markdown,
)


class TraceEvidenceDiagnosticsTest(unittest.TestCase):
    def test_diagnoses_prompted_omitted_and_unprompted_facts(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            trace_dir = Path(temp_dir)
            _write_trace(
                trace_dir / "0001_markdown.json",
                prompt="期望标题：钻孔施工\n来源包含 DZ/T 0227-2010 和 0.5MPa。",
                response="钻孔施工应按来源组织，但正文只写入 0.5MPa。",
            )
            report = {
                "project_key": "demo",
                "source_facts": {
                    "omitted_examples": [
                        {"fact": "DZ/T 0227-2010", "kind": "standard"},
                        {"fact": "GB50194-2014", "kind": "standard"},
                        {"fact": "0.5MPa", "kind": "parameter"},
                    ]
                },
            }

            result = diagnose_trace_evidence_absorption(quality_report=report, trace_dir=trace_dir)

            by_fact = {item["fact"]: item for item in result["facts"]}
            self.assertEqual("prompted_but_omitted", by_fact["DZ/T 0227-2010"]["status"])
            self.assertEqual("regenerate", by_fact["DZ/T 0227-2010"]["suggested_action"])
            self.assertEqual("not_prompted", by_fact["GB50194-2014"]["status"])
            self.assertEqual("remap_sources", by_fact["GB50194-2014"]["suggested_action"])
            self.assertEqual("absorbed_in_response", by_fact["0.5MPa"]["status"])
            self.assertEqual(1, result["buckets"]["prompted_but_omitted"])
            self.assertEqual(1, result["buckets"]["not_prompted"])

    def test_renders_markdown_report(self) -> None:
        report = {
            "project_key": "demo",
            "trace_dir": "traces",
            "trace_count": 1,
            "omitted_fact_count": 1,
            "buckets": {"prompted_but_omitted": 1},
            "recommended_actions": [
                {
                    "action": "regenerate",
                    "severity": "warning",
                    "reason": "fact reached prompt",
                    "next_steps": ["carry fact into正文"],
                }
            ],
            "facts": [
                {
                    "fact": "GB50194-2014",
                    "status": "prompted_but_omitted",
                    "prompt_hit_count": 1,
                    "response_hit_count": 0,
                    "suggested_action": "regenerate",
                    "sample_traces": [],
                }
            ],
        }

        markdown = render_trace_evidence_diagnostics_markdown(report)

        self.assertIn("# Trace Evidence Diagnostics: demo", markdown)
        self.assertIn("## Recommended Actions", markdown)
        self.assertIn("GB50194-2014", markdown)


def _write_trace(path: Path, *, prompt: str, response: str) -> None:
    path.write_text(
        json.dumps(
            {
                "kind": "markdown",
                "schema_name": None,
                "prompt": prompt,
                "response": response,
                "error": None,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


if __name__ == "__main__":
    unittest.main()
