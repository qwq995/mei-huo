from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from coalplan.infrastructure.llm.openai_compatible import OpenAICompatibleLLMClient
from coalplan.main import build_pipeline
from coalplan.settings import Settings


class ProviderSettingsTest(unittest.TestCase):
    def test_builds_deepseek_provider(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            pipeline = build_pipeline(
                Settings(
                    storage_dir=Path(temp_dir),
                    llm_provider="deepseek",
                    deepseek_api_key="test-key",
                    deepseek_model="deepseek-v4-pro",
                )
            )

            self.assertIsInstance(pipeline.llm, OpenAICompatibleLLMClient)
            self.assertEqual("https://api.deepseek.com", pipeline.llm.base_url)
            self.assertEqual("deepseek-v4-pro", pipeline.llm.model)


if __name__ == "__main__":
    unittest.main()
