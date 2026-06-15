from __future__ import annotations

from pydantic import BaseModel, Field


class ProjectCreateRequest(BaseModel):
    name: str = Field(default="宁夏煤火北一火区")
    template_id: str = Field(default="coal_fire")


class ProjectTemplateUpdateRequest(BaseModel):
    template_id: str = Field(default="coal_fire")


class BidMarkdownUploadRequest(BaseModel):
    file_name: str = Field(default="投标技术文件.md")
    content: str


class ProjectSummaryResponse(BaseModel):
    id: str
    project_id: str
    name: str
    template_id: str
    source_document_count: int
    section_count: int
    run_count: int


class GenerateResponse(BaseModel):
    id: str
    run_id: str
    status: str
    task_count: int
    passed_count: int
    failed_count: int
    final_artifact_path: str | None = None
    logs: list[str]


class ChapterResponse(BaseModel):
    node_id: str
    title: str
    status: str
    markdown: str = ""
    draft_path: str | None = None
    source_matches: list[dict] = Field(default_factory=list)


class TemplateSummaryResponse(BaseModel):
    template_id: str
    name: str
    path: str | None = None


class TemplateTreeResponse(BaseModel):
    template_id: str
    name: str
    nodes: list[dict]


class SourceTocResponse(BaseModel):
    items: list[dict]
    artifact_json_path: str | None = None
    artifact_markdown_path: str | None = None


class SectionResponse(BaseModel):
    section_id: str
    title_path: list[str]
    level: int
    content: str
    source_file: str
    artifact_path: str | None = None


class ProjectProfileResponse(BaseModel):
    profile: dict | None
    artifact_json_path: str | None = None
    artifact_markdown_path: str | None = None


class OutlinePlanResponse(BaseModel):
    outline: dict | None
    artifact_json_path: str | None = None
    artifact_markdown_path: str | None = None


class DirectoryResponse(BaseModel):
    project: ProjectSummaryResponse
    template: TemplateTreeResponse | None = None
    source_toc: SourceTocResponse | None = None
    outline: OutlinePlanResponse | None = None
    chapter_tasks: list[dict] = Field(default_factory=list)


def project_summary(project) -> ProjectSummaryResponse:
    return ProjectSummaryResponse(
        id=project.id,
        project_id=project.id,
        name=project.name,
        template_id=project.template_id,
        source_document_count=len(project.source_documents),
        section_count=len(project.sections),
        run_count=len(project.runs),
    )


def run_summary(run) -> GenerateResponse:
    passed = sum(1 for task in run.chapter_tasks if task.status.value == "passed")
    failed = sum(1 for task in run.chapter_tasks if task.status.value == "failed")
    return GenerateResponse(
        id=run.id,
        run_id=run.id,
        status=run.status.value,
        task_count=len(run.chapter_tasks),
        passed_count=passed,
        failed_count=failed,
        final_artifact_path=run.final_artifact_path,
        logs=run.logs,
    )
