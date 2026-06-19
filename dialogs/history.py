"""
Управление историей диалога (short-term memory).

Хранит последние N сообщений в БД и отдаёт их
в формате [{role, content}] для LLM.
"""
from __future__ import annotations

import logging
from typing import Any

import aiosqlite

from config import settings

log = logging.getLogger(__name__)


async def save_message(
    db: aiosqlite.Connection,
    *,
    user_id: int,
    dialog_id: str,
    role: str,
    text: str,
) -> None:
    await db.execute(
        "INSERT INTO messages (user_id, dialog_id, role, text) VALUES (?,?,?,?)",
        (user_id, dialog_id, role, text),
    )
    await db.commit()


async def get_last_n(
    db: aiosqlite.Connection,
    *,
    user_id: int,
    n: int | None = None,
) -> list[dict[str, Any]]:
    """Возвращает последние n сообщений пользователя в формате [{role, content}]."""
    limit = n or settings.HISTORY_LAST_N
    async with db.execute(
        """
        SELECT role, text FROM messages
        WHERE user_id = ?
        ORDER BY created_at DESC
        LIMIT ?
        """,
        (user_id, limit),
    ) as cur:
        rows = await cur.fetchall()

    # Разворачиваем: БД отдаёт от новых к старым, LLM нужно от старых к новым
    return [{"role": r["role"], "content": r["text"]} for r in reversed(rows)]
