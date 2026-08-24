from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from coalplan.application.compliance_review import (
    ai_repair_finding,
    match_constraints,
    match_standard_documents,
    run_compliance_review,
    recheck_finding,
    selected_review_chapters,
)
from coalplan.application.serialization import dump_model
from coalplan.application.standard_constraint_extraction import classify_standard_sources, extract_standard_constraints
from coalplan.domain.standard_constraints import ConstraintReviewStatus, FindingStatus, StandardDocumentStatus


router = APIRouter(prefix="/standards", tags=["standard-constraints"])


class StandardImportRequest(BaseModel):
    file_name: str
    content: str = ""
    source_path: str = ""
    max_batches: int | None = Field(default=None, ge=1, le=100)


class StandardBatchFile(BaseModel):
    file_name: str
    content: str


class StandardBatchImportRequest(BaseModel):
    files: list[StandardBatchFile] = Field(min_length=1, max_length=100)
    max_batches_per_document: int | None = Field(default=None, ge=1, le=100)


class StandardBatchClassifyRequest(BaseModel):
    document_ids: list[str] = Field(default_factory=list, max_length=100)


class StatusRequest(BaseModel):
    status: str


class MatchDecisionRequest(BaseModel):
    decision: str


class FindingResolutionRequest(BaseModel):
    status: FindingStatus
    note: str = ""


@router.get("/summary")
def standard_summary(request: Request):
    repository = request.app.state.standard_constraints
    documents = repository.list_documents()
    atoms = repository.list_atoms()
    return {
        "document_count": len(documents),
        "ready_document_count": sum(item.status in {StandardDocumentStatus.ready, StandardDocumentStatus.partial} for item in documents),
        "constraint_count": len(atoms),
        "published_constraint_count": sum(item.status == ConstraintReviewStatus.published for item in atoms),
        "categories": sorted({item.category for item in documents}),
        "message": "规范只参与最终成稿审查，不会改变目录或生成正文。",
    }


@router.get("/documents")
def list_standard_documents(request: Request, category: str | None = None):
    return [dump_model(item) for item in request.app.state.standard_constraints.list_documents(category=category)]


@router.get("/documents/{document_id}/constraints")
def list_document_constraints(document_id: str, request: Request, status: ConstraintReviewStatus | None = None):
    try:
        request.app.state.standard_constraints.get_document(document_id)
        return [dump_model(item) for item in request.app.state.standard_constraints.list_atoms(document_id=document_id, status=status)]
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/import-markdown")
def import_standard_markdown(payload: StandardImportRequest, request: Request):
    try:
        source_path = payload.source_path or request.app.state.pipeline.artifacts.write_text(
            "_standard_library", f"sources/{_safe_name(payload.file_name)}", payload.content,
        )
        result = extract_standard_constraints(
            file_name=payload.file_name,
            markdown=payload.content,
            source_path=source_path,
            llm=request.app.state.pipeline._structured_llm(),
            max_batches=payload.max_batches,
        )
        repository = request.app.state.standard_constraints
        repository.save_document(result.document)
        repository.replace_atoms(result.document.id, result.atoms)
        return {
            "document": dump_model(result.document),
            "block_count": result.block_count,
            "constraint_count": len(result.atoms),
            "published_count": sum(item.status == ConstraintReviewStatus.published for item in result.atoms),
            "llm_call_count": result.llm_call_count,
            "failed_batch_count": result.failed_batch_count,
            "warnings": result.warnings,
        }
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"规范约束提取失败：{exc}") from exc


@router.post("/import-batch")
def import_standard_batch(payload: StandardBatchImportRequest, request: Request):
    pipeline = request.app.state.pipeline
    repository = request.app.state.standard_constraints
    sources = [
        {"source_id": f"source_{index}", "file_name": item.file_name, "markdown": item.content}
        for index, item in enumerate(payload.files, start=1)
    ]
    try:
        classifications = classify_standard_sources(sources=sources, llm=pipeline._structured_llm())
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"规范批量分类失败：{exc}") from exc
    results = []
    for source, item in zip(sources, payload.files):
        try:
            source_path = pipeline.artifacts.write_text(
                "_standard_library", f"sources/{source['source_id']}_{_safe_name(item.file_name)}", item.content,
            )
            result = extract_standard_constraints(
                file_name=item.file_name,
                markdown=item.content,
                source_path=source_path,
                llm=pipeline._structured_llm(),
                max_batches=payload.max_batches_per_document,
                metadata=classifications[source["source_id"]],
            )
            repository.save_document(result.document)
            repository.replace_atoms(result.document.id, result.atoms)
            item_status = (
                "failed" if result.document.status == StandardDocumentStatus.failed
                else "partial" if result.document.status == StandardDocumentStatus.partial
                else "completed"
            )
            results.append({
                "file_name": item.file_name,
                "status": item_status,
                "document": dump_model(result.document),
                "constraint_count": len(result.atoms),
                "published_count": sum(atom.status == ConstraintReviewStatus.published for atom in result.atoms),
                "llm_call_count": result.llm_call_count,
                "failed_batch_count": result.failed_batch_count,
                "warnings": result.warnings,
            })
        except Exception as exc:
            results.append({"file_name": item.file_name, "status": "failed", "error": str(exc)})
    completed = sum(item["status"] in {"completed", "partial"} for item in results)
    return {
        "document_count": len(results),
        "completed_count": completed,
        "failed_count": len(results) - completed,
        "classification_batch_count": (len(sources) + 9) // 10,
        "results": results,
    }


