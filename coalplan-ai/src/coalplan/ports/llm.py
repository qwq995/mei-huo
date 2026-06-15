from __future__ import annotations

from typing import Any
from typing import Protocol


class LLMClient(Protocol):
    def complete(self, prompt: str) -> str:
        """Return a markdown completion for a prompt."""


class StructuredLLMClient(Protocol):
    def complete_json(self, prompt: str, *, schema_name: str) -> dict[str, Any]:
        """Return JSON data that should satisfy a known schema contract."""
