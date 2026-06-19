"""
Constraints — защита от переполнения контекста.

Обрезает историю и retrieval до безопасных размеров.
"""
from __future__ import annotations

from config import settings

# Грубая оценка: 1 токен ≈ 4 символа
_CHARS_PER_TOKEN = 4
_MAX_HISTORY_CHARS = 4000


def trim_history(messages: list[dict]) -> list[dict]:
    """
    Обрезает историю диалога справа налево,
    чтобы суммарный размер не превышал лимит.
    Первое сообщение (system) всегда сохраняется.
    """
    if not messages:
        return messages

    system = [m for m in messages if m["role"] == "system"]
    rest = [m for m in messages if m["role"] != "system"]
    if not rest:
        return system

    # Always keep the latest non-system message so the current user request
    # never disappears from context even when the conversation gets long.
    kept = [rest[-1]]
    total = len(rest[-1].get("content", ""))

    for msg in reversed(rest[:-1]):
        size = len(msg.get("content", ""))
        if total + size > _MAX_HISTORY_CHARS:
            break
        kept.insert(0, msg)
        total += size

    return system + kept


def trim_retrieval_block(block: str) -> str:
    """Обрезает блок памяти до MAX_CONTEXT_CHARS символов."""
    if len(block) <= settings.MAX_CONTEXT_CHARS:
        return block
    return block[: settings.MAX_CONTEXT_CHARS] + "\n[...обрезано...]"
