from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import PlainTextResponse

router = APIRouter(tags=["artifacts"])


@router.get("/projects/{project_id}/artifacts/final.md", response_class=PlainTextResponse)
def get_final_markdown(project_id: str, request: Request):
    pipeline = request.app.state.pipeline
    try:
        project = pipeline.projects.get(project_id)
        if not project.runs or not project.runs[-1].final_artifact_path:
            raise KeyError("Final markdown has not been generated.")
        return pipeline.artifacts.read_text(project.runs[-1].final_artifact_path)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

