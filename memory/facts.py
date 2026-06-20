from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

import aiosqlite

from config import settings

_FIRST_PERSON_PREFIX = re.compile(
    r"^\s*(я|у меня|мой|моя|моё|мои|меня)\b",
    re.IGNORECASE,
)
_QUESTION_PREFIX = re.compile(
    r"^\s*((?:по|на|в)\s+)?(как|какой|какая|какие|какому|какой|каких|каким|где|когда|почему|зачем|кто|что|ли|кем|чем|сколько)\b",
    re.IGNORECASE,
)
_DISCOURSE_PREFIX = re.compile(
    r"^\s*(?:нет|да|ну|так|слушай|смотри|короче|блин|блять|ладно|вообще|значит)\s*[,:\-]?\s*",
    re.IGNORECASE,
)
_SCHEDULE_VALUE = re.compile(
    r"\b\d{1,2}\s*/\s*\d{1,2}\b|\bмесяц\s+на\s+месяц\b|\bкаждый\s+день\b|\bчерез\s+месяц\b",
    re.IGNORECASE,
)
_TIME_MARKER = re.compile(
    r"\b\d{1,2}\b|\b\d{1,2}\s*(?:час|часа|часов|день|дня|дней|месяц|месяца|месяцев)\b|"
    r"\b(?:час|часа|часов|день|дня|дней|недел\w*|месяц|месяца|месяцев|год|года|лет|числа|смена|смены|смен)\b",
    re.IGNORECASE,
)
_NAME = re.compile(r"\bменя\s+зовут\s+(?P<value>[A-ZА-ЯЁ][\w-]+)", re.IGNORECASE)
_PREFERENCE = re.compile(
    r"^(?:(?:я\s+)?(?P<neg>не)\s+)?(?P<verb>люблю|нравит(?:ся|сь)|предпочитаю|обожаю|терпеть\s+не\s+могу|пью|ем)\s+(?P<value>[^.!?\n]+)$",
    re.IGNORECASE,
)
_LIVE_IN = re.compile(r"^я\s+жив[ау]\s+(?:в|на)\s+(?P<value>[^.!?\n]+)$", re.IGNORECASE)
_POSSESSION = re.compile(r"^у\s+меня(?:\s+есть)?\s+(?P<value>[^.!?\n]+)$", re.IGNORECASE)
_TOPIC_POSSESSION = re.compile(
    r"^(?P<key>[A-Za-zА-Яа-яЁё-]+(?:\s+[A-Za-zА-Яа-яЁё-]+){0,2})\s+у\s+меня\s+(?P<value>[^.!?\n]+)$",
    re.IGNORECASE,
)
_MY_IS = re.compile(
    r"^(?:мой|моя|моё|мои)\s+(?P<key>[^\s.!?,]+)(?:\s+(?:это|—|-|зовут))?\s+(?P<value>[^.!?\n]+)$",
    re.IGNORECASE,
)
_I_AM = re.compile(r"^я\s+(?P<value>[^.!?\n]+)$", re.IGNORECASE)
_VERB_ENDING = r"(?:ю|у|усь|юсь|аю|яю|ем|им|аюсь|яюсь|аем|яем|ут|ют|ет)"
_VERB_PREDICATE = re.compile(
    rf"^я\s+(?P<verb>[а-яёa-z-]+{_VERB_ENDING})\s+(?P<value>[^.!?\n]+)$",
    re.IGNORECASE,
)
_BARE_VERB_PREDICATE = re.compile(
    rf"^(?P<verb>[а-яёa-z-]+{_VERB_ENDING})\s+(?P<value>[^.!?\n]+)$",
    re.IGNORECASE,
)
_TOPIC_VALUE = re.compile(
    r"^(?P<key>[A-Za-zА-Яа-яЁё-]+(?:\s+[A-Za-zА-Яа-яЁё-]+){0,1})\s+(?P<value>[^.!?\n]+)$",
    re.IGNORECASE,
)
_ROUTE_MOTION = re.compile(
    r"\b(еду|езжу|добираюсь|доезжаю|лечу|летаю|выезжаю|отправляюсь)\b",
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
    "с",
    "до",
    "от",
}


@dataclass(frozen=True)
class FactCandidate:
    category: str
    key: str
    value: str
    source_text: str
    confidence: float = 0.9


