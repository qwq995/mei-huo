from __future__ import annotations

import json
import hashlib
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path

from coalplan.application.reference_atomization_v2 import load_reference_taxonomy
from coalplan.domain.reference_library import ReferenceBlock, ReferenceDocument
from coalplan.ports.llm import StructuredLLMClient


ROUTES = {"atom_source", "chapter_sample", "project_fact", "exclude"}


@dataclass(frozen=True)
class SectionRoute:
    title_path: list[str]
    route: str
    chapter_module: str
    reason: str
    confidence: float
    segment_ids: list[str]


@dataclass(frozen=True)
class DocumentRoutingResult:
    project_type: str
    routes: list[SectionRoute]
    selected_segments: list[ReferenceBlock]
    llm_call_count: int
    failed_batches: list[str]


def route_reference_sections(
    *,
    document: ReferenceDocument,
    segments: list[ReferenceBlock],
    llm: StructuredLLMClient,
    taxonomy: dict | None = None,
    paths_per_batch: int = 80,
    concurrency: int = 1,
    checkpoint_dir: Path | None = None,
) -> DocumentRoutingResult:
    taxonomy = taxonomy or load_reference_taxonomy()
    grouped: dict[tuple[str, ...], list[ReferenceBlock]] = {}
    for segment in segments:
        grouped.setdefault(tuple(segment.title_path), []).append(segment)
    entries = _routing_entries(grouped)
    route_by_key: dict[str, SectionRoute] = {}
    project_types: list[str] = []
    calls = 0
    failures: list[str] = []
    batches = [entries[start:start + paths_per_batch] for start in range(0, len(entries), paths_per_batch)]

    def process_batch(batch_no: int, batch: list[dict]):
        if checkpoint_dir is not None:
            cached = _load_route_checkpoint(checkpoint_dir, batch_no, batch)
            if cached is not None:
                return cached, 0, []
        responses, batch_calls, batch_failures = _route_batch(document, batch, llm, taxonomy)
        if checkpoint_dir is not None:
            _save_route_checkpoint(checkpoint_dir, batch_no, batch, responses, batch_calls, batch_failures)
        return responses, batch_calls, batch_failures

    batch_results = []
    with ThreadPoolExecutor(max_workers=max(1, min(concurrency, 8))) as executor:
        futures = {
            executor.submit(process_batch, batch_no, batch): batch_no
            for batch_no, batch in enumerate(batches, start=1)
        }
        for future in as_completed(futures):
            batch_results.append((futures[future], future.result()))
    for _, (responses, batch_calls, batch_failures) in sorted(batch_results):
        calls += batch_calls
        failures.extend(batch_failures)
        for response_batch, payload in responses:
            project_type = str(payload.get("project_type", "")).strip()
            if project_type:
                project_types.append(project_type)
            valid_keys = {entry["path_key"] for entry in response_batch}
            for item in payload.get("sections", []):
                path_key = str(item.get("path_key", ""))
                route = str(item.get("route", ""))
                chapter_module = str(item.get("chapter_module", ""))
                if path_key not in valid_keys or route not in ROUTES:
                    continue
                if chapter_module not in taxonomy["chapter_modules"]:
                    chapter_module = ""
                original = next(entry["title_path"] for entry in response_batch if entry["path_key"] == path_key)
                route_by_key[path_key] = SectionRoute(
                    title_path=original,
                    route=route,
                    chapter_module=chapter_module,
                    reason=str(item.get("reason", "")).strip(),
                    confidence=_score(item.get("confidence")),
                    segment_ids=next(entry["segment_ids"] for entry in response_batch if entry["path_key"] == path_key),
                )
    # Missing model decisions remain visible as chapter samples; they are never
    # silently promoted to reusable technical atoms.
    routes = []
    for entry in entries:
        routes.append(route_by_key.get(entry["path_key"], SectionRoute(
            title_path=entry["title_path"], route="chapter_sample", chapter_module="",
            reason="AI 未返回该标题路径，保留章节结构但不进入技术原子切分", confidence=0.0,
            segment_ids=entry["segment_ids"],
        )))
    selected_ids = {
        segment_id
        for item in routes if item.route == "atom_source"
        for segment_id in item.segment_ids
    }
    selected = [segment for segment in segments if segment.block_id in selected_ids]
    return DocumentRoutingResult(_majority(project_types) or document.project_type, routes, selected, calls, failures)


