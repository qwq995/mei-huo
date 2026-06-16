from __future__ import annotations

import os
from pathlib import Path

from pydantic import BaseModel


class Settings(BaseModel):
    storage_dir: Path = Path(os.getenv("COALPLAN_STORAGE_DIR", ".coalplan-data"))
    database_url: str | None = os.getenv("COALPLAN_DATABASE_URL")
    template_id: str = os.getenv("COALPLAN_TEMPLATE_ID", "coal_fire")
    llm_provider: str = os.getenv("COALPLAN_LLM_PROVIDER", "fake")
    structured_llm_provider: str | None = os.getenv("COALPLAN_STRUCTURED_LLM_PROVIDER")
    openai_base_url: str = os.getenv("COALPLAN_OPENAI_BASE_URL", "http://127.0.0.1:8000/v1")
    openai_api_key: str = os.getenv("COALPLAN_OPENAI_API_KEY", "")
    openai_model: str = os.getenv("COALPLAN_OPENAI_MODEL", "local-model")
    llm_trace_dir: Path | None = Path(os.environ["COALPLAN_LLM_TRACE_DIR"]) if os.getenv("COALPLAN_LLM_TRACE_DIR") else None
    minimax_base_url: str = os.getenv("COALPLAN_MINIMAX_BASE_URL", "https://api.minimaxi.com/v1")
    minimax_api_key: str = os.getenv("COALPLAN_MINIMAX_API_KEY", os.getenv("COALPLAN_OPENAI_API_KEY", ""))
    minimax_model: str = os.getenv("COALPLAN_MINIMAX_MODEL", "MiniMax-M2.7")
    deepseek_base_url: str = os.getenv("COALPLAN_DEEPSEEK_BASE_URL", "https://api.deepseek.com")
    deepseek_api_key: str = os.getenv("COALPLAN_DEEPSEEK_API_KEY", os.getenv("COALPLAN_OPENAI_API_KEY", ""))
    deepseek_model: str = os.getenv("COALPLAN_DEEPSEEK_MODEL", "deepseek-v4-pro")


def get_settings() -> Settings:
    return Settings()