def normalize_fact_text(text: str) -> str:
    return " ".join(text.split()).strip().lower()


def extract_facts(text: str) -> list[FactCandidate]:
    source = " ".join(text.split()).strip()
    if not source:
        return []

    seen: dict[tuple[str, str], FactCandidate] = {}
    for candidate in _extract_document_facts(source):
        seen[(candidate.category, candidate.key)] = candidate

    for clause in _iter_candidate_clauses(source):
        raw_clause = clause.strip()
        normalized = normalize_fact_text(raw_clause)
        if not normalized or _looks_like_question(normalized):
            continue

        cleaned_clause = _strip_discourse_prefix(raw_clause)
        normalized_cleaned = normalize_fact_text(cleaned_clause)
        if not normalized_cleaned or _looks_like_question(normalized_cleaned):
            continue
        if _looks_like_correction_rejection(normalized_cleaned):
            continue
        cleaned_clause = cleaned_clause.strip(" ,.!?;")
        if not _looks_memory_worthy(normalized_cleaned):
            continue

        candidates = _extract_clause_facts(cleaned_clause)

        for candidate in candidates:
            if candidate is None:
                continue
            seen[(candidate.category, candidate.key)] = candidate

    return list(seen.values())


def _extract_document_facts(text: str) -> list[FactCandidate]:
    if _looks_like_question(normalize_fact_text(text)):
        return []
    route = _extract_route(text)
    return [route] if route is not None else []


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
                candidate.source_text,
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


async def list_active_facts(
    db: aiosqlite.Connection,
    *,
    user_id: int,
    dialog_id: str,
) -> list[dict[str, Any]]:
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

    return [
        {
            "category": row["category"],
            "key": row["fact_key"],
            "value": row["fact_value"],
            "confidence": row["confidence"],
            "source_text": row["source_text"],
            "updated_at": row["updated_at"],
        }
        for row in rows
    ]


def build_fact_block(facts: list[dict[str, Any]]) -> str:
    if not facts:
        return ""

    lines = ["=== Confirmed facts ==="]
    for fact in facts:
        lines.append(
            f"- [{fact['category']}] {_fact_label_for_display(fact['key'])}: {fact['value']}"
        )
    lines.append("=== End facts ===")
    return "\n".join(lines)


def build_fact_answer_block(facts: list[dict[str, Any]]) -> str:
    if not facts:
        return ""

    lines = ["=== Facts for this answer ==="]
    for fact in facts:
        lines.append(f"- {_fact_label_for_display(fact['key'])}: {fact['value']}")
    lines.append("=== End answer facts ===")
    return "\n".join(lines)


def _fact_label_for_display(key: str) -> str:
    canonical_key = _canonical_fact_key(key)
    labels = {
        "маршрут": "маршрут",
        "работаю": "вахтовый цикл",
        "роль": "роль / профессия",
        "живу": "место проживания",
        "место работы": "место работы",
        "вахта": "длительность вахты",
        "график": "длительность смены",
        "режим": "режим / правило",
        "одна вахта": "чередование вахт",
        "завтрак с": "расписание питания",
        "у меня": "режим",
    }
    return labels.get(canonical_key, canonical_key)


def _extract_clause_facts(text: str) -> list[FactCandidate | None]:
    for extractor in (
        _extract_name,
        _extract_preference,
        _extract_live_in,
        _extract_topic_possession,
        _extract_possession,
        _extract_my_is,
        _extract_predicate,
        _extract_topic_value,
        _extract_temporal_fragment,
        _extract_i_am,
    ):
        candidate = extractor(text)
        if candidate is not None:
            return [candidate]
    return []


def _extract_route(text: str) -> FactCandidate | None:
    normalized = normalize_fact_text(text)
    if _ROUTE_MOTION.search(normalized) is None:
        return None
    if "из " not in normalized and "через " not in normalized and "до " not in normalized:
        return None

    cleaned = _cleanup_route_value(text)
    if not cleaned or len(cleaned.split()) < 4:
        return None

    return FactCandidate(
        category="attribute",
        key="маршрут",
        value=cleaned,
        source_text=text,
        confidence=0.88,
    )


