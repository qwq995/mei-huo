from __future__ import annotations

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile

from .schemas import (
    AIEditProposalRequest,
    ManualVersionRequest,
    OutlineAIProposalRequest,
    OutlineNodeCreateRequest,
    OutlineNodeUpdateRequest,
    SelectVersionRequest,
    SupplementRequest,
)

router = APIRouter(tags=["workspace"])


@router.get("/projects/{project_id}/outline-nodes")
def list_outline_nodes(project_id: str, request: Request):
    try:
        return request.app.state.workspace_store.list_outline_nodes(project_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/projects/{project_id}/outline-nodes")
def create_outline_node(project_id: str, payload: OutlineNodeCreateRequest, request: Request):
    try:
        return request.app.state.workspace_store.create_outline_node(project_id, payload.model_dump(exclude_none=True))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.patch("/projects/{project_id}/outline-nodes/{node_id}")
def update_outline_node(project_id: str, node_id: str, payload: OutlineNodeUpdateRequest, request: Request):
    try:
        return request.app.state.workspace_store.update_outline_node(project_id, node_id, payload.model_dump(exclude_unset=True))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.delete("/projects/{project_id}/outline-nodes/{node_id}")
def delete_outline_node(project_id: str, node_id: str, request: Request):
    try:
        request.app.state.workspace_store.delete_outline_node(project_id, node_id)
        return {"deleted": True}
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/projects/{project_id}/outline/propose-ai-change")
def propose_outline_change(project_id: str, payload: OutlineAIProposalRequest, request: Request):
    try:
        preview_nodes = payload.preview_nodes if payload.preview_nodes is not None else request.app.state.workspace_store.list_outline_nodes(project_id)
        return request.app.state.workspace_store.propose_outline_change(project_id, payload.suggestion, preview_nodes)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/projects/{project_id}/outline/ai-plan")
def propose_ai_outline_plan(project_id: str, payload: OutlineAIProposalRequest, request: Request):
    try:
        return request.app.state.pipeline.propose_ai_outline(project_id, payload.suggestion)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/projects/{project_id}/outline/proposals/{proposal_id}/apply")
def apply_outline_proposal(project_id: str, proposal_id: str, request: Request):
    try:
        return request.app.state.workspace_store.apply_proposal(project_id, proposal_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/projects/{project_id}/chapters/{node_id}/workspace")
def get_chapter_workspace(project_id: str, node_id: str, request: Request):
    try:
        return request.app.state.workspace_store.get_workspace(project_id, node_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/projects/{project_id}/chapters/{node_id}/supplements")
def add_supplement(project_id: str, node_id: str, payload: SupplementRequest, request: Request):
    try:
        return request.app.state.workspace_store.add_supplement(project_id, node_id, payload.model_dump(exclude_none=True))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.patch("/projects/{project_id}/chapters/{node_id}/supplements/{supplement_id}")
def update_supplement(project_id: str, node_id: str, supplement_id: str, payload: SupplementRequest, request: Request):
    try:
        return request.app.state.workspace_store.update_supplement(project_id, node_id, supplement_id, payload.model_dump(exclude_unset=True))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.delete("/projects/{project_id}/chapters/{node_id}/supplements/{supplement_id}")
def delete_supplement(project_id: str, node_id: str, supplement_id: str, request: Request):
    try:
        request.app.state.workspace_store.delete_supplement(project_id, node_id, supplement_id)
        return {"deleted": True}
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/projects/{project_id}/chapters/{node_id}/attachments")
async def add_attachment(
    project_id: str,
    node_id: str,
    request: Request,
    file: UploadFile = File(...),
    description: str = Form(default=""),
):
    try:
        content = await file.read()
        return request.app.state.workspace_store.add_attachment(
            project_id,
            node_id,
            file_name=file.filename or "attachment",
            content_type=file.content_type or "application/octet-stream",
            content=content,
            description=description,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.delete("/projects/{project_id}/chapters/{node_id}/attachments/{attachment_id}")
def delete_attachment(project_id: str, node_id: str, attachment_id: str, request: Request):
    try:
        request.app.state.workspace_store.delete_attachment(project_id, node_id, attachment_id)
        return {"deleted": True}
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/projects/{project_id}/chapters/{node_id}/versions")
def create_manual_version(project_id: str, node_id: str, payload: ManualVersionRequest, request: Request):
    try:
        return request.app.state.workspace_store.create_chapter_version(
            project_id,
            node_id,
            title=payload.title,
            markdown=payload.markdown,
            source_type="manual_edit",
            created_by="user",
            select=payload.select,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/projects/{project_id}/chapters/{node_id}/versions")
def list_versions(project_id: str, node_id: str, request: Request):
    try:
        return request.app.state.workspace_store.list_versions(project_id, node_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/projects/{project_id}/chapters/{node_id}/versions/{version_id}")
def get_version(project_id: str, node_id: str, version_id: str, request: Request):
    try:
        return request.app.state.workspace_store.get_version(project_id, node_id, version_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.patch("/projects/{project_id}/chapters/{node_id}/selected-version")
def select_version(project_id: str, node_id: str, payload: SelectVersionRequest, request: Request):
    try:
        return request.app.state.workspace_store.select_version(project_id, node_id, payload.version_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/projects/{project_id}/chapters/{node_id}/propose-ai-edit")
def propose_chapter_edit(project_id: str, node_id: str, payload: AIEditProposalRequest, request: Request):
    try:
        base = payload.base_markdown
        if base is None:
            workspace = request.app.state.workspace_store.get_workspace(project_id, node_id)
            selected = next((item for item in workspace["versions"] if item["id"] == workspace["selected_version_id"]), None)
            base = selected["markdown"] if selected else ""
        prompt = "\n".join(
            [
                "你是施工组织设计章节修改助手。只输出修改后的 Markdown，不要解释。",
                f"修改建议：{payload.suggestion}",
                "原文：",
                base,
            ]
        )
        preview = request.app.state.pipeline.llm.complete(prompt)
        return request.app.state.workspace_store.propose_chapter_edit(project_id, node_id, payload.suggestion, preview)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/projects/{project_id}/chapters/{node_id}/proposals/{proposal_id}/apply")
def apply_chapter_proposal(project_id: str, node_id: str, proposal_id: str, request: Request):
    try:
        return request.app.state.workspace_store.apply_proposal(project_id, proposal_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
