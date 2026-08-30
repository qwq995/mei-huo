from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from coalplan.application.outline_template_library import (
    OutlineTemplateRecommendationQuery,
    build_outline_template_library,
    default_library_dir,
    load_outline_template,
    load_outline_template_index,
    recommend_outline_templates,
)

router = APIRouter(prefix="/outline-template-library", tags=["outline-template-library"])


@router.get("")
def list_outline_templates():
    return load_outline_template_index()


@router.get("/{template_id}")
def get_outline_template(template_id: str):
    template = load_outline_template(template_id)
    if template is None:
        raise HTTPException(status_code=404, detail="目录模板不存在")
    return template.model_dump()


@router.post("/build")
def build_outline_templates(payload: dict, request: Request):
    corpus_dir = payload.get("corpus_dir")
    if not corpus_dir:
        raise HTTPException(status_code=400, detail="请提供施组 Markdown 样本目录")
    try:
        return build_outline_template_library(corpus_dir, payload.get("output_dir") or default_library_dir())
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/recommend")
def recommend_templates(payload: OutlineTemplateRecommendationQuery, request: Request):
    try:
        return recommend_outline_templates(payload, llm=request.app.state.pipeline._structured_llm())
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