def _iter_candidate_clauses(text: str) -> list[str]:
    parts = [
        part.strip()
        for part in re.findall(r"[^.!?;\n]+[.!?;\n]*", text)
        if part.strip(" ,.!?;\n")
    ]
    return parts or [text.strip()]


def _strip_discourse_prefix(text: str) -> str:
    cleaned = text.strip()
    while True:
        updated = _DISCOURSE_PREFIX.sub("", cleaned, count=1).strip()
        if updated == cleaned:
            return cleaned
        cleaned = updated


def _looks_like_question(text: str) -> bool:
    return text.endswith("?") or _QUESTION_PREFIX.search(text) is not None


def _looks_memory_worthy(text: str) -> bool:
    return (
        _FIRST_PERSON_PREFIX.search(text) is not None
        or _PREFERENCE.match(text) is not None
        or _BARE_VERB_PREDICATE.match(text) is not None
        or _TOPIC_POSSESSION.match(text) is not None
        or _looks_like_temporal_state(text)
        or _looks_like_topic_value(text)
    )


def _looks_like_correction_rejection(text: str) -> bool:
    return text.startswith("не ") and " а " in text


def _extract_name(text: str) -> FactCandidate | None:
    match = _NAME.search(text)
    if not match:
        return None
    return FactCandidate(
        category="attribute",
        key="имя",
        value=_cleanup_value(match.group("value")),
        source_text=text,
    )


def _extract_preference(text: str) -> FactCandidate | None:
    match = _PREFERENCE.match(text)
    if not match:
        return None

    value = _cleanup_value(match.group("value"))
    if not value:
        return None

    sign = "нет" if match.group("neg") else "да"
    key = _derive_key_from_object(value)
    return FactCandidate(category="preference", key=key, value=sign, source_text=text)


def _extract_live_in(text: str) -> FactCandidate | None:
    match = _LIVE_IN.match(text)
    if not match:
        return None
    value = _cleanup_value(match.group("value"))
    value = re.sub(r"^(?:в|на)\s+", "", value, flags=re.IGNORECASE)
    return FactCandidate(category="attribute", key="живу", value=value, source_text=text)


def _extract_topic_possession(text: str) -> FactCandidate | None:
    match = _TOPIC_POSSESSION.match(text)
    if not match:
        return None

    key = _normalize_key(match.group("key"))
    value = _cleanup_value(match.group("value"))
    if not key or not value:
        return None

    category = "state" if _looks_like_temporal_state(value) else "attribute"
    return FactCandidate(category=category, key=key, value=value, source_text=text, confidence=0.85)


def _extract_possession(text: str) -> FactCandidate | None:
    match = _POSSESSION.match(text)
    if not match:
        return None

    raw_value = _cleanup_value(match.group("value"))
    if not raw_value:
        return None

    if _looks_like_temporal_state(raw_value):
        return FactCandidate(category="state", key="у меня", value=raw_value, source_text=text, confidence=0.8)

    tokens = raw_value.split()
    if len(tokens) >= 2 and _looks_like_named_entity(tokens[-1]):
        key = _normalize_key(" ".join(tokens[:-1]))
        value = tokens[-1]
        if key:
            return FactCandidate(category="attribute", key=key, value=value, source_text=text)

    return FactCandidate(
        category="attribute",
        key=_normalize_key(tokens[0]),
        value=" ".join(tokens[1:]) or "есть",
        source_text=text,
        confidence=0.8,
    )


def _extract_my_is(text: str) -> FactCandidate | None:
    match = _MY_IS.match(text)
    if not match:
        return None

    key = _normalize_key(match.group("key"))
    value = _cleanup_value(match.group("value"))
    if not key or not value:
        return None

    return FactCandidate(category="attribute", key=key, value=value, source_text=text)


def _extract_predicate(text: str) -> FactCandidate | None:
    match = _VERB_PREDICATE.match(text) or _BARE_VERB_PREDICATE.match(text)
    if not match:
        return None

    verb = _normalize_key(match.group("verb"))
    value = _cleanup_value(match.group("value"))
    if not verb or not value:
        return None

    category = "state" if _looks_like_temporal_state(value) else "attribute"
    key = verb
    if category == "attribute" and _looks_like_role(value):
        key = "роль"
    elif category == "attribute" and _looks_like_location_phrase(value):
        key = f"{verb}:place"

    return FactCandidate(category=category, key=key, value=value, source_text=text)


