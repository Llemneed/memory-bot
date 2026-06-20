from __future__ import annotations

import re


def maybe_build_fact_answer(query: str, facts: list[dict]) -> str | None:
    if not facts:
        return None

    token_set = set(_query_tokens(query))
    fact_map = _fact_map(facts)

    asks_role = bool(token_set & {"кем", "работаю", "профессия", "роль"})
    asks_place = bool(token_set & {"где", "живу", "мессояхе", "мессояхском", "месторождении"})
    asks_method = bool(
        token_set
        & {"метод", "график", "расписание", "вахта", "вахтовый", "смена", "смены"}
    )
    asks_why_day_night = bool(token_set & {"почему", "день", "ночь", "ночную", "дневную"})
    mentions_food = bool(token_set & {"ужин", "завтрак", "обед", "питание"})

    if asks_role and fact_map.get("роль"):
        return f"Вы работаете {fact_map['роль']}."

    if asks_why_day_night and fact_map.get("вахта") and fact_map.get("одна вахта"):
        lines = ["Коротко по твоим данным:"]
        lines.append(f"- Длительность вахты: {fact_map['вахта']}.")
        lines.append(f"- Чередование вахт: {fact_map['одна вахта']}.")
        lines.append("- То есть у тебя чередуются именно вахты месячными блоками, а не 12-часовые смены внутри суток.")
        if fact_map.get("график"):
            lines.append(f"- Длительность смены: {fact_map['график']}.")
        elif fact_map.get("режим"):
            lines.append(f"- Длительность смены: {fact_map['режим']}.")
        return "\n".join(lines)

    if asks_method or asks_place or mentions_food:
        lines: list[str] = []

        if asks_method:
            lines.append("Коротко по твоим данным:")
            if fact_map.get("работаю"):
                lines.append(f"- Вахтовый цикл: {fact_map['работаю']}.")
            if fact_map.get("вахта"):
                lines.append(f"- Длительность вахты: {fact_map['вахта']}.")
            if fact_map.get("одна вахта"):
                lines.append(f"- Чередование вахт: {fact_map['одна вахта']}.")
            if fact_map.get("график"):
                lines.append(f"- Длительность смены: {fact_map['график']}.")
            elif fact_map.get("режим"):
                lines.append(f"- Длительность смены: {fact_map['режим']}.")

        if asks_place and fact_map.get("живу"):
            if not lines:
                lines.append("Коротко по твоим данным:")
            lines.append(f"- Место проживания: {fact_map['живу']}.")

        if mentions_food and fact_map.get("завтрак с"):
            if not lines:
                lines.append("Коротко по твоим данным:")
            lines.append(f"- Расписание питания: {fact_map['завтрак с']}.")
            if "ужин" in token_set and any(token.startswith("ночн") for token in token_set):
                lines.append("- В ночную смену ужин 19:00-20:00 не входит в рабочее время.")

        if lines:
            return "\n".join(lines)

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


def _query_tokens(query: str) -> list[str]:
    normalized = " ".join(query.split()).strip().lower()
    return [token for token in re.findall(r"[\w-]+", normalized) if len(token) > 2]
