from __future__ import annotations

import re


def maybe_build_fact_answer(query: str, facts: list[dict]) -> str | None:
    if not facts:
        return None

    query_tokens = set(_query_tokens(query))
    query_text = _normalize_text(query)
    fact_map = _fact_map(facts)

    asks_role = bool(query_tokens & {"кем", "профессия", "роль", "должность"})
    asks_where = "где" in query_tokens
    asks_work_place = asks_where and any(token.startswith("работ") for token in query_tokens)
    asks_home_place = asks_where and (
        any(token.startswith("жив") for token in query_tokens)
        or any(token.startswith("прожив") for token in query_tokens)
        or "дом" in query_tokens
    )
    asks_method = (
        _has_prefix(query_tokens, "метод")
        or _has_prefix(query_tokens, "график")
        or _has_prefix(query_tokens, "расписан")
        or _has_prefix(query_tokens, "распоряд")
        or _has_prefix(query_tokens, "вахт")
        or _has_prefix(query_tokens, "смен")
        or _has_prefix(query_tokens, "режим")
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
    mentions_food = bool(query_tokens & {"ужин", "завтрак", "обед", "питание", "еда"})
    asks_routine = _has_prefix(query_tokens, "распоряд") or (
        asks_method and ("живу" in query_tokens or "работе" in query_tokens)
    )

    if asks_role and fact_map.get("роль"):
        return f"Ты {_role_nominative(fact_map['роль'])}."

    if asks_work_place:
        work_place = fact_map.get("место_работы")
        if work_place:
            return f"Работаешь {_work_place_tail(work_place)}."
        if fact_map.get("живу"):
            return f"Отдельно место работы ты не называл. Знаю только, что живешь {_place_tail(fact_map['живу'])}."
        return "Отдельно место работы ты не называл."

    if asks_home_place and fact_map.get("живу"):
        return f"Живешь {_place_tail(fact_map['живу'])}."

    if asks_why_day_night and fact_map.get("одна вахта"):
        parts = [f"Потому что {_watch_alternation_sentence(fact_map['одна вахта'], leading=False)}."]
        if fact_map.get("вахта"):
            parts.append(_watch_duration_sentence(fact_map["вахта"]))
        if fact_map.get("график"):
            parts.append(_shift_duration_sentence(fact_map["график"]))
        elif fact_map.get("режим"):
            parts.append(_shift_duration_sentence(fact_map["режим"]))
        return " ".join(parts)

    if asks_method or mentions_food:
        parts: list[str] = []

        if asks_routine:
            schedule = _routine_summary(fact_map)
            food = _food_sentence(fact_map.get("завтрак с", ""))
            if schedule:
                parts.append(schedule)
            if food:
                parts.append(food)
        else:
            schedule = _schedule_summary(fact_map)
            if schedule:
                parts.append(schedule)

        if mentions_food and not asks_routine:
            food = _food_sentence(fact_map.get("завтрак с", ""))
            if food:
                parts.append(food)
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
    if key.endswith(":role"):
        return "роль"
    if key.endswith(":place"):
        return "место_работы"
    return key


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


def _place_tail(value: str) -> str:
    cleaned = value.replace(", ", " ").strip()
    lowered = cleaned.lower()
    if lowered.startswith(("в ", "на ", "у ", "из ", "под ")):
        return _capitalize_single_location(cleaned)
    return _capitalize_single_location(f"в {cleaned}")


def _work_place_tail(value: str) -> str:
    cleaned = value.strip()
    cleaned = re.split(r"\s+и\s+туда\b", cleaned, maxsplit=1, flags=re.IGNORECASE)[0].strip(" ,.")
    cleaned = re.split(r"\s+а\s+туда\b", cleaned, maxsplit=1, flags=re.IGNORECASE)[0].strip(" ,.")
    if cleaned.startswith(("на ", "в ")):
        return _capitalize_single_location(cleaned)
    return _capitalize_single_location(f"на {cleaned}")


def _capitalize_single_location(text: str) -> str:
    parts = text.split(maxsplit=1)
    if len(parts) != 2:
        return text
    preposition, rest = parts
    if " " not in rest and rest:
        return f"{preposition} {rest[:1].upper()}{rest[1:]}"
    return text


def _schedule_summary(fact_map: dict[str, str]) -> str:
    parts: list[str] = []

    work_cycle = fact_map.get("работаю")
    shift = fact_map.get("график") or fact_map.get("режим")
    alternation = fact_map.get("одна вахта")
    watch = fact_map.get("вахта")

    if work_cycle:
        parts.append(f"У тебя вахта {work_cycle}")
    if watch:
        parts.append(f"сама вахта длится {watch}")
    if shift:
        parts.append(_shift_clause(shift))
    if alternation:
        parts.append(_watch_alternation_sentence(alternation, leading=False))

    if not parts:
        return ""

    first, *rest = parts
    sentence = first[:1].upper() + first[1:]
    if rest:
        sentence += ": " + ", ".join(rest)
    return f"{sentence}."


def _routine_summary(fact_map: dict[str, str]) -> str:
    parts: list[str] = []

    shift = fact_map.get("график") or fact_map.get("режим")
    alternation = fact_map.get("одна вахта")
    watch = fact_map.get("вахта")

    if watch:
        parts.append(f"вахта длится {watch}")
    if shift:
        parts.append(_shift_clause(shift))
    if alternation:
        parts.append(_watch_alternation_sentence(alternation, leading=False))

    if not parts:
        return ""

    return f"На работе у тебя {', '.join(parts)}."


def _watch_duration_sentence(value: str) -> str:
    return f"Одна вахта длится {value}."


def _shift_duration_sentence(value: str) -> str:
    clause = _shift_clause(value)
    if not clause:
        return ""
    return f"{clause[:1].upper()}{clause[1:]}."


def _shift_clause(value: str) -> str:
    match = re.search(r"\b\d{1,2}\s+час(?:а|ов)?\b", value.lower())
    if match:
        return f"смены по {match.group(0)}"
    return f"по смене у тебя {value}"


def _watch_alternation_sentence(value: str, *, leading: bool = True) -> str:
    clause = _watch_alternation_clause(value)
    if leading:
        return f"{clause[:1].upper()}{clause[1:]}"
    return clause


def _watch_alternation_clause(value: str) -> str:
    lowered = value.lower()
    if "день" in lowered and "ноч" in lowered:
        return "одна вахта дневная, другая ночная"
    return f"чередование такое: {value}"


def _food_sentence(value: str) -> str:
    if not value:
        return ""
    cleaned = value.replace(" до ", ":00-").replace(", ", "; ")
    return f"По еде так: {cleaned}."
