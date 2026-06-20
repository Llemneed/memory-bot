from __future__ import annotations

import asyncio
import re
import time
from typing import Any

import aiosqlite

from config import settings

WRITE_LOCK = asyncio.Lock()
_QUESTION_PREFIX = re.compile(
    r"^\s*((?:по|на|в)\s+)?"
    r"(как|какой|какая|какие|какому|какой|каких|каким|где|когда|почему|зачем|"
    r"кто|что|ли|кем|чем|сколько)\b",
    re.IGNORECASE,
)


def normalize_message_text(text: str) -> str:
    return " ".join(text.split()).strip().lower()


def is_question_like(text: str) -> bool:
    normalized = normalize_message_text(text)
    return normalized.endswith("?") or _QUESTION_PREFIX.search(normalized) is not None


async def save_message(
    db: aiosqlite.Connection,
    *,
    user_id: int,
    dialog_id: str,
    role: str,
    text: str,
) -> int | None:
    normalized_text = normalize_message_text(text)
    async with WRITE_LOCK:
        if settings.MESSAGE_STORAGE_DEDUP_SECONDS > 0:
            cutoff = time.time() - settings.MESSAGE_STORAGE_DEDUP_SECONDS
            async with db.execute(
                """
                SELECT 1
                FROM messages
                WHERE user_id = ?
                  AND dialog_id = ?
                  AND role = ?
                  AND normalized_text = ?
                  AND created_at >= ?
                LIMIT 1
                """,
                (user_id, dialog_id, role, normalized_text, cutoff),
            ) as cur:
                duplicate = await cur.fetchone()
            if duplicate:
                return None

        cur = await db.execute(
            """
            INSERT INTO messages (user_id, dialog_id, role, text, normalized_text)
            VALUES (?,?,?,?,?)
            """,
            (user_id, dialog_id, role, text, normalized_text),
        )
        await db.commit()
    return cur.lastrowid


async def reset_history(
    db: aiosqlite.Connection,
    *,
    user_id: int,
) -> None:
    async with WRITE_LOCK:
        await db.execute("DELETE FROM messages WHERE user_id = ?", (user_id,))
        await db.execute("DELETE FROM facts WHERE user_id = ?", (user_id,))
        await db.execute("INSERT INTO fts_messages(fts_messages) VALUES('rebuild')")
        await db.commit()


async def get_last_n(
    db: aiosqlite.Connection,
    *,
    user_id: int,
    n: int | None = None,
    include_assistant: bool = True,
    include_questions: bool = True,
) -> list[dict[str, Any]]:
    limit = n or settings.HISTORY_LAST_N
    fetch_limit = max(limit * 4, limit)
    role_filter = "" if include_assistant else "AND role = 'user'"
    async with db.execute(
        f"""
        SELECT role, text FROM messages
        WHERE user_id = ?
          {role_filter}
        ORDER BY created_at DESC
        LIMIT ?
        """,
        (user_id, fetch_limit),
    ) as cur:
        rows = await cur.fetchall()

    filtered_desc: list[dict[str, Any]] = []
    seen_normalized: set[tuple[str, str]] = set()
    for row in rows:
        role = row["role"]
        text = row["text"]
        normalized = normalize_message_text(text)
        if not normalized:
            continue
        if not include_questions and role == "user" and is_question_like(text):
            continue
        dedupe_key = (role, normalized)
        if dedupe_key in seen_normalized:
            continue
        seen_normalized.add(dedupe_key)
        filtered_desc.append({"role": role, "content": text})
        if len(filtered_desc) >= limit:
            break

    return list(reversed(filtered_desc))
