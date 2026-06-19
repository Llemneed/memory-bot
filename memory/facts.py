from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

import aiosqlite

from config import settings

_FIRST_PERSON_PREFIX = re.compile(r"^\s*(я|у меня|мой|моя|моё|мои|меня)\b", re.IGNORECASE)
_QUESTION_PREFIX = re.compile(r"^\s*(как|какой|какая|какие|где|когда|почему|зачем|кто|что|ли)\b", re.IGNORECASE)
_SCHEDULE_VALUE = re.compile(
    r"\b\d{1,2}\s*/\s*\d{1,2}\b|\bмесяц\s+на\s+месяц\b|\bнедел\w+\s+через\s+\w+\b",
    re.IGNORECASE,
)
_NAME = re.compile(r"\bменя\s+зовут\s+(?P<value>[A-ZА-ЯЁ][\w-]+)", re.IGNORECASE)
_PREFERENCE = re.compile(
    r"^(?:(?:я\s+)?(?P<neg>не)\s+)?(?P<verb>люблю|нравит(?:ся|сь)|предпочитаю|обожаю|терпеть\s+не\s+могу|пью|ем)\s+(?P<value>[^.!?\n]+)$",
    re.IGNORECASE,
)
_LIVE_IN = re.compile(r"^я\s+жив[ау]\s+(?:в|на)\s+(?P<value>[^.!?\n]+)$", re.IGNORECASE)
_POSSESSION = re.compile(r"^у\s+меня(?:\s+есть)?\s+(?P<value>[^.!?\n]+)$", re.IGNORECASE)
_MY_IS = re.compile(
    r"^(?:мой|моя|моё|мои)\s+(?P<key>[^\s.!?,]+)(?:\s+(?:это|—|-|зовут))?\s+(?P<value>[^.!?\n]+)$",
    re.IGNORECASE,
)
_I_AM = re.compile(r"^я\s+(?P<value>[^.!?\n]+)$", re.IGNORECASE)
_VERB_PREDICATE = re.compile(
    r"^я\s+(?P<verb>[а-яёa-z-]+(?:ю|у|усь|юсь|аю|яю|уся|юсья|ем|им|аюсь|яюсь|аюсь))\s+(?P<value>[^.!?\n]+)$",
    re.IGNORECASE,
)
_STOPWORDS = {
    "есть",
    "это",
    "мой",
    "моя",
    "моё",
    "мои",
    "у",
    "меня",
    "в",
    "на",
    "по",
    "как",
    "и",
    "а",
}


@dataclass(frozen=True)
class FactCandidate:
    category: str
    key: str
    value: str
    confidence: float = 0.9


def normalize_fact_text(text: str) -> str:
    return " ".join(text.split()).strip().lower()


def extract_facts(text: str) -> list[FactCandidate]:
    source = " ".join(text.split()).strip()
    normalized = normalize_fact_text(text)
    if not normalized or _looks_like_question(normalized) or not _looks_memory_worthy(normalized):
        return []

    candidates = [
        _extract_name(source),
        _extract_preference(source),
        _extract_live_in(source),
        _extract_possession(source),
        _extract_my_is(source),
        _extract_predicate(source),
    ]

    if not any(candidate is not None for candidate in candidates):
        candidates.append(_extract_i_am(source))

    seen: dict[tuple[str, str], FactCandidate] = {}
    for candidate in candidates:
        if candidate is None:
            continue
        seen.setdefault((candidate.category, candidate.key), candidate)
    return list(seen.values())


async def upsert_extracted_facts(
    db: aiosqlite.Connection,
    *,
    user_id: int,
    dialog_id: str,
    text: str,
    source_message_id: int | None,
) -> list[FactCandidate]:
    candidates = extract_facts(text)
    for candidate in candidates:
        await db.execute(
            """
            INSERT INTO facts (
                user_id, dialog_id, category, fact_key, fact_value, normalized_value,
                source_message_id, confidence, status, source_text
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'active', ?)
            ON CONFLICT(user_id, dialog_id, fact_key) DO UPDATE SET
                category = excluded.category,
                fact_value = excluded.fact_value,
                normalized_value = excluded.normalized_value,
                source_message_id = excluded.source_message_id,
                confidence = excluded.confidence,
                status = 'active',
                source_text = excluded.source_text,
                updated_at = unixepoch('now','subsec')
            """,
            (
                user_id,
                dialog_id,
                candidate.category,
                candidate.key,
                candidate.value,
                normalize_fact_text(candidate.value),
                source_message_id,
                candidate.confidence,
                text,
            ),
        )
    if candidates:
        await db.commit()
    return candidates


async def retrieve_facts(
    db: aiosqlite.Connection,
    *,
    user_id: int,
    dialog_id: str,
    query: str,
    top_k: int | None = None,
) -> list[dict[str, Any]]:
    k = top_k or settings.FACTS_TOP_K
    async with db.execute(
        """
        SELECT category, fact_key, fact_value, confidence, source_text, updated_at
        FROM facts
        WHERE user_id = ?
          AND dialog_id = ?
          AND status = 'active'
        ORDER BY updated_at DESC
        """,
        (user_id, dialog_id),
    ) as cur:
        rows = await cur.fetchall()

    if not rows:
        return []

    query_tokens = _query_tokens(query)
    ranked = []
    for row in rows:
        score = _score_fact_row(row, query_tokens=query_tokens)
        ranked.append((score, row))

    positive = [item for item in ranked if item[0] > 0]
    if positive:
        ranked = positive

    ranked.sort(key=lambda item: (item[0], item[1]["updated_at"]), reverse=True)
    return [
        {
            "category": row["category"],
            "key": row["fact_key"],
            "value": row["fact_value"],
            "confidence": row["confidence"],
            "source_text": row["source_text"],
            "updated_at": row["updated_at"],
        }
        for _, row in ranked[:k]
    ]


