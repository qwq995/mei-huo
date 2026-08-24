from __future__ import annotations

import hashlib
from pathlib import Path

from coalplan.application.reference_atomization import atomize_reference_markdown
from coalplan.application.serialization import dump_model
from coalplan.domain.documents import stable_id
from coalplan.domain.reference_library import ReferenceChapter, ReferenceDocument, ReferenceDocumentKind, ReferenceReviewStatus


def process_reference_markdown(*, pipeline, library, payload: dict) -> dict:
    content = str(payload.get("content") or "")
    file_name = Path(str(payload.get("file_name") or "reference.md")).name
    digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
    document_id = stable_id("refdoc", digest)
    source_path = pipeline.artifacts.write_text("reference-library", f"sources/{document_id}/{file_name}", content)
    document = ReferenceDocument(
        id=document_id, content_hash=digest, source_path=source_path, file_name=file_name,
        project_name=str(payload.get("project_name") or file_name),
        project_type=str(payload.get("project_type") or "未分类"),
        document_kind=ReferenceDocumentKind(str(payload.get("document_kind") or ReferenceDocumentKind.special_plan.value)),
    )
    library.save_document(document)
    result = atomize_reference_markdown(
        document=document, markdown=content, llm=pipeline._structured_llm(),
        focus_terms=list(payload.get("focus_terms") or []), max_batches=payload.get("max_batches"), publish_for_validation=False,
    )
    library.replace_document_content(document.id, chapters=_chapters(document.id, result.blocks), atoms=result.atoms)
    status = "success" if not result.failed_batch_count else ("partial" if result.atoms else "failed")
    messages = {
        "success": f"已生成 {len(result.atoms)} 条候选原子，可开始抽查。",
        "partial": f"部分批次未完成，已保留 {len(result.atoms)} 条成功候选，可先抽查或稍后重试。",
        "failed": "文档已保存，但本次 AI 切分未产出候选。可以从任务中心重试。",
    }
    return {
        "document": dump_model(document), "block_count": len(result.blocks), "atom_count": len(result.atoms),
        "llm_call_count": result.llm_call_count, "failed_batch_count": result.failed_batch_count,
        "warnings": result.warnings or [], "processing_status": status, "user_message": messages[status],
        "candidate_count": sum(item.status == ReferenceReviewStatus.ai_candidate for item in result.atoms),
        "next_step": "抽查候选原子的标题、工艺标签和正文后，发布可复用内容。",
    }


def _chapters(document_id: str, blocks) -> list[ReferenceChapter]:
    ranges: dict[tuple[str, ...], tuple[int, int]] = {}
    for block in blocks:
        key = tuple(block.title_path)
        if not key:
            continue
        start, end = ranges.get(key, (block.start_line, block.end_line))
        ranges[key] = (min(start, block.start_line), max(end, block.end_line))
    return [ReferenceChapter(id=stable_id("refchapter", f"{document_id}:{' > '.join(path)}"), document_id=document_id, title_path=list(path), start_line=lines[0], end_line=lines[1], sort_order=index) for index, (path, lines) in enumerate(ranges.items(), start=1)]
