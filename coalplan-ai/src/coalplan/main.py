from __future__ import annotations

from pathlib import Path

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from coalplan.application.run_generation_pipeline import GenerationPipeline
from coalplan.infrastructure.llm.fake_llm import FakeLLMClient
from coalplan.infrastructure.llm.openai_compatible import OpenAICompatibleLLMClient
from coalplan.infrastructure.llm.source_driven_simulated import SourceDrivenSimulatedLLMClient
from coalplan.infrastructure.markdown.parser import MarkdownDocumentParser
from coalplan.infrastructure.retrieval.keyword_retriever import KeywordSourceRetriever
from coalplan.infrastructure.storage.local_artifact_repository import LocalArtifactRepository
from coalplan.infrastructure.storage.local_project_repository import LocalProjectRepository
from coalplan.infrastructure.templates.markdown_template_loader import MarkdownTemplateLoader
from coalplan.interfaces.api.routes_artifacts import router as artifacts_router
from coalplan.interfaces.api.routes_generation import router as generation_router
from coalplan.interfaces.api.routes_projects import router as projects_router
from coalplan.interfaces.api.routes_templates import router as templates_router
from coalplan.settings import Settings, get_settings


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    app = FastAPI(title="CoalPlan AI 火区治理施组生成原型", version="0.1.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.state.pipeline = build_pipeline(settings)
    app.include_router(projects_router)
    app.include_router(templates_router)
    app.include_router(generation_router)
    app.include_router(artifacts_router)
    return app


def build_pipeline(settings: Settings) -> GenerationPipeline:
    package_root = Path(__file__).resolve().parent
    storage_root = settings.storage_dir
    if not storage_root.is_absolute():
        storage_root = Path.cwd() / storage_root
    llm = _build_llm(settings.llm_provider, settings)
    structured_llm = _build_llm(settings.structured_llm_provider, settings) if settings.structured_llm_provider else None
    return GenerationPipeline(
        projects=LocalProjectRepository(storage_root / "projects"),
        artifacts=LocalArtifactRepository(storage_root / "artifacts"),
        parser=MarkdownDocumentParser(),
        templates=MarkdownTemplateLoader(package_root / "assets" / "templates"),
        retriever=KeywordSourceRetriever(),
        llm=llm,
        structured_llm=structured_llm,
    )


def _build_llm(provider: str | None, settings: Settings):
    provider = provider or "fake"
    if provider == "fake":
        return FakeLLMClient()
    if provider in {"source_fake", "source_driven"}:
        return SourceDrivenSimulatedLLMClient()
    if provider == "minimax":
        return OpenAICompatibleLLMClient(
            base_url=settings.minimax_base_url,
            api_key=settings.minimax_api_key,
            model=settings.minimax_model,
            reasoning_split=True,
            trace_dir=settings.llm_trace_dir,
        )
    if provider == "deepseek":
        return OpenAICompatibleLLMClient(
            base_url=settings.deepseek_base_url,
            api_key=settings.deepseek_api_key,
            model=settings.deepseek_model,
            disable_thinking=True,
            trace_dir=settings.llm_trace_dir,
        )
    return OpenAICompatibleLLMClient(
        base_url=settings.openai_base_url,
        api_key=settings.openai_api_key,
        model=settings.openai_model,
        trace_dir=settings.llm_trace_dir,
    )


app = create_app()


if __name__ == "__main__":
    uvicorn.run("coalplan.main:app", host="127.0.0.1", port=8010, reload=False)
