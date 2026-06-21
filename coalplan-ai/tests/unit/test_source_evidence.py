from __future__ import annotations

import unittest

from coalplan.application.source_evidence import build_source_evidence
from coalplan.domain.documents import MarkdownSection
from coalplan.domain.outline import SourceMappingMatch
from coalplan.domain.templates import TemplateNode


class SourceEvidenceTest(unittest.TestCase):
    def test_build_source_evidence_selects_relevant_paragraph_with_line_range(self) -> None:
        node = TemplateNode(
            id="node_injection",
            title="注水工程施工",
            level=3,
            source_rules=["依据投标文件中的注水工程、供水条件和施工参数编写"],
            auto_fill=["归纳注水施工流程和质量控制要点"],
            manual_fill=["注水压力、流量和现场复核记录需人工确认"],
        )
        section = MarkdownSection(
            id="sec_injection",
            title_path=["施工方案", "注水工程施工"],
            level=2,
            content="\n".join(
                [
                    "本工程先进行火区钻孔复核，确认裂隙发育情况。",
                    "",
                    "注水施工采用分区、分孔、分阶段实施，施工中应控制注水压力和流量，并做好现场记录。",
                    "",
                    "| 项目 | 要求 |",
                    "| --- | --- |",
                    "| 注水 | 连续记录压力、流量、时间 |",
                ]
            ),
            source_file="bid.md",
            start_line=20,
            end_line=28,
        )
        match = SourceMappingMatch(section_id="sec_injection", usage="method", reason="与注水施工方法相关", confidence=0.85)

        evidence = build_source_evidence(node=node, matches=[match], sections=[section])

        self.assertGreaterEqual(len(evidence), 1)
        joined = "\n".join(item.quote for item in evidence)
        self.assertIn("注水施工采用分区", joined)
        self.assertTrue(all(item.section_id == "sec_injection" for item in evidence))
        self.assertTrue(any(item.start_line is not None and item.end_line is not None for item in evidence))
        self.assertTrue(any(any("注水" in term for term in item.matched_terms) for item in evidence))


if __name__ == "__main__":
    unittest.main()
