from __future__ import annotations

import hashlib
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from coalplan.application.reference_atom_retrieval import retrieve_reference_atoms
from coalplan.application.reference_atomization import atomize_reference_markdown
from coalplan.application.serialization import dump_model
from coalplan.domain.documents import stable_id
from coalplan.domain.reference_library import (
    AtomRetrievalQuery,
    ReferenceChapter,
    ReferenceDocument,
    ReferenceDocumentKind,
    ReferenceReviewStatus,
)


router = APIRouter(prefix="/reference-library", tags=["reference-library"])


class ReferenceImportRequest(BaseModel):
    source_path: str
    project_name: str
    project_type: str
    document_kind: ReferenceDocumentKind = ReferenceDocumentKind.special_plan
    focus_terms: list[str] = Field(default_factory=list)
    max_batches: int | None = Field(default=None, ge=1)
    publish_for_validation: bool = False


class ReferenceMarkdownUploadRequest(BaseModel):
    file_name: str
    content: str
    project_name: str
    project_type: str
    document_kind: ReferenceDocumentKind = ReferenceDocumentKind.construction_organization
    focus_terms: list[str] = Field(default_factory=list)
    max_batches: int | None = Field(default=3, ge=1, le=20)


class AtomStatusRequest(BaseModel):
    status: ReferenceReviewStatus


@router.get("/documents")
def list_reference_documents(request: Request):
    return [dump_model(item) for item in request.app.state.reference_library.list_documents()]


@router.get("/summary")
def reference_library_summary(request: Request):
    library = request.app.state.reference_library
    documents = library.list_documents()
    atoms = library.list_atoms()
    status_counts = {
        status.value: sum(atom.status == status for atom in atoms)
        for status in ReferenceReviewStatus
    }
    candidates = [
        {
            "atom_id": atom.id,
            "project_name": atom.project_name,
            "project_type": atom.project_type,
            "title_path": atom.title_path,
            "process": atom.process,
            "quality_score": atom.quality_score,
            "status": atom.status.value,
            "excerpt": atom.content[:220],
        }
        for atom in atoms
        if atom.status in {ReferenceReviewStatus.ai_candidate, ReferenceReviewStatus.reviewed}
    ][:60]
    return {
        "document_count": len(documents),
        "atom_count": len(atoms),
        "status_counts": status_counts,
        "published_count": status_counts[ReferenceReviewStatus.published.value],
        "candidate_count": len(candidates),
        "candidate_atoms": candidates,
        "workflow": ["上传优秀施组", "AI 自动切分与标注", "人工快速抽查", "发布后参与生成"],
        "message": (
            "已发布原子会参与章节匹配，候选原子不会自动进入生成。"
            if atoms
            else "参考库为空时不影响投标证据生成，可稍后逐步补充。"
        ),
    }


@router.get("/atoms")
def list_reference_atoms(
    request: Request,
    status: ReferenceReviewStatus | None = None,
    excluded_project: list[str] | None = None,
):
    atoms = request.app.state.reference_library.list_atoms(
        status=status,
        excluded_projects=excluded_project or [],
    )
    return [dump_model(item) for item in atoms]


@router.post("/import-ai")
def import_reference_document(payload: ReferenceImportRequest, request: Request):
    path = Path(payload.source_path).resolve()
    if not path.exists() or path.suffix.lower() != ".md":
        raise HTTPException(status_code=404, detail="Markdown source_path does not exist.")
    raw = path.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    document = ReferenceDocument(
        id=stable_id("refdoc", digest),
        content_hash=digest,
        source_path=str(path),
        file_name=path.name,
        project_name=payload.project_name,
        project_type=payload.project_type,
        document_kind=payload.document_kind,
    )
    library = request.app.state.reference_library
    library.save_document(document)
    try:
        result = atomize_reference_markdown(
            document=document,
            markdown=raw.decode("utf-8-sig", errors="replace"),
            llm=request.app.state.pipeline._structured_llm(),
            focus_terms=payload.focus_terms,
            max_batches=payload.max_batches,
            publish_for_validation=payload.publish_for_validation,
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"AI atomization failed: {exc}") from exc
    chapters = _chapters(document.id, result.blocks)
    library.replace_document_content(document.id, chapters=chapters, atoms=result.atoms)
    return {
        "document": dump_model(document),
        "block_count": len(result.blocks),
        "atom_count": len(result.atoms),
        "llm_call_count": result.llm_call_count,
        "failed_batch_count": result.failed_batch_count,
        "warnings": result.warnings or [],
        "published_count": sum(item.status == ReferenceReviewStatus.published for item in result.atoms),
    }


