"""
Конфигурация бота через .env
"""
from __future__ import annotations

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    BOT_TOKEN: str

    # LLM
    G4F_MODEL: str = "gpt-4o-mini"
    LLM_TIMEOUT: int = 60          # секунд на один запрос к провайдеру
    LLM_MAX_RETRIES: int = 5       # сколько провайдеров пробовать

    # Память
    HISTORY_LAST_N: int = 10       # сообщений в short-term окне
    RETRIEVAL_TOP_K: int = 5       # сколько результатов из FTS5
    FACTS_TOP_K: int = 5           # сколько фактов поднимать из facts-store
    MAX_CONTEXT_CHARS: int = 6000  # лимит символов в retrieval-блоке
    MESSAGE_BURST_DEDUP_SECONDS: int = 5
    MESSAGE_STORAGE_DEDUP_SECONDS: int = 30

    # БД
    DB_PATH: str = "database/sqlite.db"

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


settings = Settings()
