"""
Инициализация SQLite + FTS5.

Схема намеренно минимальная:
  messages        — основная таблица
  fts_messages    — FTS5-индекс поверх неё
"""
from __future__ import annotations

from pathlib import Path

import aiosqlite

from config import settings

SQLITE_BUSY_TIMEOUT_MS = 5000

CREATE_MESSAGES = """
CREATE TABLE IF NOT EXISTS messages (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id    INTEGER NOT NULL,
    dialog_id  TEXT    NOT NULL,
    role       TEXT    NOT NULL CHECK(role IN ('user','assistant')),
    text       TEXT    NOT NULL,
    normalized_text TEXT NOT NULL DEFAULT '',
    created_at REAL    NOT NULL DEFAULT (unixepoch('now','subsec'))
);
"""

CREATE_FACTS = """
CREATE TABLE IF NOT EXISTS facts (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id          INTEGER NOT NULL,
    dialog_id        TEXT    NOT NULL,
    category         TEXT    NOT NULL DEFAULT 'attribute',
    fact_key         TEXT    NOT NULL,
    fact_value       TEXT    NOT NULL,
    normalized_value TEXT    NOT NULL,
    source_message_id INTEGER,
    confidence       REAL    NOT NULL DEFAULT 0.9,
    status           TEXT    NOT NULL DEFAULT 'active',
    source_text      TEXT    NOT NULL,
    created_at       REAL    NOT NULL DEFAULT (unixepoch('now','subsec')),
    updated_at       REAL    NOT NULL DEFAULT (unixepoch('now','subsec')),
    UNIQUE(user_id, dialog_id, fact_key)
);

CREATE INDEX IF NOT EXISTS idx_facts_user_dialog_updated
ON facts(user_id, dialog_id, updated_at DESC);
"""

CREATE_FTS = """
CREATE VIRTUAL TABLE IF NOT EXISTS fts_messages
USING fts5(
    text,
    role UNINDEXED,
    user_id UNINDEXED,
    dialog_id UNINDEXED,
    created_at UNINDEXED,
    content='messages',
    content_rowid='id',
    tokenize='unicode61'
);
"""

# Триггеры для синхронизации FTS с основной таблицей
CREATE_TRIGGERS = """
CREATE TRIGGER IF NOT EXISTS fts_ai AFTER INSERT ON messages BEGIN
    INSERT INTO fts_messages(rowid, text, role, user_id, dialog_id, created_at)
    VALUES (new.id, new.text, new.role, new.user_id, new.dialog_id, new.created_at);
END;

CREATE TRIGGER IF NOT EXISTS fts_ad AFTER DELETE ON messages BEGIN
    INSERT INTO fts_messages(fts_messages, rowid, text, role, user_id, dialog_id, created_at)
    VALUES ('delete', old.id, old.text, old.role, old.user_id, old.dialog_id, old.created_at);
END;

CREATE TRIGGER IF NOT EXISTS fts_au AFTER UPDATE ON messages BEGIN
    INSERT INTO fts_messages(fts_messages, rowid, text, role, user_id, dialog_id, created_at)
    VALUES ('delete', old.id, old.text, old.role, old.user_id, old.dialog_id, old.created_at);
    INSERT INTO fts_messages(rowid, text, role, user_id, dialog_id, created_at)
    VALUES (new.id, new.text, new.role, new.user_id, new.dialog_id, new.created_at);
END;
"""


async def get_db() -> aiosqlite.Connection:
    Path(settings.DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    db = await aiosqlite.connect(settings.DB_PATH)
    await db.execute("PRAGMA journal_mode=WAL")
    await db.execute("PRAGMA foreign_keys=ON")
    await db.execute(f"PRAGMA busy_timeout={SQLITE_BUSY_TIMEOUT_MS}")
    db.row_factory = aiosqlite.Row
    return db


async def init_db() -> None:
    Path(settings.DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    async with aiosqlite.connect(settings.DB_PATH) as db:
        await db.execute("PRAGMA journal_mode=WAL")
        await db.execute(f"PRAGMA busy_timeout={SQLITE_BUSY_TIMEOUT_MS}")
        await db.executescript(CREATE_MESSAGES + CREATE_FACTS + CREATE_FTS + CREATE_TRIGGERS)
        await _ensure_messages_schema(db)
        await _ensure_facts_schema(db)
        await db.commit()


async def _ensure_messages_schema(db: aiosqlite.Connection) -> None:
    async with db.execute("PRAGMA table_info(messages)") as cur:
        columns = {row[1] for row in await cur.fetchall()}

    if "normalized_text" not in columns:
        await db.execute(
            "ALTER TABLE messages ADD COLUMN normalized_text TEXT NOT NULL DEFAULT ''"
        )
        await db.execute(
            "UPDATE messages SET normalized_text = lower(trim(text)) WHERE normalized_text = ''"
        )


async def _ensure_facts_schema(db: aiosqlite.Connection) -> None:
    async with db.execute("PRAGMA table_info(facts)") as cur:
        columns = {row[1] for row in await cur.fetchall()}

    if "category" not in columns:
        await db.execute(
            "ALTER TABLE facts ADD COLUMN category TEXT NOT NULL DEFAULT 'attribute'"
        )
    if "source_message_id" not in columns:
        await db.execute("ALTER TABLE facts ADD COLUMN source_message_id INTEGER")
    if "status" not in columns:
        await db.execute(
            "ALTER TABLE facts ADD COLUMN status TEXT NOT NULL DEFAULT 'active'"
        )