@router.post("/import-path")
def import_standard_path(payload: StandardImportRequest, request: Request):
    path = Path(payload.source_path).resolve()
    if not path.is_file() or path.suffix.lower() != ".md":
        raise HTTPException(status_code=404, detail="指定的 Markdown 文件不存在。")
    payload.file_name = path.name
    payload.content = path.read_text(encoding="utf-8-sig", errors="replace")
    return import_standard_markdown(payload, request)


@router.post("/classify-batch")
def classify_existing_standards(payload: StandardBatchClassifyRequest, request: Request):
    repository = request.app.state.standard_constraints
    documents = repository.list_documents()
    if payload.document_ids:
        requested = set(payload.document_ids)
        documents = [item for item in documents if item.id in requested]
    if not documents:
        return {"document_count": 0, "classification_batch_count": 0, "documents": [], "warnings": []}
    sources = []
    warnings = []
    by_source_id = {}
    for document in documents:
        path = Path(document.source_path)
        if not path.is_file():
            warnings.append(f"{document.standard_code or document.name} 缺少可读取的原始 Markdown，已跳过。")
            continue
        source_id = document.id
        sources.append({"source_id": source_id, "file_name": document.file_name, "markdown": path.read_text(encoding="utf-8-sig", errors="replace")})
        by_source_id[source_id] = document
    classifications = classify_standard_sources(sources=sources, llm=request.app.state.pipeline._structured_llm())
    updated = []
    for source_id, metadata in classifications.items():
        document = by_source_id[source_id].model_copy(update={
            "standard_code": metadata["standard_code"],
            "name": metadata["name"],
            "category": metadata["category"],
            "disciplines": metadata["disciplines"],
            "project_types": metadata["project_types"],
        })
        repository.save_document(document)
        updated.append(dump_model(document))
        if metadata.get("classification_warning"):
            warnings.append(str(metadata["classification_warning"]))
    return {
        "document_count": len(updated),
        "classification_batch_count": (len(sources) + 9) // 10,
        "documents": updated,
        "warnings": warnings,
    }


@router.patch("/documents/{document_id}/status")
def update_standard_document_status(document_id: str, payload: StatusRequest, request: Request):
    if payload.status not in {item.value for item in StandardDocumentStatus}:
        raise HTTPException(status_code=400, detail="不支持的规范文档状态。")
    try:
        return dump_model(request.app.state.standard_constraints.set_document_status(document_id, payload.status))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.patch("/constraints/{atom_id}/status")
def update_constraint_status(atom_id: str, payload: StatusRequest, request: Request):
    try:
        status = ConstraintReviewStatus(payload.status)
        return dump_model(request.app.state.standard_constraints.set_atom_status(atom_id, status))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="不支持的约束状态。") from exc
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/projects/{project_id}/match")
def match_project_standards(project_id: str, request: Request):
    pipeline = request.app.state.pipeline
    repository = request.app.state.standard_constraints
    try:
        project = pipeline.projects.get(project_id)
        nodes = pipeline.workspace_store.list_outline_nodes(project_id)
        context = "\n".join([project.name, project.template_id, *[item["title"] for item in nodes]])
        documents = repository.list_documents()
        existing = repository.list_project_matches(project_id)
        candidate_documents = repository.search_document_candidates(
            context,
            include_document_ids={item.document_id for item in existing if item.decision == "selected"},
        ) if hasattr(repository, "search_document_candidates") else None
        matches = match_standard_documents(
            documents=documents,
            project_text=context,
            llm=pipeline._structured_llm(),
            existing_matches=existing,
            candidate_documents=candidate_documents,
        )
        repository.replace_project_matches(project_id, matches)
        documents = {item.id: item for item in repository.list_documents()}
        return [{**dump_model(item), "document": dump_model(documents[item.document_id])} for item in matches]
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.patch("/projects/{project_id}/matches/{document_id}")
def update_project_standard_match(project_id: str, document_id: str, payload: MatchDecisionRequest, request: Request):
    if payload.decision not in {"selected", "suggested", "excluded"}:
        raise HTTPException(status_code=400, detail="不支持的匹配决策。")
    return dump_model(request.app.state.standard_constraints.set_project_match_decision(project_id, document_id, payload.decision))