def build_fact_block(facts: list[dict[str, Any]]) -> str:
    if not facts:
        return ""

    lines = ["=== Подтвержденные факты ==="]
    for fact in facts:
        lines.append(f"- [{fact['category']}] {fact['key']}: {fact['value']}")
    lines.append("=== Конец фактов ===")
    return "\n".join(lines)


def _looks_like_question(text: str) -> bool:
    return text.endswith("?") or _QUESTION_PREFIX.search(text) is not None


def _looks_memory_worthy(text: str) -> bool:
    return _FIRST_PERSON_PREFIX.search(text) is not None or _PREFERENCE.match(text) is not None


def _extract_name(text: str) -> FactCandidate | None:
    match = _NAME.search(text)
    if not match:
        return None
    return FactCandidate(category="attribute", key="имя", value=_cleanup_value(match.group("value")))


def _extract_preference(text: str) -> FactCandidate | None:
    match = _PREFERENCE.match(text)
    if not match:
        return None

    value = _cleanup_value(match.group("value"))
    if not value:
        return None

    sign = "нет" if match.group("neg") else "да"
    key = _derive_key_from_object(value)
    return FactCandidate(category="preference", key=key, value=sign)


def _extract_live_in(text: str) -> FactCandidate | None:
    match = _LIVE_IN.match(text)
    if not match:
        return None
    value = _cleanup_value(match.group("value"))
    value = re.sub(r"^(?:в|на)\s+", "", value, flags=re.IGNORECASE)
    return FactCandidate(category="attribute", key="живу", value=value)


def _extract_possession(text: str) -> FactCandidate | None:
    match = _POSSESSION.match(text)
    if not match:
        return None

    raw_value = _cleanup_value(match.group("value"))
    if not raw_value:
        return None

    if _SCHEDULE_VALUE.search(raw_value):
        return FactCandidate(category="state", key="у меня", value=raw_value)

    tokens = raw_value.split()
    if len(tokens) >= 2 and _looks_like_named_entity(tokens[-1]):
        key = _normalize_key(" ".join(tokens[:-1]))
        value = tokens[-1]
        if key:
            return FactCandidate(category="attribute", key=key, value=value)

    return FactCandidate(category="attribute", key=_normalize_key(tokens[0]), value=" ".join(tokens[1:]) or "есть")


def _extract_my_is(text: str) -> FactCandidate | None:
    match = _MY_IS.match(text)
    if not match:
        return None

    key = _normalize_key(match.group("key"))
    value = _cleanup_value(match.group("value"))
    if not key or not value:
        return None

    return FactCandidate(category="attribute", key=key, value=value)


def _extract_predicate(text: str) -> FactCandidate | None:
    match = _VERB_PREDICATE.match(text)
    if not match:
        return None

    verb = _normalize_key(match.group("verb"))
    value = _cleanup_value(match.group("value"))
    if not verb or not value:
        return None

    category = "state" if _SCHEDULE_VALUE.search(value) else "attribute"
    return FactCandidate(category=category, key=verb, value=value)


def _extract_i_am(text: str) -> FactCandidate | None:
    match = _I_AM.match(text)
    if not match:
        return None

    value = _cleanup_value(match.group("value"))
    if not value or value.count(" ") > 4:
        return None

    return FactCandidate(category="attribute", key="я", value=value)


def _derive_key_from_object(text: str) -> str:
    tokens = [token for token in re.findall(r"[\w-]+", normalize_fact_text(text)) if token not in _STOPWORDS]
    return tokens[0] if tokens else "предпочтение"


def _normalize_key(text: str) -> str:
    tokens = [token for token in re.findall(r"[\w-]+", normalize_fact_text(text)) if token not in _STOPWORDS]
    return " ".join(tokens[:3]).strip()


def _cleanup_value(value: str) -> str:
    cleaned = re.split(r"[.!?\n]", value, maxsplit=1)[0]
    return " ".join(cleaned.split()).strip(" ,-—")


def _looks_like_named_entity(token: str) -> bool:
    if not token:
        return False
    first = token[0]
    return first.isupper() or first in "АБВГДЕЁЖЗИЙКЛМНОПРСТУФХЦЧШЩЭЮЯ"


def _query_tokens(query: str) -> list[str]:
    return [token for token in re.findall(r"[\w-]+", normalize_fact_text(query)) if len(token) > 2]


def _score_fact_row(row: aiosqlite.Row, *, query_tokens: list[str]) -> int:
    haystack = normalize_fact_text(
        f"{row['category']} {row['fact_key']} {row['fact_value']} {row['source_text']}"
    )
    score = sum(2 if token == row["fact_key"] else 1 for token in query_tokens if token in haystack)
    if score == 0 and not query_tokens:
        return 1
    return score
