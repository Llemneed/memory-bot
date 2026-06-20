"""
Bot configuration via .env.
"""
from __future__ import annotations

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    BOT_TOKEN: str

    # LLM
    G4F_MODEL: str = "gpt-4o-mini"
    G4F_PROXY: str = ""
    G4F_PROVIDER_ORDER: str = "PollinationsAI,DeepInfra,HuggingChat,You,Auto"
    G4F_WEB_SEARCH: bool = False
    LLM_TIMEOUT: int = 60
    LLM_MAX_RETRIES: int = 5

    # Memory
    HISTORY_LAST_N: int = 10
    RETRIEVAL_TOP_K: int = 5
    FACTS_TOP_K: int = 5
    MAX_CONTEXT_CHARS: int = 6000
    TELEGRAM_MAX_MESSAGE_CHARS: int = 3500
    MESSAGE_BURST_DEDUP_SECONDS: int = 5
    MESSAGE_STORAGE_DEDUP_SECONDS: int = 30

    # DB
    DB_PATH: str = "database/sqlite.db"

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


settings = Settings()
