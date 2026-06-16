from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from coalplan.application.serialization import dump_model

from .schemas import (
    BidMarkdownUploadRequest,
    DirectoryResponse,
    OutlinePlanResponse,
    ProjectCreateRequest,
    ProjectProfileResponse,
    ProjectTemplateUpdateRequest,
    ProjectSummaryResponse,
    SectionResponse,
    SourceTocResponse,
    TemplateTreeResponse,
    project_summary,
)

router = APIRouter(tags=["projects"])


@router.post("/projects", response_model=ProjectSummaryResponse)
def create_project(payload: ProjectCreateRequest, request: Request):
    pipeline = request.app.state.pipeline
    try:
        project = pipeline.create_project(payload.name, payload.template_id)
        return project_summary(project)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/projects", response_model=list[ProjectSummaryResponse])
def list_projects(request: Request):
    pipeline = request.app.state.pipeline
    return [project_summary(project) for project in pipeline.projects.list()]


@router.get("/projects/{project_id}", response_model=ProjectSummaryResponse)
def get_project(project_id: str, request: Request):
    pipeline = request.app.state.pipeline
    try:
        return project_summary(pipeline.projects.get(project_id))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.delete("/projects/{project_id}")
def delete_project(project_id: str, request: Request, keep_artifacts: bool = True):
    pipeline = request.app.state.pipeline
    try:
        if hasattr(pipeline.projects, "delete"):
            pipeline.projects.delete(project_id)
        else:
            raise ValueError("Configured project repository does not support deletion.")
        return {"deleted": True, "keep_artifacts": keep_artifacts}
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/projects/{project_id}/bid-markdown", response_model=ProjectSummaryResponse)
def upload_bid_markdown(project_id: str, payload: BidMarkdownUploadRequest, request: Request):
    pipeline = request.app.state.pipeline
    try:
        project = pipeline.ingest_bid_markdown(project_id, file_name=payload.file_name, content=payload.content)
        return project_summary(project)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/projects/{project_id}/template", response_model=ProjectSummaryResponse)
def update_project_template(project_id: str, payload: ProjectTemplateUpdateRequest, request: Request):
    pipeline = request.app.state.pipeline
    try:
        project = pipeline.set_template(project_id, payload.template_id)
        return project_summary(project)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/projects/{project_id}/normalize", response_model=ProjectSummaryResponse)
def normalize_project(project_id: str, request: Request):
    pipeline = request.app.state.pipeline
    try:
        project = pipeline.projects.get(project_id)
        if not project.sections:
            raise ValueError("No bid markdown has been uploaded.")
        return project_summary(project)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/projects/{project_id}/source-toc", response_model=SourceTocResponse)
def get_source_toc(project_id: str, request: Request):
    pipeline = request.app.state.pipeline
    try:
        project = pipeline.projects.get(project_id)
        if project.source_toc is None:
            raise ValueError("Source toc is not available. Upload and normalize a bid markdown file first.")
        return SourceTocResponse(
            items=[dump_model(item) for item in project.source_toc.items],
            artifact_json_path=project.source_toc.artifact_json_path,
            artifact_markdown_path=project.source_toc.artifact_markdown_path,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/projects/{project_id}/sections/{section_id}", response_model=SectionResponse)
def get_section(project_id: str, section_id: str, request: Request):
    pipeline = request.app.state.pipeline
    try:
        project = pipeline.projects.get(project_id)
        section = next((item for item in project.sections if item.id == section_id), None)
        if section is None:
            raise KeyError(f"Unknown section_id: {section_id}")
        artifact_path = str(pipeline.artifacts.root / project_id / "inputs" / "sections" / f"{section_id}.md")
        return SectionResponse(
            section_id=section.id,
            title_path=section.title_path,
            level=section.level,
            content=section.content,
            source_file=section.source_file,
            artifact_path=artifact_path,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/projects/{project_id}/profile", response_model=ProjectProfileResponse)
def get_profile(project_id: str, request: Request):
    pipeline = request.app.state.pipeline
    try:
        project = pipeline.projects.get(project_id)
        profile = project.project_profile
        return ProjectProfileResponse(
            profile=dump_model(profile) if profile else None,
            artifact_json_path=profile.artifact_json_path if profile else None,
            artifact_markdown_path=profile.artifact_markdown_path if profile else None,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/projects/{project_id}/outline", response_model=OutlinePlanResponse)
def get_outline(project_id: str, request: Request):
    pipeline = request.app.state.pipeline
    try:
        project = pipeline.projects.get(project_id)
        outline = project.outline_plan
        return OutlinePlanResponse(
            outline=dump_model(outline) if outline else None,
            artifact_json_path=outline.artifact_json_path if outline else None,
            artifact_markdown_path=outline.artifact_markdown_path if outline else None,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/projects/{project_id}/directory", response_model=DirectoryResponse)
def generate_directory(project_id: str, request: Request):
    pipeline = request.app.state.pipeline
    try:
        project = pipeline.prepare_directory(project_id)
        return _directory_response(project)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/projects/{project_id}/directory", response_model=DirectoryResponse)
def get_directory(project_id: str, request: Request):
    pipeline = request.app.state.pipeline
    try:
        project = pipeline.projects.get(project_id)
        return _directory_response(project)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


def _directory_response(project) -> DirectoryResponse:
    template = None
    if project.template_tree is not None:
        template = TemplateTreeResponse(template_id=project.template_tree.id, name=project.template_tree.name, nodes=_nodes(project.template_tree.nodes))
    source_toc = None
    if project.source_toc is not None:
        source_toc = SourceTocResponse(
            items=[dump_model(item) for item in project.source_toc.items],
            artifact_json_path=project.source_toc.artifact_json_path,
            artifact_markdown_path=project.source_toc.artifact_markdown_path,
        )
    outline = None
    if project.outline_plan is not None:
        outline = OutlinePlanResponse(
            outline=dump_model(project.outline_plan),
            artifact_json_path=project.outline_plan.artifact_json_path,
            artifact_markdown_path=project.outline_plan.artifact_markdown_path,
        )
    tasks = []
    if project.runs:
        tasks = [_task_dict(task) for task in project.runs[-1].chapter_tasks]
    return DirectoryResponse(project=project_summary(project), template=template, source_toc=source_toc, outline=outline, chapter_tasks=tasks)


def _task_dict(task) -> dict:
    return {
        "node_id": task.node_id,
        "title": task.title,
        "status": task.status.value,
        "source_matches": [dump_model(match) for match in task.source_matches],
        "draft_id": task.draft_id,
        "error_message": task.error_message,
    }


def _nodes(nodes) -> list[dict]:
    output = []
    for node in nodes:
        output.append(
            {
                "id": node.id,
                "title": node.title,
                "level": node.level,
                "source_rules": node.source_rules,
                "auto_fill": node.auto_fill,
                "manual_fill": node.manual_fill,
                "special_notes": node.special_notes,
                "children": _nodes(node.children),
            }
        )
    return output
