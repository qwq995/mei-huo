from __future__ import annotations

import json
import time
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any


API_BASE = "http://127.0.0.1:8029"
SOURCE_ROOT = Path(r"D:\Task_md\规范清单-2")
OUTPUT_ROOT = Path(".coalplan-data/standard-constraint-real-api-20260814")
TRACE_DIR_NAME = "traces_run2"
STANDARD_CODES = ("DL_T 5371-2017", "SL 734-2016", "DL_T 5148-2021")


def main() -> int:
    output_dir = OUTPUT_ROOT.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    source_paths = [_find_standard(code) for code in STANDARD_CODES]
    files = [
        {
            "file_name": path.name,
            "content": path.read_text(encoding="utf-8-sig", errors="replace"),
        }
        for path in source_paths
    ]

    trace_dir = output_dir / TRACE_DIR_NAME
    existing_trace_names = {path.name for path in trace_dir.glob("*.json")}
    started = time.perf_counter()
    imported = _request_json(
        "POST",
        "/standards/import-batch",
        {"files": files, "max_batches_per_document": 1},
        timeout=900,
    )
    constraints: dict[str, list[dict[str, Any]]] = {}
    for item in imported.get("results", []):
        document = item.get("document") or {}
        document_id = document.get("id")
        if document_id:
            constraints[document_id] = _request_json(
                "GET", f"/standards/documents/{document_id}/constraints", timeout=60
            )
    elapsed = round(time.perf_counter() - started, 3)
    all_traces = _load_traces(trace_dir)
    traces = [(path, trace) for path, trace in all_traces if path.name not in existing_trace_names]
    usage = _summarize_usage(traces)
    cumulative_traces = [*_load_traces(output_dir / "traces"), *all_traces]
    cumulative_usage = _summarize_usage(cumulative_traces)

    payload = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "api_base": API_BASE,
        "source_paths": [str(path) for path in source_paths],
        "request_scope": {
            "document_count": len(files),
            "max_batches_per_document": 1,
        },
        "elapsed_seconds": elapsed,
        "api_response": imported,
        "constraints": constraints,
        "trace_summary": usage,
        "cumulative_trace_summary": cumulative_usage,
        "trace_files": [str(path) for path, _ in traces],
    }
    (output_dir / "api_validation.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (output_dir / "constraints.json").write_text(
        json.dumps(constraints, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (output_dir / "validation_report.md").write_text(
        _render_report(payload), encoding="utf-8"
    )
    print(json.dumps({
        "output_dir": str(output_dir),
        "elapsed_seconds": elapsed,
        "completed_count": imported.get("completed_count"),
        "failed_count": imported.get("failed_count"),
        "constraint_count": sum(len(items) for items in constraints.values()),
        "trace_summary": usage,
        "cumulative_trace_summary": cumulative_usage,
    }, ensure_ascii=False, indent=2))
    return 0


def _find_standard(code: str) -> Path:
    matches = [path for path in SOURCE_ROOT.rglob("*.md") if path.name.startswith(code)]
    if not matches:
        raise FileNotFoundError(code)
    return matches[0]


def _request_json(method: str, path: str, payload: dict | None = None, *, timeout: int) -> Any:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8") if payload is not None else None
    request = urllib.request.Request(
        f"{API_BASE}{path}",
        data=body,
        headers={"Content-Type": "application/json"},
        method=method,
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def _load_traces(trace_dir: Path) -> list[tuple[Path, dict[str, Any]]]:
    output = []
    for path in sorted(trace_dir.glob("*.json")):
        output.append((path, json.loads(path.read_text(encoding="utf-8"))))
    return output


def _summarize_usage(traces: list[tuple[Path, dict[str, Any]]]) -> dict[str, Any]:
    summary: dict[str, Any] = {
        "call_count": len(traces),
        "successful_call_count": 0,
        "failed_call_count": 0,
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "total_tokens": 0,
        "prompt_cache_hit_tokens": 0,
        "prompt_cache_miss_tokens": 0,
        "api_elapsed_seconds": 0.0,
        "schemas": {},
        "model": "",
    }
    for _, trace in traces:
        usage = trace.get("usage") or {}
        if trace.get("error"):
            summary["failed_call_count"] += 1
        else:
            summary["successful_call_count"] += 1
        summary["model"] = trace.get("model") or summary["model"]
        summary["api_elapsed_seconds"] += float(trace.get("elapsed_seconds") or 0)
        for key in (
            "prompt_tokens", "completion_tokens", "total_tokens",
            "prompt_cache_hit_tokens", "prompt_cache_miss_tokens",
        ):
            summary[key] += int(usage.get(key) or 0)
        schema = trace.get("schema_name") or trace.get("kind") or "unknown"
        summary["schemas"][schema] = summary["schemas"].get(schema, 0) + 1
    summary["api_elapsed_seconds"] = round(summary["api_elapsed_seconds"], 3)
    return summary


def _render_report(payload: dict[str, Any]) -> str:
    response = payload["api_response"]
    usage = payload["trace_summary"]
    lines = [
        "# 规范约束真实 API 验证报告",
        "",
        f"- 生成时间：{payload['generated_at']}",
        f"- 模型：{usage.get('model') or '-'}",
        f"- 文档数：{payload['request_scope']['document_count']}",
        f"- 成功/失败：{response.get('completed_count', 0)}/{response.get('failed_count', 0)}",
        f"- 总耗时：{payload['elapsed_seconds']} 秒",
        f"- 真实调用：{usage['call_count']} 次",
        f"- Token：输入 {usage['prompt_tokens']}，输出 {usage['completion_tokens']}，合计 {usage['total_tokens']}",
        f"- 缓存：命中 {usage['prompt_cache_hit_tokens']}，未命中 {usage['prompt_cache_miss_tokens']}",
        "",
        "## 文档处理结果",
        "",
    ]
    for item in response.get("results", []):
        document = item.get("document") or {}
        document_atoms = payload["constraints"].get(document.get("id"), [])
        lines.extend([
            f"### {document.get('standard_code') or '-'} {document.get('name') or item.get('file_name')}",
            "",
            f"- 分类：{document.get('category') or '-'}",
            f"- 专业：{'、'.join(document.get('disciplines') or []) or '-'}",
            f"- 项目类型：{'、'.join(document.get('project_types') or []) or '-'}",
            f"- 状态：{item.get('status')}",
            f"- 约束原子：{len(document_atoms)}",
            f"- 模型调用：{item.get('llm_call_count', 0)}",
            "",
        ])
        for atom in document_atoms:
            lines.extend([
                f"#### {atom.get('clause_no') or '-'} {atom.get('constraint_type') or '-'}",
                "",
                f"- 原文：{atom.get('source_text') or '-'}",
                f"- 归一化要求：{atom.get('normalized_requirement') or '-'}",
                f"- 审查方式：{atom.get('review_method') or '-'}",
                f"- 严重性：{atom.get('severity') or '-'}",
                f"- AI 可修复：{'是' if atom.get('ai_fixable') else '否'}",
                f"- 来源行：{atom.get('start_line')}-{atom.get('end_line')}",
                "",
            ])
    return "\n".join(lines)


if __name__ == "__main__":
    raise SystemExit(main())
