from __future__ import annotations

import json
import hashlib
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path

from coalplan.application.reference_atom_v2 import finalize_v2_atom
from coalplan.application.reference_atomization import build_reference_blocks
from coalplan.domain.documents import stable_id
from coalplan.domain.reference_library import (
    AtomParameterSlot,
    ReferenceAtom,
    ReferenceBlock,
    ReferenceDocument,
    ReferenceReviewStatus,
)
from coalplan.ports.llm import StructuredLLMClient


MAX_SEGMENT_CHARS = 1800
MAX_BATCH_CHARS = 22000
ATOMIZATION_PROMPT_VERSION = "v2.5-primary-process-taxonomy-top16"
ATOM_MATERIALIZATION_VERSION = "v2.2-source-quotes-and-controlled-aliases"


@dataclass
class AtomizationV2Result:
    segments: list[ReferenceBlock]
    atoms: list[ReferenceAtom]
    excluded_segments: list[dict[str, str]]
    llm_call_count: int
    failed_batches: list[dict[str, str]]
    processed_batch_count: int = 0
    total_batch_count: int = 0


def load_reference_taxonomy(path: Path | None = None) -> dict:
    taxonomy_path = (
        path
        or Path(__file__).resolve().parents[3]
        / "config"
        / "reference_library"
        / "reference_atom_taxonomy.v2.json"
    )
    return json.loads(taxonomy_path.read_text(encoding="utf-8"))


def build_semantic_segments(markdown: str) -> list[ReferenceBlock]:
    segments: list[ReferenceBlock] = []
    for block in build_reference_blocks(markdown):
        groups = _coalesce_groups(_split_structural_block(block))
        for index, (content, start, end) in enumerate(groups, start=1):
            segments.append(
                ReferenceBlock(
                    block_id=stable_id("refseg", f"{block.block_id}:{index}:{content}"),
                    title_path=block.title_path,
                    content=content,
                    start_line=start,
                    end_line=end,
                )
            )
    return segments


def _coalesce_groups(groups: list[tuple[str, int, int]]) -> list[tuple[str, int, int]]:
    """Undo OCR/Markdown paragraph fragmentation without breaking complete tables."""
    merged: list[tuple[str, int, int]] = []
    current_text = ""
    current_start = 0
    current_end = 0

    def flush() -> None:
        nonlocal current_text, current_start, current_end
        if current_text:
            merged.append((current_text, current_start, current_end))
        current_text = ""
        current_start = current_end = 0

    for text, start, end in groups:
        is_table = text.lstrip().startswith("|")
        if is_table:
            flush()
            merged.append((text, start, end))
            continue
        if not current_text:
            current_text, current_start, current_end = text, start, end
            continue
        combined = current_text + "\n\n" + text
        if len(combined) <= MAX_SEGMENT_CHARS:
            current_text, current_end = combined, end
        else:
            flush()
            current_text, current_start, current_end = text, start, end
    flush()
    return merged


def atomize_reference_markdown_v2(
    *,
    document: ReferenceDocument,
    markdown: str,
    llm: StructuredLLMClient,
    taxonomy: dict | None = None,
    max_batches: int | None = None,
    selected_segments: list[ReferenceBlock] | None = None,
    concurrency: int = 1,
    checkpoint_dir: Path | None = None,
    max_attempts_per_batch: int = 2,
) -> AtomizationV2Result:
    controlled_taxonomy = taxonomy or load_reference_taxonomy()
    segments = selected_segments if selected_segments is not None else build_semantic_segments(markdown)
    batches = _batch_segments(segments)
    total_batch_count = len(batches)
    if max_batches is not None:
        batches = batches[:max_batches]
    atoms: list[ReferenceAtom] = []
    excluded: list[dict[str, str]] = []
    failures: list[dict[str, str]] = []
    calls = 0
    def process_batch(batch_no: int, batch: list[ReferenceBlock]):
        if checkpoint_dir is not None:
            cached = _load_atom_checkpoint(checkpoint_dir, batch_no, batch)
            if cached is not None:
                return cached, 0, None
        attempts = 0
        last_error = ""
        while attempts < max(1, max_attempts_per_batch):
            attempts += 1
            try:
                payload = llm.complete_json(
                    _v2_prompt(document, batch, controlled_taxonomy),
                    schema_name="reference_atomization_v2",
                )
                if checkpoint_dir is not None:
                    _save_atom_checkpoint(checkpoint_dir, batch_no, batch, payload, None)
                return payload, attempts, None
            except Exception as exc:
                last_error = str(exc)[:300]
        error = {"batch": str(batch_no), "error": last_error, "attempts": str(attempts)}
        if checkpoint_dir is not None:
            _save_atom_checkpoint(checkpoint_dir, batch_no, batch, None, last_error)
        return None, attempts, error

    batch_results = []
    with ThreadPoolExecutor(max_workers=max(1, min(concurrency, 8))) as executor:
        futures = {
            executor.submit(process_batch, batch_no, batch): (batch_no, batch)
            for batch_no, batch in enumerate(batches, start=1)
        }
        for future in as_completed(futures):
            batch_no, batch = futures[future]
            batch_results.append((batch_no, batch, *future.result()))
    for _, batch, payload, batch_calls, error in sorted(batch_results):
        calls += batch_calls
        if payload is not None:
            batch_atoms, batch_excluded = _materialize(document, batch, payload, controlled_taxonomy)
            atoms.extend(batch_atoms)
            excluded.extend(batch_excluded)
        if error is not None:
            failures.append(error)
    return AtomizationV2Result(
        segments, _unique_atoms(atoms), excluded, calls, failures,
        processed_batch_count=len(batches), total_batch_count=total_batch_count,
    )


