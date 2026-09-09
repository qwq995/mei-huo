from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any


class CodexCliStructuredLLMClient:
    """Structured extraction through the locally authenticated Codex CLI.

    This adapter is intended for controlled corpus-building runs. Runtime web
    requests should continue to use the configured API provider.
    """

    def __init__(
        self,
        *,
        model: str = "gpt-5.6-sol",
        schema_dir: Path | None = None,
        workdir: Path | None = None,
        trace_dir: Path | None = None,
        timeout: int = 900,
    ) -> None:
        executable = shutil.which("codex")
        if not executable:
            raise RuntimeError("Codex CLI is not available on PATH.")
        self.executable = executable
        self.model = model
        self.schema_dir = schema_dir or Path(__file__).resolve().parents[4] / "config" / "reference_library"
        self.workdir = (workdir or Path.cwd()).resolve()
        self.trace_dir = trace_dir
        self.timeout = timeout
        self._counter = 0
        self._lock = threading.Lock()
        self._run_id = f"{datetime.now().strftime('%Y%m%dT%H%M%S%f')}_{uuid.uuid4().hex[:8]}"

    def complete(self, prompt: str) -> str:
        with tempfile.TemporaryDirectory(prefix="coalplan-codex-") as temp:
            output_path = Path(temp) / "result.md"
            command = [
                self.executable, "exec", "--ephemeral", "--sandbox", "read-only",
                "--color", "never", "--json", "--model", self.model,
                "--cd", str(self.workdir), "--output-last-message", str(output_path), "-",
            ]
            started = time.perf_counter()
            try:
                completed = subprocess.run(
                    command,
                    input=(
                        "你是施工组织设计生成助手。只能依据提示词内提供的当前项目证据、"
                        "已确认项目记忆和参数化参考原子写作。只输出 Markdown 正文，不要解释，不得虚构参数。\n\n"
                        + prompt
                    ),
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    cwd=self.workdir,
                    capture_output=True,
                    timeout=self.timeout,
                    check=False,
                )
            except subprocess.TimeoutExpired as exc:
                elapsed = time.perf_counter() - started
                error = f"Codex CLI timed out after {self.timeout} seconds"
                self._write_trace("markdown", prompt, None, elapsed, error, None)
                raise RuntimeError(error) from exc
            elapsed = time.perf_counter() - started
            usage = _extract_usage(completed.stdout)
            if completed.returncode != 0 or not output_path.exists():
                error = (completed.stderr or completed.stdout or "Codex CLI returned no output")[-2000:]
                self._write_trace("markdown", prompt, None, elapsed, error, usage)
                raise RuntimeError(f"Codex CLI failed ({completed.returncode}): {error}")
            response = output_path.read_text(encoding="utf-8").strip()
            self._write_trace("markdown", prompt, response, elapsed, None, usage)
            return response

    def complete_json(self, prompt: str, *, schema_name: str) -> dict[str, Any]:
        schema_path = self.schema_dir / f"{schema_name}.output.schema.json"
        if not schema_path.exists():
            raise FileNotFoundError(f"No Codex output schema for {schema_name}: {schema_path}")
        with tempfile.TemporaryDirectory(prefix="coalplan-codex-") as temp:
            output_path = Path(temp) / "result.json"
            command = [
                self.executable, "exec", "--ephemeral", "--sandbox", "read-only",
                "--color", "never", "--json", "--model", self.model,
                "--cd", str(self.workdir), "--output-schema", str(schema_path),
                "--output-last-message", str(output_path), "-",
            ]
            started = time.perf_counter()
            try:
                completed = subprocess.run(
                    command,
                    input=(
                        "只执行给定的结构化分类或抽取任务。不要调用工具，不要修改文件，不要解释；"
                        "最终仅返回符合输出 schema 的 JSON。\n\n" + prompt
                    ),
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    cwd=self.workdir,
                    capture_output=True,
                    timeout=self.timeout,
                    check=False,
                )
            except subprocess.TimeoutExpired as exc:
                elapsed = time.perf_counter() - started
                error = f"Codex CLI timed out after {self.timeout} seconds"
                self._write_trace(schema_name, prompt, None, elapsed, error, None)
                raise RuntimeError(error) from exc
            elapsed = time.perf_counter() - started
            usage = _extract_usage(completed.stdout)
            if completed.returncode != 0 or not output_path.exists():
                error = (completed.stderr or completed.stdout or "Codex CLI returned no output")[-2000:]
                self._write_trace(schema_name, prompt, None, elapsed, error, usage)
                raise RuntimeError(f"Codex CLI failed ({completed.returncode}): {error}")
            raw = output_path.read_text(encoding="utf-8")
            try:
                payload = json.loads(raw)
            except json.JSONDecodeError as exc:
                self._write_trace(schema_name, prompt, raw, elapsed, str(exc), usage)
                raise
            self._write_trace(schema_name, prompt, raw, elapsed, None, usage)
            return payload

    def _write_trace(
        self,
        schema_name: str,
        prompt: str,
        response: str | None,
        elapsed_seconds: float,
        error: str | None,
        usage: dict[str, int] | None,
    ) -> None:
        if self.trace_dir is None:
            return
        self.trace_dir.mkdir(parents=True, exist_ok=True)
        with self._lock:
            self._counter += 1
            index = self._counter
        path = self.trace_dir / f"{self._run_id}_{index:05d}_{schema_name}.json"
        path.write_text(json.dumps({
            "index": index,
            "timestamp": datetime.now().isoformat(timespec="milliseconds"),
            "provider": "codex-cli",
            "model": self.model,
            "schema_name": schema_name,
            "elapsed_seconds": round(elapsed_seconds, 3),
            "prompt_character_count": len(prompt),
            "prompt": prompt,
            "response_character_count": len(response or ""),
            "usage": usage,
            "response": response,
            "error": error,
        }, ensure_ascii=False, indent=2), encoding="utf-8")


def _extract_usage(stdout: str) -> dict[str, int] | None:
    for line in reversed(stdout.splitlines()):
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if event.get("type") == "turn.completed" and isinstance(event.get("usage"), dict):
            return {str(key): int(value) for key, value in event["usage"].items() if isinstance(value, (int, float))}
    return None
