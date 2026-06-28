from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from coalplan.application.pipeline_blueprint import build_pipeline_blueprint, render_pipeline_blueprint_markdown
from coalplan.application.serialization import dump_model
from coalplan.application.revision_decision import build_revision_decisions

from .schemas import (
    BidMarkdownUploadRequest,
    CurrentExecutionWindowResponse,
    DirectoryResponse,
    GenerationControlPlanResponse,
    GenerationReadinessBatchExecuteRequest,
    GenerationReadinessResponse,
    IterationPlanResponse,
    OutlineGenerationStepRunResponse,
    OutlineGenerationStepProgressResponse,
    OutlinePlanResponse,
    PipelineActionPlanResponse,
    PipelineBlueprintResponse,
    PipelineGateReportResponse,
    ProjectCreateRequest,
    ProjectProfileResponse,
    RevisionDecisionsResponse,
    ProjectTemplateUpdateRequest,
    ProjectSummaryResponse,
    SectionResponse,
    SourceTocResponse,
    TemplateTreeResponse,
    TargetedRevisionPlanResponse,
    project_summary,
)

router = APIRouter(tags=["projects"])


@router.get("/pipeline-blueprint", response_model=PipelineBlueprintResponse)
def get_pipeline_blueprint():
    blueprint = build_pipeline_blueprint()
    return PipelineBlueprintResponse(
        blueprint=dump_model(blueprint),
        markdown=render_pipeline_blueprint_markdown(blueprint),
    )


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


