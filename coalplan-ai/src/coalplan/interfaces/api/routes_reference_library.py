from __future__ import annotations

import hashlib
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from coalplan.application.reference_atom_retrieval import retrieve_reference_atoms
from coalplan.application.hybrid_atom_retrieval import build_query_text, hybrid_prefilter_atoms, query_filters
from coalplan.application.reference_atom_v2 import evaluate_publication_gate, finalize_v2_atom
from coalplan.application.reference_atom_query import classify_atom_retrieval_query
from coalplan.application.reference_atomization import atomize_reference_markdown
from coalplan.application.reference_atomization_v2 import atomize_reference_markdown_v2
from coalplan.application.reference_atomization_v2 import load_reference_taxonomy
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


class AtomBulkPublishRequest(BaseModel):
    atom_ids: list[str] = Field(min_length=1, max_length=500)


class ReferenceDocumentUpdateRequest(BaseModel):
    project_name: str | None = None
    project_type: str | None = None
    document_kind: ReferenceDocumentKind | None = None


class ReferenceAtomUpdateRequest(BaseModel):
    content: str | None = None
    title_path: list[str] | None = None
    engineering_object: str | None = None
    engineering_system: str | None = None
    specialty: str | None = None
    work_item: str | None = None
    process: str | None = None
    process_family: str | None = None
    process_method: str | None = None
    process_stage: str | None = None
    chapter_type: str | None = None
    chapter_module: str | None = None
    atom_type: str | None = None
    content_functions: list[str] | None = None
    action_sequence: list[str] | None = None
    control_points: list[str] | None = None
    acceptance_checks: list[str] | None = None
    exceptions: list[str] | None = None
    risks: list[str] | None = None
    applicability: list[str] | None = None
    prohibited_scenarios: list[str] | None = None
    quality_score: float | None = Field(default=None, ge=0, le=1)
    confidence: float | None = Field(default=None, ge=0, le=1)


@router.get("/documents")
def list_reference_documents(request: Request):
    return [dump_model(item) for item in request.app.state.reference_library.list_documents()]


@router.get("/taxonomy-v2")
def get_reference_taxonomy_v2():
    """Expose controlled IDs and Chinese labels for management clients."""
    return load_reference_taxonomy()


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
        library = request.app.state.reference_library
        atom_ids = library.list_document_atom_ids(document_id) if hasattr(library, "list_document_atom_ids") else []
        library.delete_document(document_id)
        vector_index = getattr(request.app.state, "reference_vector_index", None)
        if vector_index is not None and atom_ids and hasattr(vector_index, "delete"):
            vector_index.delete(atom_ids)
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


@router.get("/atoms/search")
def search_reference_atoms(
    request: Request,
    query: str = "",
    status: ReferenceReviewStatus | None = None,
    document_id: str = "",
    chapter_module: str = "",
    engineering_system: str = "",
    process_family: str = "",
    page: int = 1,
    page_size: int = 30,
):
    """Paged management view; generation retrieval remains a separate API."""
    page = max(1, page)
    page_size = max(1, min(page_size, 100))
    atoms, total = request.app.state.reference_library.search_atoms_page(
        query=query, status=status, document_id=document_id,
        chapter_module=chapter_module, engineering_system=engineering_system,
        process_family=process_family, page=page, page_size=page_size,
    )
    start = (page - 1) * page_size
    return {
        "items": [dump_model(atom) for atom in atoms],
        "total": total,
        "page": page,
        "page_size": page_size,
        "has_more": start + page_size < total,
    }


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


