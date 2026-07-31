from __future__ import annotations

import re
from dataclasses import dataclass

from coalplan.domain.documents import stable_id
from coalplan.domain.reference_library import (
    ReferenceAtom,
    ReferenceBlock,
    ReferenceDocument,
    ReferenceFactVariable,
    ReferenceReviewStatus,
)
from coalplan.ports.llm import StructuredLLMClient


MAX_BLOCK_CHARS = 4200
MAX_BATCH_CHARS = 12000
MAX_RETRY_DEPTH = 2


@dataclass
class AtomizationResult:
    blocks: list[ReferenceBlock]
    atoms: list[ReferenceAtom]
    llm_call_count: int
    failed_batch_count: int = 0
    warnings: list[str] | None = None


def build_reference_blocks(markdown: str, *, focus_terms: list[str] | None = None) -> list[ReferenceBlock]:
    lines = markdown.splitlines()
    headings: list[tuple[int, str]] = []
    blocks: list[ReferenceBlock] = []
    body: list[str] = []
    start_line = 1

    def flush(end_line: int) -> None:
        nonlocal body, start_line
        content = "\n".join(body).strip()
        if content:
            for part, part_start, part_end in _split_oversized(content, start_line, end_line):
                block_id = stable_id("refblock", f"{part_start}:{part_end}:{part}")
                blocks.append(
                    ReferenceBlock(
                        block_id=block_id,
                        title_path=[title for _, title in headings],
                        content=part,
                        start_line=part_start,
                        end_line=part_end,
                    )
                )
        body = []

    for line_no, line in enumerate(lines, start=1):
        heading = _parse_heading(line)
        if heading:
            flush(line_no - 1)
            level, title = heading
            while headings and headings[-1][0] >= level:
                headings.pop()
            headings.append((level, title))
            start_line = line_no + 1
            continue
        if not body:
            start_line = line_no
        body.append(line)
    flush(len(lines))

    terms = [item.strip().lower() for item in (focus_terms or []) if item.strip()]
    if not terms:
        return blocks
    focused = [
        block
        for block in blocks
        if any(term in (" ".join(block.title_path) + "\n" + block.content[:1200]).lower() for term in terms)
    ]
    return focused


def atomize_reference_markdown(
    *,
    document: ReferenceDocument,
    markdown: str,
    llm: StructuredLLMClient,
    focus_terms: list[str] | None = None,
    max_batches: int | None = None,
    publish_for_validation: bool = False,
) -> AtomizationResult:
    blocks = build_reference_blocks(markdown, focus_terms=focus_terms)
    batches = _batch_blocks(blocks)
    if max_batches is not None:
        batches = batches[:max_batches]
    atoms: list[ReferenceAtom] = []
    llm_call_count = 0
    failed_batch_count = 0
    warnings: list[str] = []
    for batch_index, batch in enumerate(batches, start=1):
        batch_atoms, calls, failures, batch_warnings = _atomize_batch_resilient(
            document=document,
            blocks=batch,
            llm=llm,
            publish_for_validation=publish_for_validation,
            batch_label=str(batch_index),
        )
        atoms.extend(batch_atoms)
        llm_call_count += calls
        failed_batch_count += failures
        warnings.extend(batch_warnings)
    return AtomizationResult(
        blocks=blocks,
        atoms=atoms,
        llm_call_count=llm_call_count,
        failed_batch_count=failed_batch_count,
        warnings=warnings,
    )