def _extract_topic_value(text: str) -> FactCandidate | None:
    match = _TOPIC_VALUE.match(text)
    if not match:
        return None

    key = _normalize_key(match.group("key"))
    value = _cleanup_value(match.group("value"))
    if not key or not value or not _looks_like_topic_value(text):
        return None

    category = "state" if _looks_like_temporal_state(value) else "attribute"
    return FactCandidate(category=category, key=key, value=value, source_text=text, confidence=0.75)


def _extract_temporal_fragment(text: str) -> FactCandidate | None:
    if not _looks_like_temporal_state(text):
        return None
    return FactCandidate(category="state", key="режим", value=_cleanup_value(text), source_text=text, confidence=0.7)


def _extract_i_am(text: str) -> FactCandidate | None:
    match = _I_AM.match(text)
    if not match:
        return None

    value = _cleanup_value(match.group("value"))
    if not value or value.count(" ") > 4:
        return None

    return FactCandidate(category="attribute", key="я", value=value, source_text=text, confidence=0.7)


def _derive_key_from_object(text: str) -> str:
    tokens = [token for token in re.findall(r"[\w-]+", normalize_fact_text(text)) if token not in _STOPWORDS]
    return tokens[0] if tokens else "предпочтение"


def _normalize_key(text: str) -> str:
    tokens = [token for token in re.findall(r"[\w-]+", normalize_fact_text(text)) if token not in _STOPWORDS]
    return " ".join(tokens[:3]).strip()


def _cleanup_value(value: str) -> str:
    cleaned = re.split(r"[.!?\n]", value, maxsplit=1)[0]
    return " ".join(cleaned.split()).strip(" ,-—")


