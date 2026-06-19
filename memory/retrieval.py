"""
Retrieval через SQLite FTS5.

Ищет релевантные сообщения из всей истории пользователя
по ключевым словам текущего запроса.
"""
from __future__ import annotations

import logging
import re
from typing import Any

import aiosqlite

from config import settings

log = logging.getLogger(__name__)

# Символы, которые нужно экранировать в FTS5-запросе
_FTS_SPECIAL = re.compile(r'["\'\(\)\[\]\{\}\:\*\^]')


def _sanitize_query(text: str) -> str:
    """Убирает спецсимволы FTS5, берём первые 10 слов."""
    cleaned = _FTS_SPECIAL.sub(" ", text)
    words = cleaned.split()[:10]
    # Оборачиваем каждое слово в кавычки для точного поиска токенов
    return " OR ".join(f'"{w}"' for w in words if len(w) > 2)


async def retrieve(
    db: aiosqlite.Connection,
    *,
    user_id: int,
    query: str,
    top_k: int | None = None,
) -> list[dict[str, Any]]:
    """
    Возвращает top_k релевантных сообщений из истории пользователя.
    Результат: [{role, text, created_at, score}]
    """
    k = top_k or settings.RETRIEVAL_TOP_K
    fts_query = _sanitize_query(query)

    if not fts_query:
        return []

    try:
        async with db.execute(
            """
            SELECT m.role, m.text, m.created_at,
                   bm25(fts_messages) AS score
            FROM fts_messages
            JOIN messages m ON m.id = fts_messages.rowid
            WHERE fts_messages MATCH ?
              AND m.user_id = ?
            ORDER BY score
            LIMIT ?
            """,
            (fts_query, user_id, k),
        ) as cur:
            rows = await cur.fetchall()
        return [{"role": r[0], "text": r[1], "created_at": r[2], "score": r[3]} for r in rows]
    except aiosqlite.OperationalError as e:
        log.warning("FTS retrieval failed: %s", e)
        return []
