from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path

from coalplan.domain.documents import stable_id
from coalplan.domain.standard_constraints import (
    ConstraintAtom,
    ConstraintReviewStatus,
    ConstraintSeverity,
    StandardDocument,
    StandardDocumentStatus,
)
from coalplan.ports.llm import StructuredLLMClient


MAX_BLOCK_CHARS = 3600
MAX_BATCH_CHARS = 12000
CLAUSE_RE = re.compile(r"^\s*(?P<clause>\d+(?:\.\d+){1,5})\s+(?P<body>.+?)\s*$")
HEADING_RE = re.compile(r"^\s*#{1,6}\s+(?P<title>.+?)\s*$")
CODE_RE = re.compile(
    r"\b(?:GB(?:[/_]T)?|DL[/_]T|SL[/_]T|SL|NB[/_]T|JGJ|JTG(?:[/_]T)?|TB|HJ)"
    r"\s*[-_ ]?[A-Z0-9./—–-]+",
    re.I,
)
CLASSIFICATION_BATCH_SIZE = 10


@dataclass(frozen=True)
class StandardBlock:
    block_id: str
    clause_no: str
    title_path: list[str]
    content: str
    start_line: int
    end_line: int


@dataclass(frozen=True)
class ConstraintExtractionResult:
    document: StandardDocument
    atoms: list[ConstraintAtom]
    block_count: int
    llm_call_count: int
    failed_batch_count: int
    warnings: list[str]


def infer_standard_metadata(file_name: str, markdown: str) -> dict:
    stem = Path(file_name).stem.replace(".pdf", "")
    first_text = "\n".join(markdown.splitlines()[:80])
    code_match = CODE_RE.search(stem) or CODE_RE.search(first_text)
    code = re.sub(r"_", "/", code_match.group(0)).strip() if code_match else ""
    name = stem
    if code_match and code_match.group(0) in stem:
        name = stem.replace(code_match.group(0), "", 1).strip(" -_") or stem
    return {"standard_code": code, "name": name, "category": "未分类", "disciplines": [], "project_types": []}


def classify_standard_sources(*, sources: list[dict], llm: StructuredLLMClient, batch_size: int = CLASSIFICATION_BATCH_SIZE) -> dict[str, dict]:
    """Classify multiple standards with structured AI calls; no domain keyword table is used."""
    output: dict[str, dict] = {}
    for offset in range(0, len(sources), max(1, batch_size)):
        batch = sources[offset : offset + max(1, batch_size)]
        output.update(_classify_batch_resilient(batch, llm))
    for item in sources:
        source_id = str(item["source_id"])
        output.setdefault(source_id, {
            **infer_standard_metadata(item["file_name"], item["markdown"]),
            "category": "其他",
            "classification_warning": "AI 未返回该文档的分类结果，已保留文档供人工确认。",
        })
    return output


def _classify_batch_resilient(batch: list[dict], llm: StructuredLLMClient) -> dict[str, dict]:
    try:
        payload = llm.complete_json(_classification_prompt(batch), schema_name="standard_document_classification")
    except Exception as exc:
        if len(batch) > 1:
            midpoint = len(batch) // 2
            return {**_classify_batch_resilient(batch[:midpoint], llm), **_classify_batch_resilient(batch[midpoint:], llm)}
        source = batch[0]
        return {
            str(source["source_id"]): {
                **infer_standard_metadata(source["file_name"], source["markdown"]),
                "category": "其他",
                "classification_warning": f"AI 分类失败，已保留文档供人工分类：{str(exc)[:120]}",
            }
        }
    known_ids = {str(item["source_id"]): item for item in batch}
    output: dict[str, dict] = {}
    for item in payload.get("documents", []):
        source_id = str(item.get("source_id") or "")
        if source_id not in known_ids:
            continue
        identity = infer_standard_metadata(known_ids[source_id]["file_name"], known_ids[source_id]["markdown"])
        output[source_id] = {
            **identity,
            "category": str(item.get("category") or "其他").strip(),
            "disciplines": _strings(item.get("disciplines")),
            "project_types": _strings(item.get("project_types")),
        }
    for source_id, source in known_ids.items():
        output.setdefault(source_id, {
            **infer_standard_metadata(source["file_name"], source["markdown"]),
            "category": "其他",
            "classification_warning": "AI 未返回该文档的分类结果，已保留文档供人工确认。",
        })
    return output


