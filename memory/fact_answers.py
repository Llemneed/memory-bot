from __future__ import annotations

import re


def maybe_build_fact_answer(query: str, facts: list[dict]) -> str | None:
    if not facts:
        return None

    query_tokens = set(_query_tokens(query))
    query_text = _normalize_text(query)
    fact_map = _fact_map(facts)

    asks_role = bool(query_tokens & {"кем", "профессия", "роль", "должность"})
    asks_place = bool(query_tokens & {"где", "живу", "мессояхе", "мессояхском", "месторождении"})
    asks_work_place = "где" in query_tokens and any(token.startswith("работ") for token in query_tokens)
    asks_method = (
        _has_prefix(query_tokens, "метод")
        or _has_prefix(query_tokens, "график")
        or _has_prefix(query_tokens, "расписан")
        or _has_prefix(query_tokens, "вахт")
        or _has_prefix(query_tokens, "смен")
    )
    asks_why_day_night = (
        "почему" in query_tokens
        and (
            "день" in query_tokens
            or "ночь" in query_tokens
            or _has_prefix(query_tokens, "ночн")
            or _has_prefix(query_tokens, "дневн")
        )
    )
    mentions_food = bool(query_tokens & {"ужин", "завтрак", "обед", "питание"})

    if asks_role and fact_map.get("роль"):
        if "профессия" in query_tokens or "должность" in query_tokens:
            return f"По профессии ты {_role_nominative(fact_map['роль'])}."
        return f"Работаешь {fact_map['роль']}."

    if asks_work_place:
        parts: list[str] = []
        if fact_map.get("живу"):
            parts.append(f"Отдельно место работы ты не называл. Точно знаю только, что живешь {_place_tail(fact_map['живу'])}.")
        else:
            parts.append("Отдельно место работы ты не называл.")
        return " ".join(parts)

    if asks_why_day_night and fact_map.get("вахта") and fact_map.get("одна вахта"):
        parts = [
            "Потому что у тебя чередуются не смены внутри суток, а сами вахты: "
            f"{_watch_alternation_clause(fact_map['одна вахта'])}."
        ]
        parts.append(_watch_duration_sentence(fact_map["вахта"]))
        if fact_map.get("график"):
            parts.append(_shift_duration_sentence(fact_map["график"]))
        elif fact_map.get("режим"):
            parts.append(_shift_duration_sentence(fact_map["режим"]))
        return " ".join(parts)

    if asks_method or asks_place or mentions_food:
        if asks_place and not asks_method and not mentions_food and fact_map.get("живу"):
            return _place_sentence(fact_map["живу"])

        parts: list[str] = []

        if asks_method:
            if fact_map.get("работаю"):
                parts.append(_watch_cycle_sentence(fact_map["работаю"]))
            if fact_map.get("вахта"):
                parts.append(_watch_duration_sentence(fact_map["вахта"]))
            if fact_map.get("одна вахта"):
                parts.append(_watch_alternation_sentence(fact_map["одна вахта"]))
            if fact_map.get("график"):
                parts.append(_shift_duration_sentence(fact_map["график"]))
            elif fact_map.get("режим"):
                parts.append(_shift_duration_sentence(fact_map["режим"]))

        if asks_place and fact_map.get("живу"):
            parts.append(_place_sentence(fact_map["живу"]))

        if mentions_food and fact_map.get("завтрак с"):
            parts.append(_food_sentence(fact_map["завтрак с"]))
            if "ужин" in query_tokens and any(token.startswith("ночн") for token in query_tokens):
                parts.append("В ночную смену ужин с 19:00 до 20:00 уже не попадает в рабочее время.")

        if parts:
            return " ".join(parts)

    if query_text == "это место проживания":
        if fact_map.get("живу"):
            return f"Понял, это место проживания: {_place_tail(fact_map['живу'])}."
        return "Понял."

    return None


def _fact_map(facts: list[dict]) -> dict[str, str]:
    result: dict[str, str] = {}
    for fact in facts:
        key = _canonical_fact_key(str(fact.get("key", "")))
        value = str(fact.get("value", "")).strip()
        if key and value and key not in result:
            result[key] = value
    return result


def _canonical_fact_key(key: str) -> str:
    return "роль" if key.endswith(":role") else key


def _normalize_text(text: str) -> str:
    return " ".join(text.split()).strip().lower()


def _query_tokens(query: str) -> list[str]:
    return [token for token in re.findall(r"[\w-]+", _normalize_text(query)) if len(token) > 2]


def _has_prefix(tokens: set[str], prefix: str) -> bool:
    return any(token.startswith(prefix) for token in tokens)


def _role_nominative(value: str) -> str:
    cleaned = value.strip()
    if " " in cleaned:
        return cleaned
    lowered = cleaned.lower()
    if lowered.endswith("ом") and len(cleaned) > 3:
        return cleaned[:-2]
    if lowered.endswith("ем") and len(cleaned) > 3:
        return cleaned[:-2]
    return cleaned


def _place_sentence(value: str) -> str:
    return f"Живешь {_place_tail(value)}."


def _place_tail(value: str) -> str:
    cleaned = value.replace(", ", " ").strip()
    lowered = cleaned.lower()
    if lowered.startswith(("в ", "на ", "у ", "из ", "под ")):
        return cleaned
    return f"в {cleaned}"


def _watch_cycle_sentence(value: str) -> str:
    return f"Работаешь {value}."


def _watch_duration_sentence(value: str) -> str:
    return f"Одна вахта длится {value}."


def _shift_duration_sentence(value: str) -> str:
    match = re.search(r"\b\d{1,2}\s+час(?:а|ов)?\b", value.lower())
    if match:
        return f"Смена — {match.group(0)}."
    return f"По смене у тебя {value}."


def _watch_alternation_sentence(value: str) -> str:
    return f"{_capitalize(_watch_alternation_clause(value))}."


def _watch_alternation_clause(value: str) -> str:
    lowered = value.lower()
    if "день" in lowered and "ноч" in lowered:
        return "одна вахта дневная, другая ночная"
    return f"чередование такое: {value}"


def _food_sentence(value: str) -> str:
    cleaned = value.replace(" до ", ":00-").replace(", ", "; ")
    return f"По питанию так: {cleaned}."


def _capitalize(text: str) -> str:
    if not text:
        return text
    return text[0].upper() + text[1:]
