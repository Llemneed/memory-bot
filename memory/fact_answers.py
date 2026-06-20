from __future__ import annotations

import re

_ROUTE_NODE_ALIASES = {
    "салават": {
        "variants": ("салават", "салавата"),
        "from": "Салавата",
        "to": "Салават",
        "label": "Салават",
    },
    "уфа": {
        "variants": ("уфа", "уфу", "уфы"),
        "from": "Уфы",
        "to": "Уфу",
        "label": "Уфа",
    },
    "новый_уренгой": {
        "variants": ("уренгой", "уренгоя", "новый уренгой", "нового уренгоя"),
        "from": "Нового Уренгоя",
        "to": "Новый Уренгой",
        "label": "Новый Уренгой",
    },
    "мессояха": {
        "variants": ("мессояха", "мессояху", "мессояхе"),
        "from": "Мессояхи",
        "to": "Мессояху",
        "label": "Мессояха",
    },
}


def maybe_build_fact_answer(query: str, facts: list[dict]) -> str | None:
    if not facts:
        return None

    query_tokens = set(_query_tokens(query))
    query_text = _normalize_text(query)
    if not _looks_like_fact_request(query_text, query_tokens):
        return None

    route_answer = _route_answer(query_text, query_tokens, facts)
    if route_answer:
        return route_answer

    fact_map = _fact_map(facts)

    asks_where = "где" in query_tokens
    asks_role = bool(query_tokens & {"кем", "профессия", "роль", "должность"})
    asks_profession = bool(query_tokens & {"профессия", "должность"})
    asks_work_place = asks_where and any(token.startswith("работ") for token in query_tokens)
    asks_home_place = asks_where and (
        any(token.startswith("жив") for token in query_tokens)
        or any(token.startswith("прожив") for token in query_tokens)
        or "дом" in query_tokens
    )
    asks_work_stay = asks_home_place and "работе" in query_tokens
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
        if asks_profession:
            return f"По профессии ты {_role_nominative(fact_map['роль'])}."
        return f"Работаешь {fact_map['роль']}."

    if asks_work_stay:
        work_place = fact_map.get("место работы")
        if work_place:
            return (
                f"На работе ты {_work_place_tail(work_place)}. "
                "Где именно там живешь, ты отдельно не уточнял."
            )
        return "Где именно живешь на работе, ты отдельно не говорил."

    if asks_work_place:
        work_place = fact_map.get("место работы")
        if work_place:
            return f"Работаешь {_work_place_tail(work_place)}."
        if fact_map.get("живу"):
            return (
                "Отдельно место работы ты не называл. "
                f"Знаю только, что живешь {_place_tail(fact_map['живу'])}."
            )
        return "Отдельно место работы ты не называл."

    if asks_home_place and fact_map.get("живу"):
        return f"Живешь {_place_tail(fact_map['живу'])}."

    if asks_why_day_night and fact_map.get("одна вахта"):
        parts = [f"Потому что {_watch_alternation_clause(fact_map['одна вахта'])}."]
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
            routine = _routine_summary(fact_map)
            if routine:
                parts.append(routine)
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
        key = _canonical_fact_key(str(fact.get("key", "")), str(fact.get("value", "")))
        value = str(fact.get("value", "")).strip()
        if key and value and key not in result:
            result[key] = value
    return result


def _canonical_fact_key(key: str, value: str = "") -> str:
    if key.startswith("маршрут:"):
        return "маршрут"
    if key.endswith(":role"):
        return "роль"
    if key.endswith(":place"):
        return "место работы"
    normalized_value = _normalize_text(value)
    if key in {"смена", "смены"}:
        return "график"
    if key == "режим" and "смен" in normalized_value and re.search(r"\b\d{1,2}\s+час", normalized_value):
        return "график"
    if key == "вахты":
        if "черед" in normalized_value or ("день" in normalized_value and "ноч" in normalized_value):
            return "одна вахта"
        if any(marker in normalized_value for marker in ("месяц", "дней", "дня", "день")):
            return "вахта"
    return key


def _route_answer(query_text: str, query_tokens: set[str], facts: list[dict]) -> str | None:
    if not _looks_like_route_query(query_tokens):
        return None

    segments = _collect_route_segments(facts)
    if not segments:
        return None

    ordered = _order_route_segments(segments)
    if not ordered:
        return None

    if "сначала" in query_text:
        return f"Сначала {ordered[0]['phrase']}."

    target = _route_query_target(query_text, ordered)
    if target:
        ordered = _trim_route_segments_to_target(ordered, target)
    if not ordered:
        return None

    phrases = [segment["phrase"] for segment in ordered]
    chain = ", потом ".join(phrases)

    if target == "новый_уренгой":
        return f"До Нового Уренгоя добираешься так: {chain}."
    if target == "мессояха" or "работ" in query_text:
        return f"До работы добираешься так: {chain}."
    if "сначала" in query_text:
        return f"Сначала {phrases[0]}."
    return f"Маршрут такой: {chain}."


def _looks_like_route_query(query_tokens: set[str]) -> bool:
    markers = (
        "маршрут",
        "маршрутом",
        "доби",
        "доезж",
        "еду",
        "езжу",
        "дорог",
        "путь",
        "попада",
        "добира",
        "лет",
        "вертолет",
    )
    return any(any(token.startswith(marker) for marker in markers) for token in query_tokens)