def build_standard_blocks(markdown: str) -> list[StandardBlock]:
    lines = markdown.splitlines()
    headings: list[tuple[int, str]] = []
    raw_blocks: list[tuple[str, list[str], list[str], int, int]] = []
    current_clause = ""
    current_body: list[str] = []
    start_line = 1

    def flush(end_line: int) -> None:
        nonlocal current_body, start_line
        content = "\n".join(current_body).strip()
        if content:
            raw_blocks.append((current_clause, [title for _, title in headings], current_body[:], start_line, end_line))
        current_body = []

    for line_no, line in enumerate(lines, start=1):
        heading = HEADING_RE.match(line)
        if heading:
            flush(line_no - 1)
            level = len(line) - len(line.lstrip("#"))
            while headings and headings[-1][0] >= level:
                headings.pop()
            headings.append((level, heading.group("title").strip()))
            current_clause = ""
            start_line = line_no + 1
            continue
        clause = CLAUSE_RE.match(line)
        if clause:
            flush(line_no - 1)
            current_clause = clause.group("clause")
            current_body = [line]
            start_line = line_no
            continue
        if not current_body:
            start_line = line_no
        current_body.append(line)
    flush(len(lines))

    blocks: list[StandardBlock] = []
    for clause_no, title_path, body, block_start, block_end in raw_blocks:
        content = "\n".join(body).strip()
        if len(content) < 8:
            continue
        for index, part in enumerate(_split_text(content), start=1):
            block_id = stable_id("stdblock", f"{block_start}:{block_end}:{index}:{part}")
            blocks.append(StandardBlock(block_id, clause_no, title_path, part, block_start, block_end))
    return blocks


def extract_standard_constraints(
    *,
    file_name: str,
    markdown: str,
    source_path: str,
    llm: StructuredLLMClient,
    max_batches: int | None = None,
    metadata: dict | None = None,
) -> ConstraintExtractionResult:
    digest = hashlib.sha256(markdown.encode("utf-8")).hexdigest()
    classification_calls = 0
    if metadata is None:
        metadata = classify_standard_sources(
            sources=[{"source_id": "single", "file_name": file_name, "markdown": markdown}],
            llm=llm,
        )["single"]
        classification_calls = 1
    document = StandardDocument(
        id=stable_id("standard", digest),
        file_name=file_name,
        source_path=source_path,
        content_hash=digest,
        status=StandardDocumentStatus.processing,
        **{key: metadata[key] for key in ("standard_code", "name", "category", "disciplines", "project_types")},
    )
    blocks = build_standard_blocks(markdown)
    candidate_blocks = [block for block in blocks if _is_constraint_candidate(block)]
    batches = _batch_blocks(candidate_blocks)
    if max_batches is not None:
        batches = batches[:max_batches]
    atoms: list[ConstraintAtom] = []
    warnings: list[str] = [str(metadata["classification_warning"])] if metadata.get("classification_warning") else []
    if not candidate_blocks:
        warnings.append("未识别到可提取的规范条款；原始 Markdown 可能仅含封面、目录或正文转换不完整，请人工检查来源文件。")
    calls = classification_calls
    failures = 0
    for index, batch in enumerate(batches, start=1):
        try:
            payload = llm.complete_json(_extraction_prompt(document, batch), schema_name="standard_constraint_atomization")
            atoms.extend(_materialize(document, batch, payload))
            calls += 1
        except Exception as exc:
            calls += 1
            failures += 1
            warnings.append(f"第 {index} 批条款提取失败，其他批次已保留：{str(exc)[:120]}")
    unique = {atom.id: atom for atom in atoms}
    atoms = list(unique.values())
    if candidate_blocks and not atoms and not failures:
        warnings.append("AI 未从候选条款中形成约束原子，文档已保留并等待人工确认或重新处理。")
    document.atom_count = len(atoms)
    document.warning_count = len(warnings)
    incomplete = failures or not atoms
    document.status = StandardDocumentStatus.failed if failures and not atoms else (StandardDocumentStatus.partial if incomplete else StandardDocumentStatus.ready)
    return ConstraintExtractionResult(document, atoms, len(blocks), calls, failures, warnings)


def _classification_prompt(sources: list[dict]) -> str:
    entries = "\n\n".join(
        f"[source_id={item['source_id']}; file_name={item['file_name']}]\n{_classification_excerpt(item['markdown'])}"
        for item in sources
    )
    return f"""你负责批量分类中国工程建设规范文档。依据文件名、首页、总则和目录摘要判断，不要依据固定关键词映射。

对每份输入都返回一项。category 使用简洁稳定的业务类别，例如施工组织、施工技术、安全、质量验收、试验检测、设计、强制性条文或其他；disciplines 与 project_types 使用规范实际覆盖范围，可多选。无法判断时保持“其他”并降低 confidence，不得臆测。

返回 JSON：
{{"documents":[{{"source_id":"","category":"","disciplines":[],"project_types":[],"summary":"","confidence":0.0}}]}}

待分类文档：
{entries}"""


def _classification_excerpt(markdown: str) -> str:
    lines = [line for line in markdown.splitlines() if line.strip()]
    return "\n".join(lines[:120])[:6000]


def _split_text(content: str) -> list[str]:
    if len(content) <= MAX_BLOCK_CHARS:
        return [content]
    paragraphs = re.split(r"\n{2,}", content)
    output: list[str] = []
    current = ""
    for paragraph in paragraphs:
        candidate = f"{current}\n\n{paragraph}".strip()
        if current and len(candidate) > MAX_BLOCK_CHARS:
            output.append(current)
            current = paragraph
        else:
            current = candidate
    if current:
        output.append(current)
    return output