def _atom_batch_fingerprint(batch: list[ReferenceBlock]) -> str:
    payload = {
        "prompt_version": ATOMIZATION_PROMPT_VERSION,
        "segments": [
            {"id": item.block_id, "title_path": item.title_path, "content": item.content}
            for item in batch
        ],
    }
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _load_atom_checkpoint(checkpoint_dir: Path, batch_no: int, batch: list[ReferenceBlock]) -> dict | None:
    path = checkpoint_dir / f"batch_{batch_no:04d}.json"
    if not path.exists():
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("status") != "completed" or payload.get("fingerprint") != _atom_batch_fingerprint(batch):
        return None
    response = payload.get("payload")
    return response if isinstance(response, dict) else None


def _save_atom_checkpoint(
    checkpoint_dir: Path,
    batch_no: int,
    batch: list[ReferenceBlock],
    payload: dict | None,
    error: str | None,
) -> None:
    checkpoint_dir.mkdir(parents=True, exist_ok=True)
    value = {
        "status": "completed" if payload is not None else "failed",
        "fingerprint": _atom_batch_fingerprint(batch),
        "payload": payload,
        "error": error,
    }
    path = checkpoint_dir / f"batch_{batch_no:04d}.json"
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def _split_structural_block(block: ReferenceBlock) -> list[tuple[str, int, int]]:
    lines = block.content.splitlines()
    groups: list[tuple[str, int, int]] = []
    current: list[str] = []
    current_start = block.start_line
    mode = ""

    def flush(end_line: int) -> None:
        nonlocal current, current_start, mode
        text = "\n".join(current).strip()
        if text:
            groups.extend(_split_long_text(text, current_start, end_line))
        current = []
        mode = ""

    for offset, raw in enumerate(lines):
        line_no = block.start_line + offset
        stripped = raw.strip()
        next_mode = "table" if stripped.startswith("|") else "list" if re.match(r"^(?:[-*+] |\d+[.、]\s*)", stripped) else "text"
        if not stripped:
            flush(line_no - 1)
            current_start = line_no + 1
            continue
        if current and next_mode != mode and {next_mode, mode} != {"text", "list"}:
            flush(line_no - 1)
            current_start = line_no
        if not current:
            current_start = line_no
            mode = next_mode
        current.append(raw)
    flush(block.end_line)
    return groups


def _split_long_text(text: str, start_line: int, end_line: int) -> list[tuple[str, int, int]]:
    if len(text) <= MAX_SEGMENT_CHARS or text.lstrip().startswith("|"):
        return [(text, start_line, end_line)]
    sentences = re.split(r"(?<=[。；！？])", text)
    parts: list[str] = []
    current = ""
    for sentence in sentences:
        if current and len(current) + len(sentence) > MAX_SEGMENT_CHARS:
            parts.append(current.strip())
            current = ""
        current += sentence
    if current.strip():
        parts.append(current.strip())
    return [(part, start_line, end_line) for part in parts if part]


def _batch_segments(segments: list[ReferenceBlock]) -> list[list[ReferenceBlock]]:
    batches: list[list[ReferenceBlock]] = []
    current: list[ReferenceBlock] = []
    size = 0
    for segment in segments:
        addition = len(segment.content) + 240
        if current and size + addition > MAX_BATCH_CHARS:
            batches.append(current)
            current = []
            size = 0
        current.append(segment)
        size += addition
    if current:
        batches.append(current)
    return batches


