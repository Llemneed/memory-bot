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
            return f"Ваша профессия — {_role_nominative(fact_map['роль'])}."
        return f"Вы работаете {fact_map['роль']}."

    if asks_work_place:
        lines: list[str] = []
        if fact_map.get("живу"):
            lines.append(f"Отдельно место работы не указано. Есть только место проживания: {_place_sentence_tail(fact_map['живу'])}.")
        else:
            lines.append("Место работы отдельно не указано.")
        if fact_map.get("роль"):
            lines.append(f"По профессии вы {_role_nominative(fact_map['роль'])}.")
        return "\n".join(lines)

    if asks_why_day_night and fact_map.get("вахта") and fact_map.get("одна вахта"):
        lines = ["Коротко по твоим данным:"]
        lines.append(_watch_duration_sentence(fact_map["вахта"]))
        lines.append(_watch_alternation_sentence(fact_map["одна вахта"]))
        lines.append("То есть у тебя чередуются именно вахты месячными блоками, а не 12-часовые смены внутри суток.")
        if fact_map.get("график"):
            lines.append(_shift_duration_sentence(fact_map["график"]))
        elif fact_map.get("режим"):
            lines.append(_shift_duration_sentence(fact_map["режим"]))
        return "\n".join(f"- {line}" if index else line for index, line in enumerate(lines))

    if asks_method or asks_place or mentions_food:
        if asks_place and not asks_method and not mentions_food and fact_map.get("живу"):
            return _place_sentence(fact_map["живу"])

        lines: list[str] = ["Коротко по твоим данным:"]

        if asks_method:
            if fact_map.get("работаю"):
                lines.append(_watch_cycle_sentence(fact_map["работаю"]))
            if fact_map.get("вахта"):
                lines.append(_watch_duration_sentence(fact_map["вахта"]))
            if fact_map.get("одна вахта"):
                lines.append(_watch_alternation_sentence(fact_map["одна вахта"]))
            if fact_map.get("график"):
                lines.append(_shift_duration_sentence(fact_map["график"]))
            elif fact_map.get("режим"):
                lines.append(_shift_duration_sentence(fact_map["режим"]))

        if asks_place and fact_map.get("живу"):
            lines.append(_place_sentence(fact_map["живу"]))

        if mentions_food and fact_map.get("завтрак с"):
            lines.append(_food_sentence(fact_map["завтрак с"]))
            if "ужин" in query_tokens and any(token.startswith("ночн") for token in query_tokens):
                lines.append("В ночную смену ужин 19:00-20:00 не входит в рабочее время.")

        compact = [line for line in lines if line]
        if len(compact) == 1 and compact[0] == "Коротко по твоим данным:":
            return None
        return "\n".join(f"- {line}" if index else line for index, line in enumerate(compact))

    if query_text == "это место проживания":
        if fact_map.get("живу"):
            return f"Понял. Место проживания: {_place_sentence_tail(fact_map['живу'])}."
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
    return f"Вы живете {_place_sentence_tail(value)}."


def _place_sentence_tail(value: str) -> str:
    cleaned = value.replace(", ", " ").strip()
    lowered = cleaned.lower()
    if lowered.startswith(("в ", "на ", "у ", "из ", "под ")):
        return cleaned
    return f"в {cleaned}"


def _watch_cycle_sentence(value: str) -> str:
    return f"Вахтовый цикл — {value}."


def _watch_duration_sentence(value: str) -> str:
    return f"Вахта длится {value}."


def _shift_duration_sentence(value: str) -> str:
    match = re.search(r"\b\d{1,2}\s+час(?:а|ов)?\b", value.lower())
    if match:
        return f"Смена длится {match.group(0)}."
    return f"Режим смены: {value}."


def _watch_alternation_sentence(value: str) -> str:
    lowered = value.lower()
    if "день" in lowered and "ноч" in lowered:
        return "Одна вахта дневная, другая ночная."
    return f"Чередование вахт: {value}."


def _food_sentence(value: str) -> str:
    cleaned = value.replace(" до ", ":00-").replace(", ", "; ")
    return f"Расписание питания: {cleaned}."
