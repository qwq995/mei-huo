from __future__ import annotations

import hashlib
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from coalplan.application.reference_atom_retrieval import retrieve_reference_atoms
from coalplan.application.reference_atomization import atomize_reference_markdown
from coalplan.application.reference_import_service import process_reference_markdown
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


class ReferenceDocumentUpdateRequest(BaseModel):
    project_name: str | None = None
    project_type: str | None = None
    document_kind: ReferenceDocumentKind | None = None


class ReferenceAtomUpdateRequest(BaseModel):
    content: str | None = None
    title_path: list[str] | None = None
    engineering_object: str | None = None
    specialty: str | None = None
    work_item: str | None = None
    process: str | None = None
    process_stage: str | None = None
    chapter_type: str | None = None
    applicability: list[str] | None = None
    prohibited_scenarios: list[str] | None = None
    quality_score: float | None = Field(default=None, ge=0, le=1)
    confidence: float | None = Field(default=None, ge=0, le=1)


@router.get("/documents")
def list_reference_documents(request: Request):
    return [dump_model(item) for item in request.app.state.reference_library.list_documents()]


@router.patch("/documents/{document_id}")
def update_reference_document(document_id: str, payload: ReferenceDocumentUpdateRequest, request: Request):
    try:
        document = request.app.state.reference_library.get_document(document_id)
        for key, value in payload.model_dump(exclude_unset=True).items():
            setattr(document, key, value)
        return dump_model(request.app.state.reference_library.update_document(document))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.delete("/documents/{document_id}")
def delete_reference_document(document_id: str, request: Request):
    try:
        request.app.state.reference_library.delete_document(document_id)
        return {"deleted": True, "document_id": document_id}
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


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


@router.get("/management")
def reference_library_management(request: Request):
    """Return reference documents and atoms for the management console."""
    library = request.app.state.reference_library
    documents = library.list_documents()
    atoms = library.list_atoms()
    counts: dict[str, dict[str, int]] = {}
    for atom in atoms:
        item = counts.setdefault(atom.document_id, {"total": 0, "published": 0, "candidate": 0, "rejected": 0})
        item["total"] += 1
        status = atom.status.value if hasattr(atom.status, "value") else str(atom.status)
        if status == "published":
            item["published"] += 1
        elif status == "rejected":
            item["rejected"] += 1
        else:
            item["candidate"] += 1
    return {
        "documents": [
            {
                **dump_model(document),
                "atom_counts": counts.get(document.id, {"total": 0, "published": 0, "candidate": 0, "rejected": 0}),
            }
            for document in documents
        ],
        "atoms": [dump_model(atom) for atom in atoms],
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
    try:
        return process_reference_markdown(
            pipeline=request.app.state.pipeline,
            library=request.app.state.reference_library,
            payload=payload.model_dump(mode="json"),
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"AI atomization failed: {exc}") from exc


@router.patch("/atoms/{atom_id}/status")
def set_reference_atom_status(atom_id: str, payload: AtomStatusRequest, request: Request):
    try:
        atom = request.app.state.reference_library.set_atom_status(atom_id, payload.status)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return dump_model(atom)


@router.patch("/atoms/{atom_id}")
def update_reference_atom(atom_id: str, payload: ReferenceAtomUpdateRequest, request: Request):
    try:
        atom = request.app.state.reference_library.get_atom(atom_id)
        for key, value in payload.model_dump(exclude_unset=True).items():
            setattr(atom, key, value)
        return dump_model(request.app.state.reference_library.update_atom(atom))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


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