def _v2_prompt(document: ReferenceDocument, segments: list[ReferenceBlock], taxonomy: dict) -> str:
    source = "\n\n".join(
        f"[segment_id={item.block_id}; lines={item.start_line}-{item.end_line}; title_path={' > '.join(item.title_path) or '-'}]\n{item.content}"
        for item in segments
    )
    return f"""你负责把优秀施工组织设计转化为可复用、可追溯、可参数化的 V2 原子。
来源项目：{document.project_name}
项目类型：{document.project_type}

受控分类表：
{json.dumps(taxonomy, ensure_ascii=False)}

工作要求：
1. 先判断每个 segment 是技术原子来源、章节结构样本、项目事实，还是无效内容。
2. 封面、签批、目录、页眉页脚、纯商务内容、重复文本、口号和仅有编号的内容必须排除。
3. 纯工程概况、工程量和项目专属条件不得包装成跨项目技术原子，可标为 project_fact 并排除。
4. 一个原子只保留一个主要工程对象和一个工艺主题；条件、步骤、控制、检查、异常和记录可组成闭环。
5. 只能组合本批存在且相邻或语义连续的 segment_id，不得改写 raw_excerpt。
   当一个 segment 包含多个原子时，必须为每个原子返回 source_quotes，逐条原样复制该原子真正使用的连续句段。
6. chapter_module、atom_type、process_stage、content_functions、parameter role 和 reuse_policy 必须使用受控分类值。
7. engineering_system 必须使用 engineering_systems 的受控 ID，process_family 必须使用 process_families 的受控 ID；
   engineering_object 和 process_method 使用准确专业名称，不要用“其他”“通用”等空标签。
   单一工艺使用对应的细分类；一个原子确实包含前后连续的多种协同工艺时，使用对应的综合治理分类，
   不得因为文本提到风险、事故或高温就误标为 emergency_response。
8. 识别全部项目名称、地点、桩号、高程、数量、日期、材料参数、设备型号、工艺参数和规范编号为 parameter_slots。
9. action_sequence、control_points、acceptance_checks、exceptions、risks 只提取原文明确表达的内容，不得补写。
10. quality_score 与 confidence 为 0~1。低价值内容宁可排除，不要勉强产出。
11. process_family 按原子的主要施工工序选择，不要因为原文同时出现检查或验收要求就改标为 quality_testing；
    一般机械钻孔、钻进和成孔必须使用 drilling_borehole，只有明确使用炸药、装药、起爆或爆破网路时才使用 drilling_blasting。
12. 每批最多返回 16 条原子，只保留本批最具复用价值、技术信息完整的内容；同一工艺流程的连续步骤、控制点和检查闭环应合并为一个原子，不要按句子碎片化。

返回 JSON：
{{
  "atoms": [{{
    "segment_ids": ["..."], "source_quotes": ["必须是来源中的连续原文"],
    "atom_type": "process", "chapter_module": "process_technology",
    "engineering_system": "", "engineering_object": "", "specialty": "", "work_item": "",
    "process_family": "", "process_method": "", "process_stage": "main_operation",
    "content_functions": ["workflow"], "applicability": [], "prohibited_scenarios": [],
    "action_sequence": [], "control_points": [], "acceptance_checks": [], "exceptions": [], "risks": [],
    "parameter_slots": [{{"slot_key": "", "display_name": "", "source_value": "", "unit": "",
      "data_type": "number_with_unit", "semantic_role": "project_specific", "reuse_policy": "replace_from_evidence",
      "required": false}}],
    "quality_score": 0.0, "confidence": 0.0, "value_reason": ""
  }}],
  "excluded_segments": [{{"segment_id": "...", "category": "signature|toc|commercial|project_fact|generic|duplicate|broken", "reason": ""}}]
}}

待处理片段：
{source}"""