def _route_fingerprint(entries: list[dict]) -> str:
    payload = json.dumps(_public_entries(entries), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _load_route_checkpoint(checkpoint_dir: Path, batch_no: int, entries: list[dict]):
    path = checkpoint_dir / f"batch_{batch_no:04d}.json"
    if not path.exists():
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("status") != "completed" or payload.get("fingerprint") != _route_fingerprint(entries):
        return None
    by_key = {entry["path_key"]: entry for entry in entries}
    responses = []
    for item in payload.get("responses", []):
        response_entries = [by_key[key] for key in item.get("path_keys", []) if key in by_key]
        if response_entries:
            responses.append((response_entries, item.get("payload", {})))
    return responses


def _save_route_checkpoint(
    checkpoint_dir: Path,
    batch_no: int,
    entries: list[dict],
    responses: list[tuple[list[dict], dict]],
    calls: int,
    failures: list[str],
) -> None:
    checkpoint_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "status": "completed" if not failures else "partial",
        "fingerprint": _route_fingerprint(entries),
        "llm_call_count": calls,
        "failures": failures,
        "responses": [
            {"path_keys": [entry["path_key"] for entry in response_entries], "payload": response}
            for response_entries, response in responses
        ],
    }
    path = checkpoint_dir / f"batch_{batch_no:04d}.json"
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def _route_batch(
    document: ReferenceDocument,
    entries: list[dict],
    llm: StructuredLLMClient,
    taxonomy: dict,
    depth: int = 0,
) -> tuple[list[tuple[list[dict], dict]], int, list[str]]:
    try:
        payload = llm.complete_json(
            _routing_prompt(document, entries, taxonomy),
            schema_name="reference_section_routing_v2",
        )
        return [(entries, payload)], 1, []
    except Exception as exc:
        # Recursive subdivision repairs malformed or truncated structured JSON.
        # Provider/auth/balance failures affect every child request, so retrying
        # them only multiplies cost and noise.
        if _can_recover_by_splitting(exc) and depth < 3 and len(entries) > 20:
            midpoint = len(entries) // 2
            left = _route_batch(document, entries[:midpoint], llm, taxonomy, depth + 1)
            right = _route_batch(document, entries[midpoint:], llm, taxonomy, depth + 1)
            return left[0] + right[0], 1 + left[1] + right[1], left[2] + right[2]
        return [], 1, [str(exc)[:300]]


def _can_recover_by_splitting(exc: Exception) -> bool:
    message = str(exc).lower()
    terminal_markers = (
        "http 401", "http 402", "http 403", "http 404", "http 429",
        "insufficient balance", "authentication", "unauthorized", "forbidden",
        "connection refused", "name or service not known", "timed out",
    )
    return not any(marker in message for marker in terminal_markers)


def _routing_prompt(document: ReferenceDocument, entries: list[dict], taxonomy: dict) -> str:
    return f"""你负责对优秀施工组织设计的章节做语义路由，不做关键词硬匹配。
文件名：{document.file_name}
候选项目名：{document.project_name}

路由定义：
- atom_source：摘要中已经出现可执行的方法、连续步骤、条件与参数、检查验收、异常处置或明确接口，能够形成独立技术要点。
- chapter_sample：章节框架、管理原则、职责制度、保证体系、一般性要求或仅有标题层次，主要价值是组织方式。
- project_fact：工程名称、地点、数量、工期、合同范围等当前历史项目事实。
- exclude：封面签批、目录、页眉页脚、商务报价、空泛口号、重复或破损内容。

文档模块只能选：{json.dumps(taxonomy['chapter_modules'], ensure_ascii=False)}
请根据标题路径与短摘要判断，不要因为出现“施工”二字就一律归入 atom_source。
严格控制 atom_source：
- “加强管理、严格控制、确保质量、落实责任”等没有具体动作和检查闭环的表述必须归入 chapter_sample 或 exclude。
- 质量、安全、环保章节只有在摘要明确给出作业方法、检查对象、触发条件、处置步骤或记录成果时才是 atom_source。
- 单纯规范清单、人员名单、设备数量表、进度日期和工程量表不是技术原子。
- 不确定时选择 chapter_sample。通常每批 atom_source 不应超过一半，确属连续工艺技术章节时除外。
返回 JSON：
{{"project_type":"准确的项目族/工程类型","sections":[{{"path_key":"原值","route":"atom_source|chapter_sample|project_fact|exclude","chapter_module":"受控值或空字符串","reason":"","confidence":0.0}}]}}

章节清单：
{json.dumps(_public_entries(entries), ensure_ascii=False)}"""


def _routing_entries(grouped: dict[tuple[str, ...], list[ReferenceBlock]]) -> list[dict]:
    entries: list[dict] = []
    for path, items in grouped.items():
        windows = _split_route_windows(items)
        for index, window in enumerate(windows, start=1):
            base_key = _path_key(path)
            path_key = base_key if len(windows) == 1 else f"{base_key} :: 内容窗口 {index}"
            entries.append({
                "path_key": path_key,
                "title_path": list(path),
                "character_count": sum(len(item.content) for item in window),
                "sample": _sample(window),
                "segment_ids": [item.block_id for item in window],
            })
    return entries


def _split_route_windows(items: list[ReferenceBlock], *, max_segments: int = 8, max_chars: int = 7000) -> list[list[ReferenceBlock]]:
    if len(items) <= max_segments and sum(len(item.content) for item in items) <= max_chars:
        return [items]
    windows: list[list[ReferenceBlock]] = []
    current: list[ReferenceBlock] = []
    size = 0
    for item in items:
        if current and (len(current) >= max_segments or size + len(item.content) > max_chars):
            windows.append(current)
            current = []
            size = 0
        current.append(item)
        size += len(item.content)
    if current:
        windows.append(current)
    return windows


def _public_entries(entries: list[dict]) -> list[dict]:
    return [
        {key: value for key, value in entry.items() if key != "segment_ids"}
        for entry in entries
    ]


def _sample(items: list[ReferenceBlock]) -> str:
    text = " ".join(item.content.replace("\n", " ") for item in items[:2])
    return text[:260]


def _path_key(path: tuple[str, ...]) -> str:
    return " > ".join(path) or "__root__"


def _majority(values: list[str]) -> str:
    if not values:
        return ""
    return max(set(values), key=values.count)


def _score(value) -> float:
    try:
        return max(0.0, min(1.0, float(value)))
    except (TypeError, ValueError):
        return 0.0