def _atomize_batch_resilient(
    *,
    document: ReferenceDocument,
    blocks: list[ReferenceBlock],
    llm: StructuredLLMClient,
    publish_for_validation: bool,
    batch_label: str,
    retry_depth: int = 0,
) -> tuple[list[ReferenceAtom], int, int, list[str]]:
    try:
        payload = llm.complete_json(_atomization_prompt(document, blocks), schema_name="reference_atomization")
        return (
            _materialize_atoms(
                document=document,
                blocks=blocks,
                payload=payload,
                publish_for_validation=publish_for_validation,
            ),
            1,
            0,
            [],
        )
    except Exception as exc:
        if retry_depth < MAX_RETRY_DEPTH and len(blocks) > 1:
            midpoint = max(1, len(blocks) // 2)
            left = _atomize_batch_resilient(
                document=document,
                blocks=blocks[:midpoint],
                llm=llm,
                publish_for_validation=publish_for_validation,
                batch_label=f"{batch_label}.1",
                retry_depth=retry_depth + 1,
            )
            right = _atomize_batch_resilient(
                document=document,
                blocks=blocks[midpoint:],
                llm=llm,
                publish_for_validation=publish_for_validation,
                batch_label=f"{batch_label}.2",
                retry_depth=retry_depth + 1,
            )
            return (
                left[0] + right[0],
                1 + left[1] + right[1],
                left[2] + right[2],
                left[3] + right[3],
            )
        reason = str(exc).replace("\n", " ").strip()[:160] or type(exc).__name__
        return [], 1, 1, [f"第 {batch_label} 批未能完成，已保留其他成功批次：{reason}"]


def _parse_heading(line: str) -> tuple[int, str] | None:
    match = re.match(r"^\s*(#{1,6})\s+(.+?)\s*$", line)
    if not match:
        return None
    title = match.group(2).strip().strip("#").strip()
    if not title or title.startswith("|") or re.match(r"^(图|表)\s*\d", title):
        return None
    explicit_level = len(match.group(1))
    numbered = re.match(r"^(\d+(?:\.\d+){0,5})(?:[.\s、]|$)", title)
    inferred_level = numbered.group(1).count(".") + 1 if numbered else explicit_level
    return min(6, inferred_level), title


def _split_oversized(content: str, start_line: int, end_line: int):
    if len(content) <= MAX_BLOCK_CHARS:
        yield content, start_line, end_line
        return
    parts = re.split(r"\n{2,}", content)
    current: list[str] = []
    current_chars = 0
    cursor = start_line
    part_start = start_line
    for part in parts:
        addition = len(part) + (2 if current else 0)
        if current and current_chars + addition > MAX_BLOCK_CHARS:
            text = "\n\n".join(current)
            line_count = text.count("\n") + 1
            yield text, part_start, cursor + line_count - 1
            cursor += line_count
            part_start = cursor
            current = []
            current_chars = 0
        current.append(part)
        current_chars += addition
    if current:
        yield "\n\n".join(current), part_start, end_line


def _batch_blocks(blocks: list[ReferenceBlock]) -> list[list[ReferenceBlock]]:
    batches: list[list[ReferenceBlock]] = []
    current: list[ReferenceBlock] = []
    size = 0
    for block in blocks:
        block_size = len(block.content) + 300
        if current and size + block_size > MAX_BATCH_CHARS:
            batches.append(current)
            current = []
            size = 0
        current.append(block)
        size += block_size
    if current:
        batches.append(current)
    return batches


def _atomization_prompt(document: ReferenceDocument, blocks: list[ReferenceBlock]) -> str:
    block_text = "\n\n".join(
        [
            f"[block_id={block.block_id}; lines={block.start_line}-{block.end_line}; "
            f"title_path={' > '.join(block.title_path) or '-'}]\n{block.content}"
            for block in blocks
        ]
    )
    return f"""你负责把优秀施工组织设计切分并标注为可检索原子。原文来自“{document.project_name}”，项目类型“{document.project_type}”。

规则：
1. 由你决定相邻 block 的合并与拆分边界，但只能引用下方存在的 block_id，不得改写原文。
2. 一个原子表达一个完整技术要点；工艺条件、步骤、控制参数、检查验收和异常处置尽量保持闭环。
3. 表单、审批封面、目录、专家意见、空泛口号和仅有图表编号的块不要输出。
4. 识别项目名称、地名、桩号、工程量、日期、设备数量、材料配比、施工参数、规范版本为 fact_variables。
5. quality_score 与 confidence 范围为 0~1。
6. 每批最多输出10个最具复用价值的原子；每个原子的 fact_variables 最多8项，避免重复罗列同类参数。

返回 JSON 对象：
{{"atoms":[{{"block_ids":["..."],"title_path":["..."],"engineering_object":"","specialty":"","work_item":"",
"process":"","process_stage":"","chapter_type":"","content_functions":["工艺流程"],
"applicability":[""],"prohibited_scenarios":[""],"fact_variables":[{{"name":"","value":"","variable_type":"project_specific"}}],
"quality_score":0.0,"confidence":0.0}}]}}

待处理原文块：
{block_text}"""


def _materialize_atoms(
    *,
    document: ReferenceDocument,
    blocks: list[ReferenceBlock],
    payload: dict,
    publish_for_validation: bool,
) -> list[ReferenceAtom]:
    by_id = {block.block_id: block for block in blocks}
    atoms: list[ReferenceAtom] = []
    seen_atom_ids: set[str] = set()
    for candidate in payload.get("atoms", []):
        selected = [by_id[item] for item in candidate.get("block_ids", []) if item in by_id]
        if not selected:
            continue
        content = "\n\n".join(block.content for block in selected).strip()
        if len(content) < 80:
            continue
        confidence = _score(candidate.get("confidence"))
        quality_score = _score(candidate.get("quality_score"))
        status = (
            ReferenceReviewStatus.published
            if publish_for_validation and confidence >= 0.75 and quality_score >= 0.65
            else ReferenceReviewStatus.ai_candidate
        )
        atom_id = stable_id("atom", f"{document.id}:{':'.join(block.block_id for block in selected)}")
        if atom_id in seen_atom_ids:
            continue
        seen_atom_ids.add(atom_id)
        variables = [
            ReferenceFactVariable(
                name=str(item.get("name", "")).strip(),
                value=str(item.get("value", "")).strip(),
                variable_type=str(item.get("variable_type", "project_specific")).strip() or "project_specific",
            )
            for item in candidate.get("fact_variables", [])
            if str(item.get("value", "")).strip()
        ]
        atoms.append(
            ReferenceAtom(
                id=atom_id,
                document_id=document.id,
                project_name=document.project_name,
                project_type=document.project_type,
                title_path=[str(item) for item in candidate.get("title_path", [])] or selected[0].title_path,
                content=content,
                source_block_ids=[block.block_id for block in selected],
                start_line=min(block.start_line for block in selected),
                end_line=max(block.end_line for block in selected),
                engineering_object=str(candidate.get("engineering_object", "")).strip(),
                specialty=str(candidate.get("specialty", "")).strip(),
                work_item=str(candidate.get("work_item", "")).strip(),
                process=str(candidate.get("process", "")).strip(),
                process_stage=str(candidate.get("process_stage", "")).strip(),
                chapter_type=str(candidate.get("chapter_type", "")).strip(),
                content_functions=[str(item) for item in candidate.get("content_functions", [])],
                applicability=[str(item) for item in candidate.get("applicability", [])],
                prohibited_scenarios=[str(item) for item in candidate.get("prohibited_scenarios", [])],
                fact_variables=variables,
                quality_score=quality_score,
                confidence=confidence,
                status=status,
            )
        )
    return atoms


def _score(value) -> float:
    try:
        return max(0.0, min(1.0, float(value)))
    except (TypeError, ValueError):
        return 0.0
