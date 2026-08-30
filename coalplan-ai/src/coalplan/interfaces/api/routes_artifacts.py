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


@router.get("/projects/{project_id}/artifacts/current.md", response_class=PlainTextResponse)
def get_current_generated_markdown(project_id: str, request: Request):
    """Return a reviewable manuscript from currently selected/generated chapters.

    This deliberately renders in memory so previewing or downloading an in-progress
    manuscript does not overwrite the project's final merge artifact or run status.
    """
    pipeline = request.app.state.pipeline
    try:
        markdown, _ = pipeline.render_partial_markdown(project_id)
        return markdown
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
