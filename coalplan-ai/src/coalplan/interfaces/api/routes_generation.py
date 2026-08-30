from __future__ import annotations

import re

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


def _public_chapter_markdown(markdown: str) -> str:
    """Expose only deliverable body text; stored versions retain audit/source blocks."""
    lines = (markdown or "").splitlines()
    try:
        start = next(index for index, line in enumerate(lines) if re.match(r"^##\s+生成正文\s*$", line.strip()))
        lines = lines[start + 1:]
        end = next((index for index, line in enumerate(lines) if re.match(r"^##\s+", line.strip())), len(lines))
        lines = lines[:end]
    except StopIteration:
        pass
    cleaned: list[str] = []
    for line in lines:
        # Trace ids can be inline in an otherwise valid paragraph. Remove only
        # the trace annotation, never the whole paragraph.
        line = re.sub(
            r"\s*(?:[（(][^()（）]*\b(?:evidence_id|section_id|atom_id|fact_id)\s*[:=][^()（）]*[）)]|"
            r"\[[^\[\]]*\b(?:evidence_id|section_id|atom_id|fact_id)\s*[:=][^\[\]]*\])",
            "",
            line,
            flags=re.I,
        )
        line = re.sub(r"\b(?:evidence_id|section_id|atom_id|fact_id)\s*[:=]\s*[^\s，。；;，,]+", "", line, flags=re.I)
        line = re.sub(r"【需人工补充：[^】]+】", "", line).rstrip()
        if re.match(r"^\s*[-*]\s*[。；;，,：:]?\s*$", line):
            continue
        if line.strip():
            cleaned.append(line)
    return "\n".join(cleaned).strip()


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
        result = []
        for task in project.runs[-1].chapter_tasks:
            selected = _selected_version(request, project_id, task.node_id)
            result.append({
                "node_id": task.node_id,
                "title": task.title,
                "target_word_count": task.target_word_count,
                "status": _effective_task_status(request, project_id, task),
                "source_matches": [_dump(match) for match in task.source_matches],
                "source_mapping": _dump(task.source_mapping) if task.source_mapping else None,
                "draft_id": task.draft_id,
                "version_id": selected.get("id") if selected else None,
                "version_no": selected.get("version_no") if selected else None,
                "selected_version_id": selected.get("id") if selected else None,
                "error_message": task.error_message,
            })
        return result
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/projects/{project_id}/partial-merge", response_model=GenerateResponse)
def partial_merge_project(project_id: str, request: Request):
    """Create a clearly marked stage manuscript while chapters are still missing."""
    pipeline = request.app.state.pipeline
    try:
        ensure_generation_window(pipeline, project_id)
        return run_summary(pipeline.merge_partial(project_id))
    except HTTPException:
        raise
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/projects/{project_id}/generation-context", response_model=dict)
def get_generation_context(project_id: str, request: Request):
    try:
        return request.app.state.pipeline.get_generation_context(project_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/projects/{project_id}/chapters/{node_id}/writing-units", response_model=dict)
def preview_chapter_writing_units(project_id: str, node_id: str, request: Request):
    try:
        return request.app.state.pipeline.preview_chapter_writing_units(project_id, node_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/projects/{project_id}/chapters/{node_id}/writing-skill", response_model=dict)
def generate_chapter_writing_skill(project_id: str, node_id: str, request: Request):
    try:
        ensure_generation_window(request.app.state.pipeline, project_id)
        return request.app.state.pipeline.generate_chapter_writing_skill_for_node(project_id, node_id, force=True)
    except HTTPException:
        raise
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.put("/projects/{project_id}/chapters/{node_id}/writing-skill", response_model=dict)
def save_chapter_writing_skill(project_id: str, node_id: str, payload: dict, request: Request):
    try:
        return request.app.state.pipeline.save_chapter_writing_skill(project_id, node_id, payload)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/projects/{project_id}/chapters/{node_id}/generate", response_model=ChapterResponse)
def generate_chapter(project_id: str, node_id: str, request: Request):
    pipeline = request.app.state.pipeline
    try:
        ensure_generation_window(pipeline, project_id)
        draft = pipeline.generate_one(project_id, node_id)
        project = pipeline.projects.get(project_id)
        task = next((item for item in project.runs[-1].chapter_tasks if item.node_id == node_id), None)
        selected_version = _selected_version(request, project_id, node_id)
        version_metadata = (selected_version or {}).get("generation_metadata") or {}
        version_mapping = version_metadata.get("source_mapping")
        return ChapterResponse(
            node_id=draft.node_id,
            title=draft.title,
            status=draft.validation_status.value,
            markdown=_public_chapter_markdown(draft.markdown),
            draft_path=draft.artifact_path,
            source_matches=[_dump(match) for match in task.source_matches] if task else [],
            source_mapping=version_mapping or (_dump(task.source_mapping) if task and task.source_mapping else None),
            generation_metadata=version_metadata or draft.generation_metadata,
            evidence_audit=_dump(draft.evidence_audit) if draft.evidence_audit else None,
            version=selected_version,
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
        version_metadata = (version or {}).get("generation_metadata") or {}
        version_mapping = version_metadata.get("source_mapping")
        return ChapterResponse(
            node_id=task.node_id,
            title=task.title,
            status=_effective_task_status(request, project_id, task),
            markdown=_public_chapter_markdown(markdown),
            draft_path=path,
            source_matches=[_dump(match) for match in task.source_matches],
            source_mapping=version_mapping or (_dump(task.source_mapping) if task.source_mapping else None),
            generation_metadata=version_metadata,
            evidence_audit=version.get("evidence_audit") if version else None,
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
    except ValueError as exc:
        if "No quality audit report is available" in str(exc):
            return {
                "project_id": project_id,
                "status": "not_run",
                "targets": [],
                "message": "尚未运行成稿质量审查，完成阶段性合稿后即可生成修订任务。",
                "next_action": "run_quality_audit",
            }
        raise HTTPException(status_code=400, detail=str(exc)) from exc
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


def _effective_task_status(request: Request, project_id: str, task) -> str:
    """Treat a persisted selected version as generated after imports or service restarts."""
    try:
        workspace = request.app.state.workspace_store.get_workspace(project_id, task.node_id)
        selected_id = workspace.get("selected_version_id")
        selected = next((item for item in workspace.get("versions", []) if item.get("id") == selected_id), None)
        review_status = ((selected or {}).get("generation_metadata") or {}).get("quality_review", {}).get("status")
        if review_status in {"needs_repair", "failed"}:
            return review_status
        if selected_id and review_status == "passed":
            return "passed"
        if selected_id and task.status.value not in {"needs_repair", "failed", "running"}:
            return "passed"
    except Exception:
        pass
    return task.status.value