@router.post("/projects/{project_id}/review")
def review_project(project_id: str, request: Request):
    try:
        return run_compliance_review(project_id=project_id, pipeline=request.app.state.pipeline, repository=request.app.state.standard_constraints)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/projects/{project_id}/chapters/{node_id}/constraint-matches")
def preview_chapter_constraint_matches(project_id: str, node_id: str, request: Request):
    pipeline = request.app.state.pipeline
    repository = request.app.state.standard_constraints
    try:
        chapter = next((item for item in selected_review_chapters(project_id, pipeline.workspace_store) if item.node_id == node_id), None)
        if chapter is None:
            raise KeyError("该章节没有已选用版本。")
        selected_documents = {item.document_id for item in repository.list_project_matches(project_id) if item.decision == "selected"}
        atoms = [
            atom for atom in repository.list_atoms(status=ConstraintReviewStatus.published)
            if atom.document_id in selected_documents
        ]
        candidate_atoms = repository.search_constraint_candidates(
            f"{chapter.title}\n{chapter.markdown[:12000]}", selected_documents,
        ) if hasattr(repository, "search_constraint_candidates") else None
        if candidate_atoms is None:
            candidate_atoms = atoms
        warnings: list[str] = []
        matches = match_constraints(
            atoms=atoms,
            candidate_atoms=candidate_atoms,
            chapter=chapter,
            llm=pipeline._structured_llm(),
            warnings=warnings,
        )
        return {
            "project_id": project_id,
            "node_id": node_id,
            "chapter_version_id": chapter.version_id,
            "selected_document_count": len(selected_documents),
            "candidate_constraint_count": len(atoms),
            "matches": [
                {"atom": dump_model(atom), "score": score, "match_reason": reason}
                for atom, score, reason in matches
            ],
            "warnings": warnings,
        }
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/projects/{project_id}/review-runs")
def list_compliance_review_runs(project_id: str, request: Request, limit: int = 20):
    return [dump_model(item) for item in request.app.state.standard_constraints.list_review_runs(project_id, limit=min(max(limit, 1), 100))]


@router.get("/projects/{project_id}/review-runs/{run_id}")
def get_compliance_review_run(project_id: str, run_id: str, request: Request):
    try:
        repository = request.app.state.standard_constraints
        run = repository.get_review_run(project_id, run_id)
        matches = repository.list_constraint_matches(project_id, run_id)
        findings = repository.list_findings(project_id, run_id=run_id)
        return {"run": dump_model(run), "constraint_matches": [dump_model(item) for item in matches], "findings": [dump_model(item) for item in findings]}
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/projects/{project_id}/findings")
def list_compliance_findings(project_id: str, request: Request, status: FindingStatus | None = None, run_id: str | None = None):
    return [dump_model(item) for item in request.app.state.standard_constraints.list_findings(project_id, status=status, run_id=run_id)]


@router.post("/projects/{project_id}/findings/{finding_id}/ai-fix")
def fix_compliance_finding(project_id: str, finding_id: str, request: Request):
    try:
        return ai_repair_finding(project_id=project_id, finding_id=finding_id, pipeline=request.app.state.pipeline, repository=request.app.state.standard_constraints)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/projects/{project_id}/findings/{finding_id}/recheck")
def recheck_compliance_finding(project_id: str, finding_id: str, request: Request):
    try:
        return recheck_finding(project_id=project_id, finding_id=finding_id, pipeline=request.app.state.pipeline, repository=request.app.state.standard_constraints)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.patch("/projects/{project_id}/findings/{finding_id}")
def resolve_compliance_finding(project_id: str, finding_id: str, payload: FindingResolutionRequest, request: Request):
    try:
        return dump_model(request.app.state.standard_constraints.resolve_finding(project_id, finding_id, status=payload.status, note=payload.note))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


def _safe_name(value: str) -> str:
    cleaned = "".join(char if char.isalnum() or char in "._-" else "_" for char in value).strip("._")
    return cleaned[:160] or "standard.md"
