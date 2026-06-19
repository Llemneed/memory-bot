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
    created_at REAL    NOT NULL DEFAULT (unixepoch('now','subsec'))
);
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
        await db.executescript(CREATE_MESSAGES + CREATE_FTS + CREATE_TRIGGERS)
        await db.commit()