def _cleanup_route_value(value: str) -> str:
    cleaned = " ".join(value.split()).strip(" ,-—")
    cleaned = re.sub(r"\bоттуда уже\b", "оттуда", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(
        r"\b(?:сначала,?\s*)?я\s+(еду|езжу|добираюсь|доезжаю|лечу|летаю)\b",
        r"\1",
        cleaned,
        flags=re.IGNORECASE,
    )
    cleaned = re.sub(r"\s+,", ",", cleaned)
    return cleaned.strip(" .,!?:;")


def _looks_like_named_entity(token: str) -> bool:
    if not token:
        return False
    first = token[0]
    return first.isupper() or first in "АБВГДЕЁЖЗИЙКЛМНОПРСТУФХЦЧШЩЭЮЯ"


def _looks_like_temporal_state(text: str) -> bool:
    normalized = normalize_fact_text(text)
    return _SCHEDULE_VALUE.search(normalized) is not None or _TIME_MARKER.search(normalized) is not None


def _looks_like_role(value: str) -> bool:
    normalized = normalize_fact_text(value)
    tokens = normalized.split()
    if not tokens or len(tokens) > 5:
        return False
    return any(
        token.endswith(suffix)
        for token in tokens
        for suffix in ("ом", "ем", "ой", "ою", "ым", "им", "ией", "ией", "ами", "ями")
    )


def _looks_like_location_phrase(value: str) -> bool:
    return re.match(r"^(?:в|на|из|у|под)\s+", normalize_fact_text(value)) is not None


def _looks_like_topic_value(text: str) -> bool:
    match = _TOPIC_VALUE.match(text)
    if not match:
        return False
    key = _normalize_key(match.group("key"))
    value = _cleanup_value(match.group("value"))
    if not key or not value:
        return False
    if len(key) <= 1:
        return False
    if key in {"место", "оттуда", "оттуда уже", "туда", "сюда", "здесь"}:
        return False
    if key in {"день", "дни", "месяц", "месяцы", "час", "часы", "число", "числа"}:
        return False
    if _looks_like_temporal_state(value) or _looks_like_role(value) or _looks_like_location_phrase(value):
        return True
    return bool(re.search(r"\d", value)) or len(value.split()) <= 6


def _query_tokens(query: str) -> list[str]:
    return [token for token in re.findall(r"[\w-]+", normalize_fact_text(query)) if len(token) > 2]


def _score_fact_row(row: aiosqlite.Row, *, query_tokens: list[str]) -> int:
    canonical_key = _canonical_fact_key(row["fact_key"])
    raw_key = normalize_fact_text(row["fact_key"])
    haystack = normalize_fact_text(
        f"{row['category']} {raw_key} {canonical_key} {row['fact_value']} {row['source_text']}"
    )
    score = sum(2 if token in {canonical_key, raw_key} else 1 for token in query_tokens if token in haystack)
    score += _intent_adjustment(row, query_tokens=query_tokens)
    if score == 0 and not query_tokens:
        return 1
    return score


def _display_fact_key(key: str) -> str:
    canonical_key = _canonical_fact_key(key)
    labels = {
        "работаю": "вахтовый цикл",
        "роль": "роль / профессия",
        "живу": "место проживания",
        "вахта": "длительность вахты",
        "график": "длительность смены",
        "режим": "режим / правило",
        "одна вахта": "чередование вахт",
        "завтрак с": "расписание питания",
        "у меня": "режим",
    }
    return labels.get(canonical_key, canonical_key)


def _display_fact_key(key: str) -> str:
    canonical_key = _canonical_fact_key(key)
    labels = {
        "работаю": "вахтовый цикл",
        "роль": "роль / профессия",
        "живу": "место проживания",
        "вахта": "длительность вахты",
        "график": "длительность смены",
        "режим": "режим / правило",
        "одна вахта": "чередование вахт",
        "завтрак с": "расписание питания",
        "у меня": "режим",
    }
    return labels.get(canonical_key, canonical_key)


def _display_fact_key(key: str) -> str:
    canonical_key = _canonical_fact_key(key)
    labels = {
        "работаю": "вахтовый цикл",
        "роль": "роль / профессия",
        "живу": "место проживания",
        "вахта": "длительность вахты",
        "график": "длительность смены",
        "режим": "режим / правило",
        "одна вахта": "чередование вахт",
        "завтрак с": "расписание питания",
        "у меня": "режим",
    }
    return labels.get(canonical_key, canonical_key)


def _canonical_fact_key(key: str) -> str:
    if key.endswith(":role"):
        return "роль"
    if key.endswith(":place"):
        return "место работы"
    return key


def _display_fact_key(key: str) -> str:
    canonical_key = _canonical_fact_key(key)
    labels = {
        "работаю": "вахтовый цикл",
        "роль": "роль / профессия",
        "живу": "место проживания",
        "график": "длительность смены",
        "режим": "режим / правило",
        "одна вахта": "чередование дневной и ночной смены",
        "завтрак с": "расписание питания",
        "у меня": "режим",
    }
    return labels.get(canonical_key, canonical_key)


def _intent_adjustment(row: aiosqlite.Row, *, query_tokens: list[str]) -> int:
    canonical_key = _canonical_fact_key(row["fact_key"])
    token_set = set(query_tokens)

    asks_about_route = bool(
        token_set
        & {
            "маршрут",
            "маршрутом",
            "добираюсь",
            "добраться",
            "доезжаю",
            "еду",
            "езжу",
            "путь",
            "дорога",
            "образом",
        }
    )
    asks_about_method = bool(
        token_set
        & {"метод", "методу", "график", "графику", "расписание", "расписанию", "вахта", "вахтовый", "смена", "смены"}
    )
    asks_about_role = bool(
        token_set & {"роль", "профессия", "профессию", "работа", "работаю", "электромонтер", "кем"}
    )
    asks_about_place = bool(
        token_set & {"где", "живу", "место", "месторождение", "мессояхе", "мессояхском"}
    )

    score = 0
    if asks_about_route:
        if canonical_key == "маршрут":
            score += 9
        elif canonical_key == "место работы":
            score += 4
        elif canonical_key == "живу":
            score += 2
        elif row["category"] == "state":
            score -= 3
        else:
            score -= 1

    if asks_about_method:
        if row["category"] == "state" or canonical_key in {"работаю", "график", "режим", "одна вахта", "завтрак с", "у меня"}:
            score += 4
        if canonical_key == "роль":
            score -= 4

    if asks_about_role:
        if canonical_key == "роль":
            score += 5
        elif row["category"] == "state":
            score -= 1

    if asks_about_place:
        if canonical_key == "живу":
            score += 5
        elif canonical_key == "место работы":
            score += 4
        elif canonical_key == "роль":
            score -= 1

    return score
