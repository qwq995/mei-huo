from __future__ import annotations

import hashlib
import json
from typing import Any


def dependency_fingerprint(payload: dict[str, Any]) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


class CachedLLMClient:
    """Persistent prompt cache for successful model responses."""

    def __init__(self, client, artifacts, project_id: str, *, namespace: str) -> None:
        self.client = client
        self.artifacts = artifacts
        self.project_id = project_id
        self.namespace = namespace

    def complete(self, prompt: str) -> str:
        key = hashlib.sha256(f"{self.namespace}\n{prompt}".encode("utf-8")).hexdigest()
        relative = f"control/llm-cache/{self.namespace}/{key}.txt"
        try:
            return self.artifacts.read_text(str(self.artifacts.root / self.project_id / relative))
        except (FileNotFoundError, KeyError, OSError):
            value = self.client.complete(prompt)
            self.artifacts.write_text(self.project_id, relative, value)
            return value

    def complete_json(self, prompt: str, *, schema_name: str) -> dict[str, Any]:
        key = hashlib.sha256(f"{self.namespace}\n{schema_name}\n{prompt}".encode("utf-8")).hexdigest()
        relative = f"control/llm-cache/{self.namespace}/{key}.json"
        try:
            return json.loads(self.artifacts.read_text(str(self.artifacts.root / self.project_id / relative)))
        except (FileNotFoundError, KeyError, OSError, json.JSONDecodeError):
            value = self.client.complete_json(prompt, schema_name=schema_name)
            self.artifacts.write_text(self.project_id, relative, json.dumps(value, ensure_ascii=False, indent=2))
            return value
