from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from .schemas import TemplateSummaryResponse, TemplateTreeResponse

router = APIRouter(tags=["templates"])


@router.get("/templates", response_model=list[TemplateSummaryResponse])
def list_templates(request: Request):
    pipeline = request.app.state.pipeline
    if hasattr(pipeline.templates, "list_templates"):
        return [TemplateSummaryResponse(**item) for item in pipeline.templates.list_templates()]
    return [TemplateSummaryResponse(template_id="coal_fire", name="火区治理施工组织设计模板")]


@router.get("/projects/{project_id}/template-tree", response_model=TemplateTreeResponse)
def get_project_template(project_id: str, request: Request):
    pipeline = request.app.state.pipeline
    try:
        project = pipeline.projects.get(project_id)
        if project.template_tree is None:
            raise ValueError("Template tree not loaded.")
        return TemplateTreeResponse(
            template_id=project.template_tree.id,
            name=project.template_tree.name,
            nodes=_nodes(project.template_tree.nodes),
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/templates/{template_id}", response_model=TemplateTreeResponse)
def get_template(template_id: str, request: Request):
    pipeline = request.app.state.pipeline
    try:
        tree = pipeline.templates.load(template_id)
        return TemplateTreeResponse(template_id=tree.id, name=tree.name, nodes=_nodes(tree.nodes))
    except Exception as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


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
