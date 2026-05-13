from __future__ import annotations

from pathlib import Path

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    telegram_api_id: int
    telegram_api_hash: str
    telegram_session_path: Path = Path("data/telegram.session")
    obsidian_vault_path: Path
    database_url: str = "sqlite:///./data/app.db"
    openai_api_key: str | None = None
    openai_base_url: str | None = None
    wiki_model: str = "gpt-4o-mini"
    vault_bucket: str = "_telegram_wiki"
    ingest_max_messages_per_peer: int = 3000

    @field_validator("telegram_session_path", "obsidian_vault_path", mode="before")
    @classmethod
    def expand_path(cls, v: str | Path) -> Path:
        return Path(v).expanduser().resolve()


def get_settings() -> Settings:
    return Settings()
