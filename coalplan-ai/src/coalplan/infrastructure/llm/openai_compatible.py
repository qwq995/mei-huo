from __future__ import annotations

import json
import re
import time
import urllib.request
import urllib.error
from datetime import datetime
from pathlib import Path
from typing import Any


class OpenAICompatibleLLMClient:
    """Minimal OpenAI-compatible chat completions client for private deployments."""

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        model: str,
        timeout: int = 120,
        reasoning_split: bool = False,
        disable_thinking: bool = False,
        trace_dir: Path | str | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.timeout = timeout
        self.reasoning_split = reasoning_split
        self.disable_thinking = disable_thinking
        self.trace_dir = Path(trace_dir) if trace_dir else None
        self._trace_counter = 0

    def complete(self, prompt: str) -> str:
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [
                {
                    "role": "system",
                    "content": "你是施工组织设计生成助手。只能依据用户提供的来源材料写作，只输出严格 Markdown，不要解释。",
                },
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.2,
        }
        if self.reasoning_split:
            payload["reasoning_split"] = True
        if self.disable_thinking:
            payload["thinking"] = {"type": "disabled"}
        started = time.perf_counter()
        try:
            parsed = self._post_chat_completions(payload)
            content = _strip_reasoning_tags(parsed["choices"][0]["message"]["content"]).strip()
        except Exception as exc:
            self._write_trace(
                kind="markdown",
                prompt=prompt,
                response=None,
                parsed_json=None,
                usage=None,
                elapsed_seconds=time.perf_counter() - started,
                error=str(exc),
            )
            raise
        self._write_trace(
            kind="markdown",
            prompt=prompt,
            response=content,
            parsed_json=None,
            usage=parsed.get("usage"),
            elapsed_seconds=time.perf_counter() - started,
            error=None,
        )
        return content

    def complete_json(self, prompt: str, *, schema_name: str) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [
                {
                    "role": "system",
                    "content": f"你是施工组织设计结构化信息抽取助手。只输出符合 {schema_name} 的 JSON，不要 Markdown，不要解释。",
                },
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.0,
            "response_format": {"type": "json_object"},
        }
        if self.reasoning_split:
            payload["reasoning_split"] = True
        if self.disable_thinking:
            payload["thinking"] = {"type": "disabled"}
        started = time.perf_counter()
        try:
            parsed = self._post_chat_completions(payload)
            content = parsed["choices"][0]["message"]["content"]
            parsed_json = _parse_json_object(content)
        except Exception as exc:
            self._write_trace(
                kind="json",
                schema_name=schema_name,
                prompt=prompt,
                response=None,
                parsed_json=None,
                usage=None,
                elapsed_seconds=time.perf_counter() - started,
                error=str(exc),
            )
            raise
        self._write_trace(
            kind="json",
            schema_name=schema_name,
            prompt=prompt,
            response=_strip_reasoning_tags(content).strip(),
            parsed_json=parsed_json,
            usage=parsed.get("usage"),
            elapsed_seconds=time.perf_counter() - started,
            error=None,
        )
        return parsed_json

    def _post_chat_completions(self, payload: dict[str, Any]) -> dict[str, Any]:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(
            f"{self.base_url}/chat/completions",
            data=data,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                raw = response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"HTTP {exc.code}: {body}") from exc
        return json.loads(raw)

    def _write_trace(
        self,
        *,
        kind: str,
        prompt: str,
        response: str | None,
        parsed_json: dict[str, Any] | None,
        usage: dict[str, Any] | None,
        elapsed_seconds: float,
        error: str | None,
        schema_name: str | None = None,
    ) -> None:
        if self.trace_dir is None:
            return
        self.trace_dir.mkdir(parents=True, exist_ok=True)
        self._trace_counter += 1
        timestamp = datetime.now().isoformat(timespec="milliseconds")
        safe_schema = f"_{schema_name}" if schema_name else ""
        path = self.trace_dir / f"{self._trace_counter:04d}_{kind}{safe_schema}.json"
        path.write_text(
            json.dumps(
                {
                    "index": self._trace_counter,
                    "timestamp": timestamp,
                    "kind": kind,
                    "schema_name": schema_name,
                    "provider_base_url": self.base_url,
                    "model": self.model,
                    "elapsed_seconds": round(elapsed_seconds, 3),
                    "prompt": prompt,
                    "response": response,
                    "parsed_json": parsed_json,
                    "usage": usage,
                    "error": error,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )


def _parse_json_object(content: str) -> dict[str, Any]:
    text = _strip_reasoning_tags(content).strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    if not text.startswith("{"):
        match = re.search(r"\{[\s\S]*\}", text)
        if match:
            text = match.group(0)
    data = json.loads(text)
    if not isinstance(data, dict):
        raise ValueError("Structured LLM output must be a JSON object.")
    return data


def _strip_reasoning_tags(content: str) -> str:
    return re.sub(r"<think>[\s\S]*?</think>", "", content, flags=re.I).strip()
