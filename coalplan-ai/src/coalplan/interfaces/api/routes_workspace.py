from __future__ import annotations

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile

from coalplan.interfaces.api.execution_window_guard import ensure_generation_window

from .schemas import (
    AIEditProposalRequest,
    ContentNodeUpdateRequest,
    ManualVersionRequest,
    OutlineAIProposalRequest,
    OutlineNodeCreateRequest,
    OutlineNodeUpdateRequest,
    PreGenerationOutlineRefineRequest,
    RevisionActionRequest,
    SelectVersionRequest,
    SupplementRequest,
    WordCountEstimateRequest,
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


@router.post("/projects/{project_id}/outline/control-plan-proposal")
def propose_control_plan_outline_repair(project_id: str, request: Request):
    try:
        return request.app.state.pipeline.propose_control_outline_repair(project_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/projects/{project_id}/outline/pre-generation-refine")
def propose_pre_generation_outline_refine(project_id: str, payload: PreGenerationOutlineRefineRequest, request: Request):
    try:
        return request.app.state.pipeline.propose_pre_generation_outline_refine(
            project_id,
            mode=payload.mode,
            use_local_corpus=payload.use_local_corpus,
            use_human_reference=payload.use_human_reference,
            human_reference_markdown=payload.human_reference_markdown,
            project_type=payload.project_type,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/projects/{project_id}/outline/word-counts/estimate")
def estimate_outline_word_counts(project_id: str, payload: WordCountEstimateRequest, request: Request):
    try:
        return request.app.state.pipeline.estimate_outline_word_counts(project_id, payload.reference_markdown)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/projects/{project_id}/outline/proposals/{proposal_id}/apply")
def apply_outline_proposal(project_id: str, proposal_id: str, request: Request):
    try:
        result = request.app.state.workspace_store.apply_proposal(project_id, proposal_id)
        pipeline = getattr(request.app.state, "pipeline", None)
        if pipeline is not None:
            try:
                run = pipeline.sync_generation_tasks(project_id)
                result["chapter_task_count"] = len(run.chapter_tasks) if run else 0
            except Exception as exc:
                result["task_sync_warning"] = str(exc)
        return result
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/projects/{project_id}/outline/proposals/{proposal_id}/reject")
def reject_outline_proposal(project_id: str, proposal_id: str, request: Request):
    try:
        return request.app.state.workspace_store.reject_proposal(
            project_id,
            proposal_id,
            target_type="outline",
            target_id=project_id,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


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


@router.get("/projects/{project_id}/chapters/{node_id}/versions/{version_id}/content-tree")
def get_version_content_tree(project_id: str, node_id: str, version_id: str, request: Request):
    try:
        return request.app.state.workspace_store.get_version_content_tree(project_id, node_id, version_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/projects/{project_id}/chapters/{node_id}/versions/{version_id}/content-revision-plan")
def get_version_content_revision_plan(project_id: str, node_id: str, version_id: str, request: Request):
    try:
        return request.app.state.workspace_store.get_version_content_revision_plan(project_id, node_id, version_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/projects/{project_id}/chapters/{node_id}/versions/{version_id}/generation-metadata")
def get_version_generation_metadata(project_id: str, node_id: str, version_id: str, request: Request):
    try:
        return request.app.state.workspace_store.get_version_generation_metadata(project_id, node_id, version_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/projects/{project_id}/chapters/{node_id}/versions/{version_id}/evidence-audit")
def get_version_evidence_audit(project_id: str, node_id: str, version_id: str, request: Request):
    try:
        return request.app.state.workspace_store.get_version_evidence_audit(project_id, node_id, version_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/projects/{project_id}/chapters/{node_id}/versions/{version_id}/evidence-audit/revision-action")
def execute_evidence_utilization_revision_action(
    project_id: str,
    node_id: str,
    version_id: str,
    payload: RevisionActionRequest,
    request: Request,
):
    try:
        ensure_generation_window(request.app.state.pipeline, project_id)
        return request.app.state.pipeline.execute_evidence_utilization_revision_action(
            project_id,
            node_id,
            version_id,
            payload.action,
        )
    except HTTPException:
        raise
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/projects/{project_id}/chapters/{node_id}/versions/{version_id}/generation-metadata/revision-action")
def execute_generation_metadata_revision_action(
    project_id: str,
    node_id: str,
    version_id: str,
    payload: RevisionActionRequest,
    request: Request,
):
    try:
        ensure_generation_window(request.app.state.pipeline, project_id)
        return request.app.state.pipeline.execute_generation_metadata_revision_action(
            project_id,
            node_id,
            version_id,
            payload.action,
        )
    except HTTPException:
        raise
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/projects/{project_id}/chapters/{node_id}/versions/{version_id}/content-nodes/{content_node_id}/revision-action")
def execute_content_node_revision_action(
    project_id: str,
    node_id: str,
    version_id: str,
    content_node_id: str,
    payload: RevisionActionRequest,
    request: Request,
):
    try:
        ensure_generation_window(request.app.state.pipeline, project_id)
        return request.app.state.pipeline.execute_content_revision_action(
            project_id,
            node_id,
            version_id,
            content_node_id,
            payload.action,
        )
    except HTTPException:
        raise
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.patch("/projects/{project_id}/chapters/{node_id}/versions/{version_id}/content-nodes/{content_node_id}")
def update_version_content_node(project_id: str, node_id: str, version_id: str, content_node_id: str, payload: ContentNodeUpdateRequest, request: Request):
    try:
        return request.app.state.workspace_store.update_version_content_node(
            project_id,
            node_id,
            version_id,
            content_node_id,
            payload.markdown,
            select=payload.select,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


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


@router.post("/projects/{project_id}/chapters/{node_id}/subsection-proposal")
def propose_chapter_subsections(project_id: str, node_id: str, request: Request):
    try:
        return request.app.state.pipeline.propose_subsection_expansion(project_id, node_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/projects/{project_id}/chapters/{node_id}/proposals/{proposal_id}/reject")
def reject_chapter_proposal(project_id: str, node_id: str, proposal_id: str, request: Request):
    try:
        return request.app.state.workspace_store.reject_proposal(
            project_id,
            proposal_id,
            target_type="chapter",
            target_id=node_id,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/projects/{project_id}/outline/subsection-proposals")
def propose_project_subsections(project_id: str, request: Request):
    try:
        return request.app.state.pipeline.propose_project_subsection_expansions(project_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/projects/{project_id}/chapters/{node_id}/revision-action")
def execute_chapter_revision_action(project_id: str, node_id: str, payload: RevisionActionRequest, request: Request):
    try:
        ensure_generation_window(request.app.state.pipeline, project_id)
        return request.app.state.pipeline.execute_revision_action(project_id, node_id, payload.action)
    except HTTPException:
        raise
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
