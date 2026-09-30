from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="JARVIS_")

    data_dir: Path = Path("/data")
    llm_base_url: str = "http://llm-api:8080"
    llm_model: str = "local"
    llm_timeout: float = 120.0
    gmail_account: str = ""
    gmail_query: str = "in:inbox"
    initial_lookback_days: int = 7
    max_attachment_bytes: int = 25_000_000
    max_messages_per_run: int = 50
    content_chars: int = 6000
    # Must match llama.cpp's --ctx-size; compose feeds both from LLM_CONTEXT_SIZE so they cannot diverge.
    context_tokens: int = 8192
    workspace_agent_url: str = ""

    @property
    def secrets_dir(self) -> Path:
        return self.data_dir / "secrets"
