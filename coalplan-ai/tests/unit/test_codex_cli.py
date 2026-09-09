from __future__ import annotations

import json
import tempfile
import unittest
from subprocess import CompletedProcess
from pathlib import Path
from unittest.mock import patch

from coalplan.infrastructure.llm.codex_cli import CodexCliStructuredLLMClient


class CodexCliStructuredLLMClientTests(unittest.TestCase):
    def test_markdown_completion_returns_last_message_and_records_trace(self) -> None:
        def fake_run(command, **kwargs):
            output = Path(command[command.index("--output-last-message") + 1])
            output.write_text("# 施工方法\n\n依据已知条件组织施工。", encoding="utf-8")
            return CompletedProcess(command, 0, stdout='{"type":"turn.completed","usage":{"input_tokens":10,"output_tokens":8}}\n', stderr="")

        with tempfile.TemporaryDirectory() as temp_dir, patch(
            "coalplan.infrastructure.llm.codex_cli.shutil.which", return_value="codex"
        ), patch("coalplan.infrastructure.llm.codex_cli.subprocess.run", side_effect=fake_run):
            client = CodexCliStructuredLLMClient(trace_dir=Path(temp_dir))
            result = client.complete("只写已知内容")

            self.assertTrue(result.startswith("# 施工方法"))
            trace = json.loads(next(Path(temp_dir).glob("*.json")).read_text(encoding="utf-8"))
            self.assertEqual("只写已知内容", trace["prompt"])
            self.assertEqual(18, trace["usage"]["input_tokens"] + trace["usage"]["output_tokens"])

    def test_separate_clients_do_not_overwrite_trace_files(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir, patch(
            "coalplan.infrastructure.llm.codex_cli.shutil.which", return_value="codex"
        ):
            trace_dir = Path(temp_dir)
            first = CodexCliStructuredLLMClient(trace_dir=trace_dir)
            second = CodexCliStructuredLLMClient(trace_dir=trace_dir)

            first._write_trace("schema", "one", "{}", 1.0, None, {"input_tokens": 1})
            second._write_trace("schema", "two", "{}", 1.0, None, {"input_tokens": 2})

            paths = sorted(trace_dir.glob("*.json"))
            self.assertEqual(2, len(paths))
            token_counts = {
                json.loads(path.read_text(encoding="utf-8"))["usage"]["input_tokens"]
                for path in paths
            }
            self.assertEqual({1, 2}, token_counts)
            prompts = {
                json.loads(path.read_text(encoding="utf-8"))["prompt"]
                for path in paths
            }
            self.assertEqual({"one", "two"}, prompts)


if __name__ == "__main__":
    unittest.main()