def _batch_blocks(blocks: list[StandardBlock]) -> list[list[StandardBlock]]:
    output: list[list[StandardBlock]] = []
    current: list[StandardBlock] = []
    size = 0
    for block in blocks:
        block_size = len(block.content) + 240
        if current and size + block_size > MAX_BATCH_CHARS:
            output.append(current)
            current, size = [], 0
        current.append(block)
        size += block_size
    if current:
        output.append(current)
    return output


def _is_constraint_candidate(block: StandardBlock) -> bool:
    if not block.clause_no:
        return False
    if any(re.sub(r"\s+", "", title) in {"目录", "目次"} for title in block.title_path):
        return False
    compact = re.sub(r"\s+", "", block.content)
    if "……" in compact or re.search(r"\.{5,}\d+$", compact):
        return False
    return bool(re.search(r"必须|应当|应|不得|严禁|不应|不宜|宜|可|允许|偏差|合格率|不合格", compact))


def _extraction_prompt(document: StandardDocument, blocks: list[StandardBlock]) -> str:
    source = "\n\n".join(
        f"[block_id={block.block_id}; clause={block.clause_no or '-'}; lines={block.start_line}-{block.end_line}; title={' > '.join(block.title_path) or '-'}]\n{block.content}"
        for block in blocks
    )
    return f"""你正在执行“规范约束拆分”技能。将《{document.standard_code} {document.name}》拆成仅供施工组织设计成稿审查使用的约束原子。

要求：
1. 一个原子表达一项可独立判断的要求，原文必须逐字来自一个 block，不得虚构条款。
2. 不要输出术语定义、目录、前言、引用文件列表和纯说明性文字。
3. constraint_type 仅从：禁止性要求、强制性要求、数值阈值、允许偏差、工序闭环、资质审批、验收记录、适用条件、一般技术要求 中选择。
4. review_method 仅从：semantic_review、numeric_compare、presence_check、evidence_check、applicability_check 中选择。
5. ai_fixable 仅在修改正文措辞、补全已有依据支持的步骤或措施即可合规时为 true；涉及资质、审批、检测报告、现场实测、设计参数或事实缺失时必须为 false。
6. status：高置信且原文明确时为 published，否则为 ai_candidate。所有约束只在最终审查阶段使用，不参与目录或正文生成。
7. 每批最多输出 16 条高价值约束。

返回 JSON：
{{"atoms":[{{"block_id":"","clause_no":"","source_text":"","normalized_requirement":"","constraint_type":"","review_method":"semantic_review","severity":"blocking|warning|advisory","disciplines":[],"project_types":[],"chapter_scopes":[],"keywords":[],"applicability":[],"exceptions":[],"evidence_required":[],"ai_fixable":false,"repair_instruction":"","confidence":0.0,"status":"published|ai_candidate"}}]}}

规范原文：
{source}"""


def _materialize(document: StandardDocument, blocks: list[StandardBlock], payload: dict) -> list[ConstraintAtom]:
    by_id = {block.block_id: block for block in blocks}
    output: list[ConstraintAtom] = []
    for candidate in payload.get("atoms", []):
        block = by_id.get(str(candidate.get("block_id") or ""))
        if block is None:
            continue
        quoted = str(candidate.get("source_text") or "").strip()
        source_text = quoted if quoted and quoted in block.content else block.content
        confidence = _score(candidate.get("confidence"))
        status_value = str(candidate.get("status") or "")
        status = ConstraintReviewStatus.published if status_value == "published" and confidence >= 0.72 else ConstraintReviewStatus.ai_candidate
        clause_no = str(candidate.get("clause_no") or block.clause_no).strip()
        output.append(
            ConstraintAtom(
                id=stable_id("constraint", f"{document.id}:{clause_no}:{source_text}"),
                document_id=document.id,
                standard_code=document.standard_code,
                standard_name=document.name,
                clause_no=clause_no,
                title_path=block.title_path,
                source_text=source_text,
                normalized_requirement=str(candidate.get("normalized_requirement") or source_text).strip(),
                constraint_type=str(candidate.get("constraint_type") or "一般技术要求").strip(),
                review_method=str(candidate.get("review_method") or "semantic_review").strip(),
                severity=_severity(candidate.get("severity")),
                disciplines=_strings(candidate.get("disciplines")),
                project_types=_strings(candidate.get("project_types")),
                chapter_scopes=_strings(candidate.get("chapter_scopes")),
                keywords=_strings(candidate.get("keywords")),
                applicability=_strings(candidate.get("applicability")),
                exceptions=_strings(candidate.get("exceptions")),
                evidence_required=_strings(candidate.get("evidence_required")),
                ai_fixable=bool(candidate.get("ai_fixable", False)),
                repair_instruction=str(candidate.get("repair_instruction") or "").strip(),
                start_line=block.start_line,
                end_line=block.end_line,
                confidence=confidence,
                status=status,
            )
        )
    return output


def _strings(value) -> list[str]:
    return [str(item).strip() for item in (value or []) if str(item).strip()]


def _score(value) -> float:
    try:
        return max(0.0, min(1.0, float(value)))
    except (TypeError, ValueError):
        return 0.0


def _severity(value) -> ConstraintSeverity:
    try:
        return ConstraintSeverity(str(value))
    except ValueError:
        return ConstraintSeverity.warning
