from __future__ import annotations

import unittest

from coalplan.infrastructure.llm.openai_compatible import _parse_json_object


class OpenAICompatibleLLMTest(unittest.TestCase):
    def test_parse_json_object_strips_reasoning_tags(self) -> None:
        content = '<think>分析过程</think>\n{"project_name":"煤火治理","source_section_ids":[]}'

        data = _parse_json_object(content)

        self.assertEqual("煤火治理", data["project_name"])


if __name__ == "__main__":
    unittest.main()