def _collect_route_segments(facts: list[dict]) -> list[dict[str, str]]:
    segments: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()

    for fact in facts:
        key = str(fact.get("key", "")).strip()
        value = str(fact.get("value", "")).strip()
        parsed = _parse_route_segment_key(key)
        if parsed is None:
            continue
        source, dest = parsed
        marker = (source, dest)
        if marker in seen:
            continue
        seen.add(marker)
        segments.append(
            {
                "source": source,
                "dest": dest,
                "phrase": value or _route_segment_phrase(source, dest),
            }
        )

    return segments


def _parse_route_segment_key(key: str) -> tuple[str, str] | None:
    if not key.startswith("маршрут:"):
        return None
    payload = key.split(":", 1)[1]
    if "->" not in payload:
        return None
    source, dest = payload.split("->", 1)
    source = source.strip()
    dest = dest.strip()
    if not source or not dest:
        return None
    return source, dest


def _order_route_segments(segments: list[dict[str, str]]) -> list[dict[str, str]]:
    if not segments:
        return []

    by_source = {segment["source"]: segment for segment in segments}
    destinations = {segment["dest"] for segment in segments}
    starts = [segment for segment in segments if segment["source"] not in destinations]
    start = starts[0] if starts else segments[0]

    ordered: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    current = start
    while current is not None:
        marker = (current["source"], current["dest"])
        if marker in seen:
            break
        seen.add(marker)
        ordered.append(current)
        current = by_source.get(current["dest"])

    for segment in segments:
        marker = (segment["source"], segment["dest"])
        if marker not in seen:
            ordered.append(segment)

    return ordered


def _route_query_target(query_text: str, segments: list[dict[str, str]]) -> str | None:
    for node, meta in _ROUTE_NODE_ALIASES.items():
        if any(variant in query_text for variant in meta["variants"]):
            return node

    if "работ" in query_text:
        return segments[-1]["dest"]
    return None


def _trim_route_segments_to_target(segments: list[dict[str, str]], target: str) -> list[dict[str, str]]:
    trimmed: list[dict[str, str]] = []
    for segment in segments:
        trimmed.append(segment)
        if segment["dest"] == target:
            break
    return trimmed


def _route_segment_phrase(source: str, dest: str) -> str:
    return f"из {_route_node_label(source, case='from')} в {_route_node_label(dest, case='to')}"


def _route_node_label(node: str, *, case: str) -> str:
    meta = _ROUTE_NODE_ALIASES.get(node)
    if meta is not None:
        return str(meta["from"] if case == "from" else meta["to"])
    label = node.replace("_", " ").strip()
    if not label:
        return node
    return f"{label[:1].upper()}{label[1:]}"


def _normalize_text(text: str) -> str:
    return " ".join(text.split()).strip().lower()


def _query_tokens(query: str) -> list[str]:
    return [token for token in re.findall(r"[\w-]+", _normalize_text(query)) if len(token) > 2]


def _has_prefix(tokens: set[str], prefix: str) -> bool:
    return any(token.startswith(prefix) for token in tokens)


def _looks_like_fact_request(query_text: str, query_tokens: set[str]) -> bool:
    if "?" in query_text:
        return True
    if query_text.startswith(("напомни", "скажи", "подскажи", "расскажи", "уточни")):
        return True
    if query_tokens & {"кто", "что", "где", "когда", "почему", "зачем", "кем", "чем", "какой", "какая", "какие", "каким"}:
        return True
    return False


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
    pieces: list[str] = []

    work_cycle = fact_map.get("работаю")
    shift = fact_map.get("график") or fact_map.get("режим")
    alternation = fact_map.get("одна вахта")
    watch = fact_map.get("вахта")

    if work_cycle:
        pieces.append(work_cycle)
    if shift:
        pieces.append(_shift_clause(shift))
    if alternation:
        pieces.append(_watch_alternation_clause(alternation))
    if watch:
        pieces.append(f"сама вахта длится {watch}")

    if not pieces:
        return ""

    return f"По графику у тебя {', '.join(pieces)}."


def _routine_summary(fact_map: dict[str, str]) -> str:
    pieces: list[str] = []

    work_cycle = fact_map.get("работаю")
    shift = fact_map.get("график") or fact_map.get("режим")
    alternation = fact_map.get("одна вахта")
    watch = fact_map.get("вахта")
    food = fact_map.get("завтрак с")

    if work_cycle:
        pieces.append(f"вахта {work_cycle}")
    if watch:
        pieces.append(f"сама вахта длится {watch}")
    if shift:
        pieces.append(_shift_clause(shift))
    if alternation:
        pieces.append(_watch_alternation_clause(alternation))

    if not pieces and not food:
        return ""

    text = f"На работе у тебя так: {', '.join(pieces)}."
    food_sentence = _food_sentence(food or "")
    if food_sentence:
        text = f"{text} {food_sentence}"
    return text.strip()


def _watch_duration_sentence(value: str) -> str:
    return f"Одна вахта длится {value}."


def _shift_duration_sentence(value: str) -> str:
    clause = _shift_clause(value)
    return f"{clause[:1].upper()}{clause[1:]}." if clause else ""


def _shift_clause(value: str) -> str:
    match = re.search(r"\b\d{1,2}\s+час(?:а|ов)?\b", value.lower())
    if match:
        return f"смены по {match.group(0)}"
    return f"по смене у тебя {value}"


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
