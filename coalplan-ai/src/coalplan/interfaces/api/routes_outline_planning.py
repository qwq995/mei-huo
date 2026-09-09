from fastapi import APIRouter, HTTPException, Request

from coalplan.application.outline_planning import OutlinePlanningService
from coalplan.interfaces.api.outline_edit_guard import ensure_outline_editable

router = APIRouter(tags=["outline-planning"])


def _service(request):
    return OutlinePlanningService(request.app.state.pipeline)


@router.get("/projects/{project_id}/outline/planning")
def get_planning(project_id: str, request: Request):
    try:
        state = _service(request).get(project_id)
        used_ids = {sid for c in state.get("blueprint", {}).get("contracts", []) for sid in c.get("source_section_ids", [])}
        state["source_catalog"] = [{"id": s.id, "title": " / ".join(s.title_path), "file_name": s.source_file} for s in request.app.state.pipeline.projects.get(project_id).sections if s.id in used_ids]
        return {k: v for k, v in state.items() if k not in {"cache", "extracted_findings"}}
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc


@router.post("/projects/{project_id}/outline/planning/confirm")
def confirm_planning(project_id: str, payload: dict, request: Request):
    try:
        ensure_outline_editable(request, project_id)
        manager = request.app.state.job_manager
        if any(j["status"] in {"queued", "running"} for j in manager.list_recent(project_id)):
            raise ValueError("项目任务正在执行，请等待完成后确认。")
        _service(request).confirm(project_id, payload)
        return get_planning(project_id, request)
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc


@router.patch("/projects/{project_id}/outline/planning/contracts/{node_id}")
def edit_contract(project_id: str, node_id: str, payload: dict, request: Request):
    try:
        ensure_outline_editable(request, project_id)
        if any(j["status"] in {"queued", "running"} for j in request.app.state.job_manager.list_recent(project_id)):
            raise ValueError("项目任务正在执行，请等待完成后保存。")
        _service(request).edit_contract(project_id, node_id, payload)
        return get_planning(project_id, request)
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