@router.post("/import-ai-v2")
def import_reference_document_v2(payload: ReferenceImportRequest, request: Request):
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
        result = atomize_reference_markdown_v2(
            document=document,
            markdown=raw.decode("utf-8-sig", errors="replace"),
            llm=request.app.state.pipeline._structured_llm(),
            max_batches=payload.max_batches,
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"V2 AI atomization failed: {exc}") from exc
    chapters = _chapters(document.id, result.segments)
    library.replace_document_content(document.id, chapters=chapters, atoms=result.atoms)
    return {
        "document": dump_model(document),
        "segment_count": len(result.segments),
        "atom_count": len(result.atoms),
        "pending_publish_count": sum(item.status == ReferenceReviewStatus.pending_publish for item in result.atoms),
        "blocked_count": sum(bool(item.publication_blockers) for item in result.atoms),
        "excluded_segments": result.excluded_segments,
        "llm_call_count": result.llm_call_count,
        "failed_batches": result.failed_batches,
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
        current = request.app.state.reference_library.get_atom(atom_id)
        if payload.status == ReferenceReviewStatus.published and current.schema_version == "v2":
            gate = evaluate_publication_gate(current)
            if not gate.allowed:
                raise HTTPException(status_code=409, detail={"message": "原子未通过发布门禁", "blockers": gate.blockers})
        atom = request.app.state.reference_library.set_atom_status(atom_id, payload.status)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    vector_index = getattr(request.app.state, "reference_vector_index", None)
    if vector_index is not None and payload.status == ReferenceReviewStatus.published:
        vector_index.upsert([atom])
    elif vector_index is not None and hasattr(vector_index, "delete"):
        vector_index.delete([atom.id])
    return dump_model(atom)


@router.post("/atoms/bulk-publish")
def bulk_publish_reference_atoms(payload: AtomBulkPublishRequest, request: Request):
    publishable: list[str] = []
    blocked: list[dict] = []
    atoms = request.app.state.reference_library.get_atoms(payload.atom_ids)
    atom_by_id = {atom.id: atom for atom in atoms}
    missing = [atom_id for atom_id in dict.fromkeys(payload.atom_ids) if atom_id not in atom_by_id]
    for atom_id in payload.atom_ids:
        atom = atom_by_id.get(atom_id)
        if atom is None:
            continue
        gate = evaluate_publication_gate(atom)
        if atom.schema_version != "v2" or not gate.allowed:
            blocked.append({"atom_id": atom_id, "blockers": gate.blockers or ["仅允许通过 V2 门禁的原子批量发布"]})
            continue
        publishable.append(atom_id)
    published_atoms = request.app.state.reference_library.set_atom_statuses(
        publishable,
        ReferenceReviewStatus.published,
    )
    published = [atom.id for atom in published_atoms]
    vector_index = getattr(request.app.state, "reference_vector_index", None)
    if vector_index is not None and published_atoms:
        vector_index.upsert(published_atoms)
    return {"published": published, "blocked": blocked, "missing": missing}


@router.patch("/atoms/{atom_id}")
def update_reference_atom(atom_id: str, payload: ReferenceAtomUpdateRequest, request: Request):
    try:
        atom = request.app.state.reference_library.get_atom(atom_id)
        for key, value in payload.model_dump(exclude_unset=True).items():
            setattr(atom, key, value)
        if atom.schema_version == "v2":
            if payload.content is not None:
                atom.raw_excerpt = payload.content
                atom.normalized_text = payload.content
            atom = finalize_v2_atom(atom)
        updated = request.app.state.reference_library.update_atom(atom)
        vector_index = getattr(request.app.state, "reference_vector_index", None)
        if (
            vector_index is not None
            and updated.status == ReferenceReviewStatus.published
            and not updated.publication_blockers
        ):
            vector_index.upsert([updated])
        elif vector_index is not None and hasattr(vector_index, "delete"):
            vector_index.delete([updated.id])
        return dump_model(updated)
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


@router.post("/retrieve-v2")
def retrieve_atoms_v2(payload: AtomRetrievalQuery, request: Request):
    library = request.app.state.reference_library
    vector_index = getattr(request.app.state, "reference_vector_index", None)
    vector_results = []
    limit = max(12, payload.top_k * 4)
    if vector_index is not None:
        vector_results = vector_index.search(
            build_query_text(payload), limit=limit, filters=query_filters(payload),
        )
    if hasattr(library, "list_v2_retrieval_candidates"):
        atoms = library.list_v2_retrieval_candidates(payload, limit=max(100, payload.top_k * 20))
        loaded = {atom.id for atom in atoms}
        missing_ids = [atom_id for atom_id, _ in vector_results if atom_id not in loaded]
        if missing_ids and hasattr(library, "get_atoms"):
            atoms.extend(library.get_atoms(missing_ids))
    else:
        atoms = library.list_atoms()
    candidates = hybrid_prefilter_atoms(
        atoms,
        payload,
        vector_results=vector_results,
        limit=limit,
    )
    return [
        {
            "atom": dump_model(item.atom),
            "score": round(item.score, 6),
            "lexical_rank": item.lexical_rank,
            "vector_rank": item.vector_rank,
            "tag_score": item.tag_score,
            "match_reasons": item.match_reasons,
        }
        for item in candidates[: payload.top_k]
    ]


@router.post("/classify-query-v2")
def classify_retrieval_query_v2(payload: AtomRetrievalQuery, request: Request):
    try:
        result = classify_atom_retrieval_query(
            payload,
            llm=request.app.state.pipeline._structured_llm(),
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"AI retrieval query classification failed: {exc}") from exc
    return {
        "query": dump_model(result.query),
        "confidence": result.confidence,
        "reason": result.reason,
    }


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
