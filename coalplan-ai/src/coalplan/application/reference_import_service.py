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
    if payload.get("schema_version") == "v2":
        from coalplan.application.reference_atomization_v2 import atomize_reference_markdown_v2
        result = atomize_reference_markdown_v2(document=document, markdown=content, llm=pipeline._structured_llm(), max_batches=payload.get("max_batches"))
        existing, page = [], 1
        while True:
            batch, total = library.search_atoms_page(document_id=document.id, page=page, page_size=100)
            existing.extend(batch)
            if len(existing) >= total or not batch:
                break
            page += 1
        # Retried imports retain previously reviewed/published content and successful batches.
        atoms = {atom.id: atom for atom in result.atoms}
        atoms.update({atom.id: atom for atom in existing})
        library.replace_document_content(document.id, chapters=_chapters(document.id, result.segments), atoms=list(atoms.values()))
        status = "partial" if result.failed_batches else "success"
        return {"document": dump_model(document), "schema_version": "v2", "atom_count": len(atoms), "candidate_count": sum(a.status == ReferenceReviewStatus.pending_publish for a in atoms.values()), "llm_call_count": result.llm_call_count, "failed_batch_count": len(result.failed_batches), "failed_batches": result.failed_batches, "processing_status": status, "user_message": f"已保存 {len(atoms)} 条原子，等待审核发布。", "excluded_segments": result.excluded_segments}
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
