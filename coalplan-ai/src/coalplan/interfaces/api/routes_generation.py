from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from coalplan.interfaces.api.execution_window_guard import ensure_generation_window

from .schemas import (
    ChildChapterGenerateRequest,
    ChapterResponse,
    GenerateResponse,
    QualityAuditRunRequest,
    QualityAuditTargetExecuteRequest,
    QualityAuditTargetsExecuteRequest,
    QualityIterationRunRequest,
    QualityFeedbackApplyRequest,
    run_summary,
)

router = APIRouter(tags=["generation"])


@router.post("/projects/{project_id}/generate", response_model=GenerateResponse)
def generate_project(project_id: str, request: Request):
    pipeline = request.app.state.pipeline
    try:
        ensure_generation_window(pipeline, project_id)
        pipeline.prepare_run(project_id)
        run = pipeline.generate_all(project_id)
        return run_summary(run)
    except HTTPException:
        raise
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/projects/{project_id}/chapters", response_model=list[dict])
def list_chapters(project_id: str, request: Request):
    pipeline = request.app.state.pipeline
    try:
        project = pipeline.projects.get(project_id)
        if not project.runs:
            return []
        return [
            {
                "node_id": task.node_id,
                "title": task.title,
                "target_word_count": task.target_word_count,
                "status": task.status.value,
                "source_matches": [_dump(match) for match in task.source_matches],
                "source_mapping": _dump(task.source_mapping) if task.source_mapping else None,
                "draft_id": task.draft_id,
                "error_message": task.error_message,
            }
            for task in project.runs[-1].chapter_tasks
        ]
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/projects/{project_id}/chapters/{node_id}/generate", response_model=ChapterResponse)
def generate_chapter(project_id: str, node_id: str, request: Request):
    pipeline = request.app.state.pipeline
    try:
        ensure_generation_window(pipeline, project_id)
        draft = pipeline.generate_one(project_id, node_id)
        project = pipeline.projects.get(project_id)
        task = next((item for item in project.runs[-1].chapter_tasks if item.node_id == node_id), None)
        return ChapterResponse(
            node_id=draft.node_id,
            title=draft.title,
            status=draft.validation_status.value,
            markdown=draft.markdown,
            draft_path=draft.artifact_path,
            source_matches=[_dump(match) for match in task.source_matches] if task else [],
            source_mapping=_dump(task.source_mapping) if task and task.source_mapping else None,
            version=_selected_version(request, project_id, node_id),
        )
    except HTTPException:
        raise
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/projects/{project_id}/chapters/{node_id}/children/generate", response_model=dict)
def generate_child_chapters(project_id: str, node_id: str, payload: ChildChapterGenerateRequest, request: Request):
    pipeline = request.app.state.pipeline
    try:
        ensure_generation_window(pipeline, project_id)
        return pipeline.generate_child_chapters(
            project_id,
            node_id,
            recursive=payload.recursive,
            only_pending=payload.only_pending,
            limit=payload.limit,
        )
    except HTTPException:
        raise
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/projects/{project_id}/chapters/{node_id}", response_model=ChapterResponse)
def get_chapter(project_id: str, node_id: str, request: Request):
    pipeline = request.app.state.pipeline
    try:
        project = pipeline.projects.get(project_id)
        if not project.runs:
            raise KeyError("Project has no generation run.")
        task = next((item for item in project.runs[-1].chapter_tasks if item.node_id == node_id), None)
        if task is None:
            raise KeyError(f"Unknown node_id: {node_id}")
        version = _selected_version(request, project_id, node_id)
        path = None
        markdown = ""
        if version:
            markdown = version.get("markdown", "")
            path = version.get("artifact_path")
        elif task.draft_id:
            path = str(pipeline.artifacts.root / project_id / "chapters" / f"{node_id}.md")
            markdown = pipeline.artifacts.read_text(path)
        return ChapterResponse(
            node_id=task.node_id,
            title=task.title,
            status=task.status.value,
            markdown=markdown,
            draft_path=path,
            source_matches=[_dump(match) for match in task.source_matches],
            source_mapping=_dump(task.source_mapping) if task.source_mapping else None,
            version=version,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/projects/{project_id}/merge", response_model=GenerateResponse)
def merge_project(project_id: str, request: Request):
    pipeline = request.app.state.pipeline
    try:
        ensure_generation_window(pipeline, project_id)
        run = pipeline.merge_latest(project_id)
        return run_summary(run)
    except HTTPException:
        raise
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/projects/{project_id}/quality-feedback", response_model=dict)
def get_quality_feedback(project_id: str, request: Request):
    pipeline = request.app.state.pipeline
    try:
        feedback = pipeline.quality_feedback_plan(project_id)
        return {"project_id": project_id, "feedback": _dump(feedback) if feedback else None}
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/projects/{project_id}/quality-feedback", response_model=dict)
def apply_quality_feedback(project_id: str, payload: QualityFeedbackApplyRequest, request: Request):
    pipeline = request.app.state.pipeline
    try:
        return pipeline.apply_quality_feedback_report(
            project_id,
            payload.report,
            trace_diagnostics=payload.trace_diagnostics,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/projects/{project_id}/quality-audit", response_model=dict)
def run_quality_audit(project_id: str, payload: QualityAuditRunRequest, request: Request):
    pipeline = request.app.state.pipeline
    try:
        return pipeline.run_quality_audit(
            project_id,
            source_markdown=payload.source_markdown,
            human_reference_markdown=payload.human_reference_markdown,
            apply_feedback=payload.apply_feedback,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/projects/{project_id}/quality-audit/revision-targets", response_model=dict)
def get_quality_audit_revision_targets(project_id: str, request: Request):
    pipeline = request.app.state.pipeline
    try:
        return pipeline.quality_audit_revision_targets(project_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/projects/{project_id}/quality-audit/revision-targets/{target_index}/execute", response_model=dict)
def execute_quality_audit_revision_target(
    project_id: str,
    target_index: int,
    payload: QualityAuditTargetExecuteRequest,
    request: Request,
):
    pipeline = request.app.state.pipeline
    try:
        return pipeline.execute_quality_audit_revision_target(project_id, target_index, action=payload.action)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/projects/{project_id}/quality-audit/revision-targets/execute", response_model=dict)
def execute_quality_audit_revision_targets(
    project_id: str,
    payload: QualityAuditTargetsExecuteRequest,
    request: Request,
):
    pipeline = request.app.state.pipeline
    try:
        return pipeline.execute_quality_audit_revision_targets(
            project_id,
            include_user_confirmation=payload.include_user_confirmation,
            limit=payload.limit,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/projects/{project_id}/quality-iteration", response_model=dict)
def run_quality_iteration(project_id: str, payload: QualityIterationRunRequest, request: Request):
    pipeline = request.app.state.pipeline
    try:
        return pipeline.run_quality_iteration(
            project_id,
            max_rounds=payload.max_rounds,
            include_user_confirmation=payload.include_user_confirmation,
            limit_per_round=payload.limit_per_round,
            source_markdown=payload.source_markdown,
            human_reference_markdown=payload.human_reference_markdown,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/projects/{project_id}/quality-iteration/learning-report", response_model=dict)
def get_quality_iteration_learning_report(project_id: str, request: Request):
    pipeline = request.app.state.pipeline
    try:
        return pipeline.quality_iteration_learning_report(project_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/projects/{project_id}/quality-feedback/outline-proposal", response_model=dict)
def propose_quality_feedback_outline(project_id: str, request: Request):
    pipeline = request.app.state.pipeline
    try:
        return pipeline.propose_quality_feedback_outline_repair(project_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def _dump(model) -> dict:
    if hasattr(model, "model_dump"):
        return model.model_dump(mode="json")
    return model.dict()


def _selected_version(request: Request, project_id: str, node_id: str) -> dict | None:
    store = getattr(request.app.state, "workspace_store", None)
    if store is None:
        return None
    try:
        workspace = store.get_workspace(project_id, node_id)
        selected_id = workspace.get("selected_version_id")
        if not selected_id:
            return None
        return store.get_version(project_id, node_id, selected_id)
    except Exception:
        return None
