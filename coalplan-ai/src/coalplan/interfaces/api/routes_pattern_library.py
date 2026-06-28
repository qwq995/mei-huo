from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request

from coalplan.application.pattern_library_admin import (
    analyze_corpus_to_pattern_library,
    apply_generated_pattern_library,
    audit_pattern_library,
    build_reviewable_pattern_skill_from_corpus,
    build_pattern_library_candidate_from_learning_report,
    export_pattern_skill,
    read_active_pattern_library,
    read_generated_pattern_library,
    read_pattern_prompt_cards,
    read_pattern_library_apply_history,
)

from .schemas import (
    PatternLibraryAnalyzeRequest,
    PatternLibraryAnalyzeResponse,
    PatternLibraryBuildSkillRequest,
    PatternLibraryBuildSkillResponse,
    PatternLibraryApplyRequest,
    PatternLibraryApplyHistoryResponse,
    PatternLibraryApplyResponse,
    PatternLibraryAuditRequest,
    PatternLibraryAuditResponse,
    PatternLibraryLearningRequest,
    PatternLibraryLearningResponse,
    PatternLibraryPromptCardsResponse,
    PatternLibraryResponse,
    PatternLibrarySkillExportRequest,
    PatternLibrarySkillResponse,
)

router = APIRouter(prefix="/pattern-library", tags=["pattern-library"])


@router.get("", response_model=PatternLibraryResponse)
def get_active_pattern_library():
    return PatternLibraryResponse(**read_active_pattern_library())


@router.get("/generated", response_model=PatternLibraryResponse)
def get_generated_pattern_library(generated_path: str | None = None):
    try:
        payload = read_generated_pattern_library(generated_path)
        return PatternLibraryResponse(
            library=payload["library"],
            generated_path=payload["generated_path"],
            generated_available=True,
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/apply-history", response_model=PatternLibraryApplyHistoryResponse)
def get_pattern_library_apply_history():
    return PatternLibraryApplyHistoryResponse(**read_pattern_library_apply_history())


@router.get("/skill", response_model=PatternLibrarySkillResponse)
def get_pattern_library_skill(generated_path: str | None = None):
    try:
        return PatternLibrarySkillResponse(**export_pattern_skill(generated_path=generated_path))
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/prompt-cards", response_model=PatternLibraryPromptCardsResponse)
def get_pattern_library_prompt_cards(generated_path: str | None = None):
    try:
        return PatternLibraryPromptCardsResponse(**read_pattern_prompt_cards(generated_path=generated_path))
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/analyze", response_model=PatternLibraryAnalyzeResponse)
def analyze_pattern_library(payload: PatternLibraryAnalyzeRequest, request: Request):
    pipeline = request.app.state.pipeline
    output_dir = Path(payload.output_dir) if payload.output_dir else pipeline.artifacts.root.parent / "pattern-library"
    try:
        return PatternLibraryAnalyzeResponse(
            **analyze_corpus_to_pattern_library(corpus_dir=payload.corpus_dir, output_dir=output_dir)
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/build-skill", response_model=PatternLibraryBuildSkillResponse)
def build_pattern_library_skill(payload: PatternLibraryBuildSkillRequest, request: Request):
    pipeline = request.app.state.pipeline
    output_dir = (
        Path(payload.output_dir)
        if payload.output_dir
        else pipeline.artifacts.root.parent / "pattern-library" / "reviewable-skill-build"
    )
    try:
        return PatternLibraryBuildSkillResponse(
            **build_reviewable_pattern_skill_from_corpus(
                corpus_dir=payload.corpus_dir,
                output_dir=output_dir,
                skill_name=payload.skill_name,
                include_source_excerpts=payload.include_source_excerpts,
                max_source_chars=payload.max_source_chars,
            )
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/learn-from-quality-iteration", response_model=PatternLibraryLearningResponse)
def learn_pattern_library_from_quality_iteration(payload: PatternLibraryLearningRequest, request: Request):
    pipeline = request.app.state.pipeline
    output_dir = Path(payload.output_dir) if payload.output_dir else pipeline.artifacts.root.parent / "pattern-library"
    try:
        if payload.learning_report is not None:
            learning_report = payload.learning_report
        elif payload.learning_report_path:
            learning_report = json.loads(Path(payload.learning_report_path).read_text(encoding="utf-8-sig"))
        elif payload.project_id:
            learning_report = pipeline.quality_iteration_learning_report(payload.project_id)
        else:
            raise ValueError("Provide project_id, learning_report_path, or learning_report.")
        return PatternLibraryLearningResponse(
            **build_pattern_library_candidate_from_learning_report(
                learning_report=learning_report,
                output_dir=output_dir,
                selected_suggestion_indexes=payload.selected_suggestion_indexes,
            )
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/audit", response_model=PatternLibraryAuditResponse)
def audit_pattern_library_endpoint(payload: PatternLibraryAuditRequest, request: Request):
    pipeline = request.app.state.pipeline
    output_dir = Path(payload.output_dir) if payload.output_dir else pipeline.artifacts.root.parent / "pattern-library"
    try:
        return PatternLibraryAuditResponse(
            **audit_pattern_library(
                generated_path=payload.generated_path,
                library=payload.library,
                corpus_dir=payload.corpus_dir,
                output_dir=output_dir,
            )
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/apply-generated", response_model=PatternLibraryApplyResponse)
def apply_generated_pattern_library_endpoint(payload: PatternLibraryApplyRequest):
    try:
        return PatternLibraryApplyResponse(**apply_generated_pattern_library(generated_path=payload.generated_path))
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/skill/export", response_model=PatternLibrarySkillResponse)
def export_pattern_library_skill_endpoint(payload: PatternLibrarySkillExportRequest):
    try:
        return PatternLibrarySkillResponse(
            **export_pattern_skill(
                generated_path=payload.generated_path,
                output_path=payload.output_path,
                output_dir=payload.output_dir,
            )
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