@router.post("/upload-markdown")
def upload_reference_markdown(payload: ReferenceMarkdownUploadRequest, request: Request):
    raw = payload.content.encode("utf-8")
    digest = hashlib.sha256(raw).hexdigest()
    document_id = stable_id("refdoc", digest)
    source_path = request.app.state.pipeline.artifacts.write_text(
        "reference-library",
        f"sources/{document_id}/{Path(payload.file_name).name}",
        payload.content,
    )
    document = ReferenceDocument(
        id=document_id,
        content_hash=digest,
        source_path=source_path,
        file_name=Path(payload.file_name).name,
        project_name=payload.project_name,
        project_type=payload.project_type,
        document_kind=payload.document_kind,
    )
    library = request.app.state.reference_library
    library.save_document(document)
    try:
        result = atomize_reference_markdown(
            document=document,
            markdown=payload.content,
            llm=request.app.state.pipeline._structured_llm(),
            focus_terms=payload.focus_terms,
            max_batches=payload.max_batches,
            publish_for_validation=False,
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"AI atomization failed: {exc}") from exc
    library.replace_document_content(document.id, chapters=_chapters(document.id, result.blocks), atoms=result.atoms)
    processing_status = "success" if not result.failed_batch_count else ("partial" if result.atoms else "failed")
    if processing_status == "success":
        user_message = f"已生成 {len(result.atoms)} 条候选原子，可开始抽查。"
    elif processing_status == "partial":
        user_message = f"部分批次未完成，已保留 {len(result.atoms)} 条成功候选，可先抽查或稍后重新上传。"
    else:
        user_message = "文档已保存，但本次 AI 切分未产出候选。可以重新上传，其他项目资料不受影响。"
    return {
        "document": dump_model(document),
        "block_count": len(result.blocks),
        "atom_count": len(result.atoms),
        "llm_call_count": result.llm_call_count,
        "failed_batch_count": result.failed_batch_count,
        "warnings": result.warnings or [],
        "processing_status": processing_status,
        "user_message": user_message,
        "candidate_count": sum(item.status == ReferenceReviewStatus.ai_candidate for item in result.atoms),
        "next_step": "抽查候选原子的标题、工艺标签和正文后，发布可复用内容。",
    }


@router.patch("/atoms/{atom_id}/status")
def set_reference_atom_status(atom_id: str, payload: AtomStatusRequest, request: Request):
    try:
        atom = request.app.state.reference_library.set_atom_status(atom_id, payload.status)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return dump_model(atom)


@router.post("/retrieve")
def retrieve_atoms(payload: AtomRetrievalQuery, request: Request):
    atoms = request.app.state.reference_library.list_atoms()
    try:
        results = retrieve_reference_atoms(atoms=atoms, query=payload, llm=request.app.state.pipeline._structured_llm())
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"AI atom rerank failed: {exc}") from exc
    return [dump_model(item) for item in results]


@router.get("/usage/{project_id}")
def list_atom_usage(project_id: str, request: Request, node_id: str | None = None):
    return request.app.state.reference_library.list_usage(project_id, node_id)


def _chapters(document_id: str, blocks) -> list[ReferenceChapter]:
    ranges: dict[tuple[str, ...], tuple[int, int]] = {}
    for block in blocks:
        key = tuple(block.title_path)
        if not key:
            continue
        start, end = ranges.get(key, (block.start_line, block.end_line))
        ranges[key] = (min(start, block.start_line), max(end, block.end_line))
    return [
        ReferenceChapter(
            id=stable_id("refchapter", f"{document_id}:{' > '.join(path)}"),
            document_id=document_id,
            title_path=list(path),
            start_line=line_range[0],
            end_line=line_range[1],
            sort_order=index,
        )
        for index, (path, line_range) in enumerate(ranges.items(), start=1)
    ]