@router.get("/projects/{project_id}/generation-control-plan", response_model=GenerationControlPlanResponse)
def get_generation_control_plan(project_id: str, request: Request):
    pipeline = request.app.state.pipeline
    try:
        plan = pipeline.generation_control_plan(project_id)
        return GenerationControlPlanResponse(
            plan=dump_model(plan),
            artifact_json_path=str(pipeline.artifacts.root / project_id / "control" / "generation_control_plan.json"),
            artifact_markdown_path=str(pipeline.artifacts.root / project_id / "control" / "generation_control_plan.md"),
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/projects/{project_id}/revision-decisions", response_model=RevisionDecisionsResponse)
def get_revision_decisions(project_id: str, request: Request):
    pipeline = request.app.state.pipeline
    try:
        project = pipeline.projects.get(project_id)
        if not project.runs:
            return RevisionDecisionsResponse(decisions=[])
        project.template_tree = pipeline._effective_template_tree(project)
        if project.template_tree is None:
            return RevisionDecisionsResponse(decisions=[])
        control_plan = pipeline.generation_control_plan(project_id)
        drafts = pipeline._selected_version_drafts(project)
        if not drafts:
            drafts = pipeline._drafts.get(project.runs[-1].id, [])
        decisions = build_revision_decisions(
            run=project.runs[-1],
            drafts=drafts,
            template_tree=project.template_tree,
            policies=control_plan.chapter_policies,
        )
        return RevisionDecisionsResponse(
            decisions=[dump_model(item) for item in decisions],
            artifact_json_path=str(pipeline.artifacts.root / project_id / "control" / "revision_decisions.json"),
            artifact_markdown_path=str(pipeline.artifacts.root / project_id / "control" / "revision_decisions.md"),
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/projects/{project_id}/pipeline-gates", response_model=PipelineGateReportResponse)
def get_pipeline_gates(project_id: str, request: Request):
    pipeline = request.app.state.pipeline
    try:
        return pipeline.pipeline_gate_report(project_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/projects/{project_id}/pipeline-actions", response_model=PipelineActionPlanResponse)
def get_pipeline_actions(project_id: str, request: Request):
    pipeline = request.app.state.pipeline
    try:
        return pipeline.pipeline_action_plan(project_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/projects/{project_id}/generation-readiness", response_model=GenerationReadinessResponse)
def get_generation_readiness(project_id: str, request: Request):
    pipeline = request.app.state.pipeline
    try:
        return pipeline.generation_readiness(project_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/projects/{project_id}/generation-readiness/execute", response_model=dict)
def execute_generation_readiness_batch(project_id: str, payload: GenerationReadinessBatchExecuteRequest, request: Request):
    pipeline = request.app.state.pipeline
    try:
        return pipeline.execute_generation_readiness_batch(
            project_id,
            group_id=payload.group_id,
            include_user_confirmation=payload.include_user_confirmation,
            limit=payload.limit,
            respect_execution_window=payload.respect_execution_window,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/projects/{project_id}/outline-generation-steps", response_model=OutlineGenerationStepProgressResponse)
def get_outline_generation_steps(project_id: str, request: Request):
    pipeline = request.app.state.pipeline
    try:
        return pipeline.outline_generation_step_progress(project_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/projects/{project_id}/outline-generation-steps/{step_id}/generate", response_model=OutlineGenerationStepRunResponse)
def generate_outline_step(project_id: str, step_id: str, request: Request):
    pipeline = request.app.state.pipeline
    try:
        return pipeline.generate_outline_step(project_id, step_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/projects/{project_id}/iteration-plan", response_model=IterationPlanResponse)
def get_iteration_plan(project_id: str, request: Request):
    pipeline = request.app.state.pipeline
    try:
        return pipeline.iteration_plan(project_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/projects/{project_id}/current-execution-window", response_model=CurrentExecutionWindowResponse)
def get_current_execution_window(project_id: str, request: Request):
    pipeline = request.app.state.pipeline
    try:
        return pipeline.current_execution_window(project_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/projects/{project_id}/targeted-revision-plan", response_model=TargetedRevisionPlanResponse)
def get_targeted_revision_plan(project_id: str, request: Request):
    pipeline = request.app.state.pipeline
    try:
        return pipeline.targeted_revision_plan(project_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/projects/{project_id}/directory", response_model=DirectoryResponse)
def generate_directory(project_id: str, request: Request):
    pipeline = request.app.state.pipeline
    try:
        project = pipeline.prepare_directory(project_id)
        return _directory_response(project, pipeline)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/projects/{project_id}/directory", response_model=DirectoryResponse)
def get_directory(project_id: str, request: Request):
    pipeline = request.app.state.pipeline
    try:
        project = pipeline.projects.get(project_id)
        return _directory_response(project, pipeline)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


def _directory_response(project, pipeline=None) -> DirectoryResponse:
    warnings = []
    profile_status = "ready" if project.project_profile is not None else "not_ready"
    outline_status = "planned" if project.outline_plan is not None else "not_run"
    outline_source = getattr(project.outline_plan, "plan_source", "template") if project.outline_plan is not None else "template"
    if project.outline_plan is None:
        warnings.append("已生成基础模板目录。可继续手动编辑，或点击 AI 优化目录生成可确认的修改建议。")
    if project.project_profile and project.project_profile.missing_items:
        if any("兜底" in item or "失败" in item for item in project.project_profile.missing_items):
            warnings.append("项目概况使用了基础兜底画像，请人工补充关键信息后再正式生成。")
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
    generation_control = None
    if pipeline is not None and project.source_toc is not None and project.template_tree is not None:
        try:
            plan = pipeline.generation_control_plan(project.id)
            generation_control = GenerationControlPlanResponse(
                plan=dump_model(plan),
                artifact_json_path=str(pipeline.artifacts.root / project.id / "control" / "generation_control_plan.json"),
                artifact_markdown_path=str(pipeline.artifacts.root / project.id / "control" / "generation_control_plan.md"),
            )
        except Exception as exc:
            warnings.append(f"生成控制计划暂不可用：{exc}")
    revision_decisions = None
    if pipeline is not None and project.runs and project.template_tree is not None:
        try:
            control_plan = pipeline.generation_control_plan(project.id)
            drafts = pipeline._selected_version_drafts(project) or pipeline._drafts.get(project.runs[-1].id, [])
            decisions = build_revision_decisions(
                run=project.runs[-1],
                drafts=drafts,
                template_tree=project.template_tree,
                policies=control_plan.chapter_policies,
            )
            revision_decisions = RevisionDecisionsResponse(
                decisions=[dump_model(item) for item in decisions],
                artifact_json_path=str(pipeline.artifacts.root / project.id / "control" / "revision_decisions.json"),
                artifact_markdown_path=str(pipeline.artifacts.root / project.id / "control" / "revision_decisions.md"),
            )
        except Exception as exc:
            warnings.append(f"生成后修订判定暂不可用：{exc}")
    tasks = []
    if project.runs:
        tasks = [_task_dict(task) for task in project.runs[-1].chapter_tasks]
    return DirectoryResponse(
        project=project_summary(project),
        template=template,
        source_toc=source_toc,
        outline=outline,
        generation_control=generation_control,
        revision_decisions=revision_decisions,
        chapter_tasks=tasks,
        profile_status=profile_status,
        outline_status=outline_status,
        outline_source=outline_source,
        warnings=warnings,
    )


def _task_dict(task) -> dict:
    return {
        "node_id": task.node_id,
        "title": task.title,
        "status": task.status.value,
        "source_matches": [dump_model(match) for match in task.source_matches],
        "source_mapping": dump_model(task.source_mapping) if task.source_mapping else None,
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
