"""
Context Builder.

Собирает retrieval-результаты в текстовый блок,
который вставляется в system prompt.
Применяет constraints по размеру.
"""
from __future__ import annotations

import datetime
from typing import Any

from config import settings


def build_memory_block(retrieved: list[dict[str, Any]]) -> str:
    """
    Превращает список найденных сообщений в текстовый блок памяти.
    Возвращает пустую строку, если нечего показывать.
    """
    if not retrieved:
        return ""

    lines: list[str] = ["=== Из прошлых разговоров ==="]
    total_chars = 0

    for item in retrieved:
        role_label = "Пользователь" if item["role"] == "user" else "Ассистент"
        ts = _fmt_ts(item.get("created_at"))
        line = f"[{ts}] {role_label}: {item['text']}"

        if total_chars + len(line) > settings.MAX_CONTEXT_CHARS:
            break

        lines.append(line)
        total_chars += len(line)

    if len(lines) == 1:  # только заголовок — ничего не добавилось
        return ""

    lines.append("=== Конец памяти ===")
    return "\n".join(lines)


def _fmt_ts(ts: float | None) -> str:
    if ts is None:
        return "?"
    try:
        return datetime.datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M")
    except (OSError, ValueError):
        return "?"
