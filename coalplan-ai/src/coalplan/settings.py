from __future__ import annotations

import os
from pathlib import Path

from pydantic import BaseModel


def _load_local_env() -> None:
    env_path = Path.cwd() / ".env"
    if not env_path.exists():
        return
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if not key or key in os.environ:
            continue
        os.environ[key] = value.strip().strip('"').strip("'")


_load_local_env()


def _env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


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
    reference_vector_enabled: bool = _env_bool("COALPLAN_REFERENCE_VECTOR_ENABLED")
    reference_vector_model: str = os.getenv("COALPLAN_REFERENCE_VECTOR_MODEL", "BAAI/bge-small-zh-v1.5")
    reference_vector_path: Path = Path(os.getenv("COALPLAN_REFERENCE_VECTOR_PATH", "reference-vectors"))
    reference_vector_url: str | None = os.getenv("COALPLAN_REFERENCE_VECTOR_URL")


def get_settings() -> Settings:
    return Settings()
