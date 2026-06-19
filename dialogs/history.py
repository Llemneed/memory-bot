from __future__ import annotations

import asyncio
from typing import Any

import aiosqlite

from config import settings

WRITE_LOCK = asyncio.Lock()


async def save_message(
    db: aiosqlite.Connection,
    *,
    user_id: int,
    dialog_id: str,
    role: str,
    text: str,
) -> None:
    async with WRITE_LOCK:
        await db.execute(
            "INSERT INTO messages (user_id, dialog_id, role, text) VALUES (?,?,?,?)",
            (user_id, dialog_id, role, text),
        )
        await db.commit()


async def reset_history(
    db: aiosqlite.Connection,
    *,
    user_id: int,
) -> None:
    async with WRITE_LOCK:
        await db.execute("DELETE FROM messages WHERE user_id = ?", (user_id,))
        await db.execute("INSERT INTO fts_messages(fts_messages) VALUES('rebuild')")
        await db.commit()


async def get_last_n(
    db: aiosqlite.Connection,
    *,
    user_id: int,
    n: int | None = None,
) -> list[dict[str, Any]]:
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

    return [{"role": row["role"], "content": row["text"]} for row in reversed(rows)]
