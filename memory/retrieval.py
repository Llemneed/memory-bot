"""
SQLite FTS retrieval helpers.

This layer is only a raw-history fallback. We keep it useful by skipping
duplicate entries and old user questions that tend to pollute the prompt.
"""
from __future__ import annotations

import logging
import re
from typing import Any

import aiosqlite

from config import settings
from dialogs.history import normalize_message_text

log = logging.getLogger(__name__)

_FTS_SPECIAL = re.compile(r'["\'()\[\]{}:*^]')
_QUESTION_PREFIX = re.compile(
    r"^\s*((?:по|на|в)\s+)?"
    r"(как|какой|какая|какие|какому|какой|каких|каким|где|когда|почему|зачем|"
    r"кто|что|ли|кем|чем|сколько)\b",
    re.IGNORECASE,
)


def _sanitize_query(text: str) -> str:
    cleaned = _FTS_SPECIAL.sub(" ", text)
    words = cleaned.split()[:10]
    return " OR ".join(f'"{word}"' for word in words if len(word) > 2)


def _looks_like_question(text: str) -> bool:
    normalized = normalize_message_text(text)
    return normalized.endswith("?") or _QUESTION_PREFIX.search(normalized) is not None


async def retrieve(
    db: aiosqlite.Connection,
    *,
    user_id: int,
    query: str,
    top_k: int | None = None,
    exclude_text: str | None = None,
) -> list[dict[str, Any]]:
    k = top_k or settings.RETRIEVAL_TOP_K
    fts_query = _sanitize_query(query)
    excluded_normalized = normalize_message_text(exclude_text or "")

    if not fts_query:
        return []

    try:
        fetch_limit = max(k * 4, k)
        async with db.execute(
            """
            SELECT m.role, m.text, m.created_at,
                   bm25(fts_messages) AS score
            FROM fts_messages
            JOIN messages m ON m.id = fts_messages.rowid
            WHERE fts_messages MATCH ?
              AND m.user_id = ?
              AND (? = '' OR m.normalized_text <> ?)
            ORDER BY score
            LIMIT ?
            """,
            (fts_query, user_id, excluded_normalized, excluded_normalized, fetch_limit),
        ) as cur:
            rows = await cur.fetchall()

        results: list[dict[str, Any]] = []
        seen_normalized: set[str] = set()
        for role, text, created_at, score in rows:
            normalized_text = normalize_message_text(text)
            if not normalized_text or normalized_text in seen_normalized:
                continue
            seen_normalized.add(normalized_text)

            if role == "user" and _looks_like_question(text):
                continue

            results.append(
                {
                    "role": role,
                    "text": text,
                    "created_at": created_at,
                    "score": score,
                }
            )
            if len(results) >= k:
                break

        return results
    except aiosqlite.OperationalError as exc:
        log.warning("FTS retrieval failed: %s", exc)
        return []