def _materialize(
    document: ReferenceDocument,
    segments: list[ReferenceBlock],
    payload: dict,
    taxonomy: dict,
) -> tuple[list[ReferenceAtom], list[dict[str, str]]]:
    by_id = {item.block_id: item for item in segments}
    allowed = {
        key: set(taxonomy[key])
        for key in (
            "chapter_modules", "atom_types", "process_stages", "content_functions",
            "engineering_systems", "process_families",
        )
    }
    atoms: list[ReferenceAtom] = []
    for candidate in payload.get("atoms", [])[:16]:
        selected = [by_id[item] for item in candidate.get("segment_ids", []) if item in by_id]
        if not selected:
            continue
        selected_content = "\n\n".join(item.content for item in selected).strip()
        quotes = [str(item).strip() for item in candidate.get("source_quotes", []) if str(item).strip()]
        valid_quotes = [resolved for quote in quotes if (resolved := _resolve_source_quote(quote, selected_content))]
        if quotes and not valid_quotes:
            continue
        content = "\n\n".join(valid_quotes).strip() if valid_quotes else selected_content
        quote_warning = bool(quotes) and len(valid_quotes) != len(quotes)
        # Keep short candidates visible for review; the publication gate records
        # incomplete technical meaning instead of silently dropping source text.
        if len(content) < 20:
            continue
        atom_type = _controlled(candidate.get("atom_type"), allowed["atom_types"])
        chapter_module = _controlled(candidate.get("chapter_module"), allowed["chapter_modules"])
        process_stage = _controlled(candidate.get("process_stage"), allowed["process_stages"])
        engineering_system = _taxonomy_value(candidate.get("engineering_system"), "engineering_systems", taxonomy)
        process_family = _taxonomy_value(candidate.get("process_family"), "process_families", taxonomy)
        functions = [item for item in candidate.get("content_functions", []) if item in allowed["content_functions"]]
        slots = []
        for item in candidate.get("parameter_slots", []):
            try:
                item = dict(item)
                source_value = str(item.get("source_value", ""))
                unit = str(item.get("unit", ""))
                if source_value and unit and source_value + unit in content:
                    item["source_value"] = source_value + unit
                slot = AtomParameterSlot(**item)
            except Exception:
                continue
            if slot.source_value and slot.source_value in content:
                slots.append(slot)
        atom = ReferenceAtom(
            id=stable_id(
                "atomv2",
                f"{document.id}:{':'.join(item.block_id for item in selected)}:{atom_type}:"
                f"{candidate.get('process_family', '')}:{content}",
            ),
            document_id=document.id,
            project_name=document.project_name,
            project_type=document.project_type,
            title_path=selected[0].title_path,
            content=content,
            schema_version="v2",
            atom_type=atom_type or "technical_excerpt",
            raw_excerpt=content,
            normalized_text=content,
            source_block_ids=[item.block_id for item in selected],
            start_line=min(item.start_line for item in selected),
            end_line=max(item.end_line for item in selected),
            engineering_object=str(candidate.get("engineering_object", "")).strip(),
            engineering_system=engineering_system,
            specialty=str(candidate.get("specialty", "")).strip(),
            work_item=str(candidate.get("work_item", "")).strip(),
            process=str(candidate.get("process_method", "")).strip(),
            process_family=process_family,
            process_method=str(candidate.get("process_method", "")).strip(),
            process_stage=process_stage,
            chapter_type=chapter_module,
            chapter_module=chapter_module,
            content_functions=functions,
            applicability=_strings(candidate.get("applicability")),
            prohibited_scenarios=_strings(candidate.get("prohibited_scenarios")),
            action_sequence=_strings(candidate.get("action_sequence")),
            control_points=_strings(candidate.get("control_points")),
            acceptance_checks=_strings(candidate.get("acceptance_checks")),
            exceptions=_strings(candidate.get("exceptions")),
            risks=_strings(candidate.get("risks")),
            parameter_slots=slots,
            quality_score=_score(candidate.get("quality_score")),
            confidence=_score(candidate.get("confidence")),
            value_reason=str(candidate.get("value_reason", "")).strip(),
            migration_warning=(
                ["部分模型引文未能逐字定位，原子仅保留已核验的来源引文"] if quote_warning else []
            ),
            status=ReferenceReviewStatus.ai_candidate,
        )
        atom = finalize_v2_atom(atom)
        if not atom.publication_blockers and atom.quality_score >= 0.72 and atom.confidence >= 0.78:
            atom.status = ReferenceReviewStatus.pending_publish
        atoms.append(atom)
    excluded = []
    for item in payload.get("excluded_segments", []):
        segment_id = str(item.get("segment_id", ""))
        if segment_id in by_id:
            excluded.append({
                "segment_id": segment_id,
                "category": str(item.get("category", "generic")),
                "reason": str(item.get("reason", "")),
            })
    return atoms, excluded


def _controlled(value, allowed: set[str]) -> str:
    text = str(value or "").strip()
    return text if text in allowed else ""


def _resolve_source_quote(quote: str, source: str) -> str:
    if quote in source:
        return quote
    compact_source: list[str] = []
    source_positions: list[int] = []
    for index, character in enumerate(source):
        if character.isspace():
            continue
        compact_source.append(character)
        source_positions.append(index)
    compact_quote = "".join(character for character in quote if not character.isspace())
    if not compact_quote:
        return ""
    start = "".join(compact_source).find(compact_quote)
    if start < 0:
        return ""
    end = start + len(compact_quote) - 1
    return source[source_positions[start]:source_positions[end] + 1].strip()


def _taxonomy_value(value, domain: str, taxonomy: dict) -> str:
    text = str(value or "").strip()
    if text in taxonomy.get(domain, []):
        return text
    return str(taxonomy.get("aliases", {}).get(domain, {}).get(text, ""))


def _strings(value) -> list[str]:
    return [str(item).strip() for item in (value or []) if str(item).strip()]


def _score(value) -> float:
    try:
        return min(1.0, max(0.0, float(value)))
    except (TypeError, ValueError):
        return 0.0


def _unique_atoms(atoms: list[ReferenceAtom]) -> list[ReferenceAtom]:
    return list({atom.id: atom for atom in atoms}.values())
