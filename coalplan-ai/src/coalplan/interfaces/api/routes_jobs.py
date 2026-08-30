from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from coalplan.application.generation_jobs import JobConflictError


router = APIRouter(tags=["jobs"])


class CreateJobRequest(BaseModel):
    job_type: str
    payload: dict = Field(default_factory=dict)


@router.post("/projects/{project_id}/jobs", status_code=202)
def create_job(project_id: str, payload: CreateJobRequest, request: Request):
    try:
        return request.app.state.job_manager.create(project_id, payload.job_type, payload.payload)
    except JobConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/projects/{project_id}/jobs/active")
def list_jobs(project_id: str, request: Request, limit: int = 12):
    return request.app.state.job_manager.list_recent(project_id, limit=min(max(limit, 1), 50))


@router.get("/projects/{project_id}/jobs/{job_id}")
def get_job(project_id: str, job_id: str, request: Request):
    try:
        return request.app.state.job_manager.get(project_id, job_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/projects/{project_id}/jobs/{job_id}/retry", status_code=202)
def retry_job(project_id: str, job_id: str, request: Request):
    try:
        return request.app.state.job_manager.retry(project_id, job_id)
    except JobConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/projects/{project_id}/jobs/{job_id}/pause", status_code=202)
def pause_job(project_id: str, job_id: str, request: Request):
    try:
        return request.app.state.job_manager.pause(project_id, job_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
