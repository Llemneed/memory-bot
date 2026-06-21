from __future__ import annotations

import asyncio
import logging
import re
import time

from aiogram import Router
from aiogram.filters import Command, CommandStart
from aiogram.types import Message

from config import settings
from database.sqlite import get_db
from dialogs.history import get_last_n, normalize_message_text, reset_history, save_message
from llm.g4f_client import complete
from llm.prompts import build_system_prompt
from memory.constraints import trim_history, trim_retrieval_block
from memory.context_builder import build_memory_block
from memory.fact_answers import maybe_build_fact_answer
from memory.facts import (
    build_fact_answer_block,
    build_fact_block,
    expand_fact_answer_hits,
    list_active_facts,
    retrieve_facts,
    upsert_extracted_facts,
)
from memory.retrieval import retrieve

log = logging.getLogger(__name__)
router = Router()

SEND_RETRY_COUNT = 3
SEND_RETRY_DELAY_SECONDS = 2
RECENT_INPUTS: dict[tuple[int, str], float] = {}
RECENT_INPUTS_LOCK = asyncio.Lock()


def _dialog_id(user_id: int) -> str:
    return f"dialog_{user_id}"


def _user_wants_structured_reply(text: str) -> bool:
    normalized = normalize_message_text(text)
    if not normalized:
        return False
    markers = (
        "спис",
        "пункт",
        "шаг",
        "по шаг",
        "вариант",
        "сравн",
        "таблиц",
        "чеклист",
        "план",
    )
    return any(marker in normalized for marker in markers)


def _is_route_query(text: str) -> bool:
    normalized = normalize_message_text(text)
    if not normalized:
        return False
    markers = (
        "маршрут",
        "маршрутом",
        "добира",
        "доезжа",
        "еду",
        "езжу",
        "дорог",
        "путь",
    )
    return any(marker in normalized for marker in markers)


def _is_route_fact(fact: dict) -> bool:
    key = str(fact.get("key", "")).lower()
    return key.startswith("маршрут") or key.endswith(":place")


def _fact_value_by_key(facts: list[dict], key: str) -> str | None:
    for fact in facts:
        if str(fact.get("key", "")) != key:
            continue
        value = str(fact.get("value", "")).strip()
        if value:
            return value
    return None


def _shape_answer_text(answer: str, user_text: str) -> str:
    cleaned = answer.strip()
    if not cleaned or _user_wants_structured_reply(user_text):
        return cleaned

    lines = [line.strip() for line in cleaned.splitlines() if line.strip()]
    bullet_lines = [line for line in lines if line.startswith(("-", "•", "*"))]
    if not bullet_lines:
        return cleaned

    heading = ""
    content_lines = lines
    if lines and lines[0].endswith(":") and len(lines[0]) < 80:
        heading = lines[0][:-1].strip()
        content_lines = lines[1:]

    if not content_lines or not all(line.startswith(("-", "•", "*")) for line in content_lines):
        return cleaned

    items = [re.sub(r"^[-•*]\s*", "", line).strip(" .;") for line in content_lines]
    items = [item for item in items if item]
    if not items:
        return cleaned

    if heading:
        sentence = f"{heading}: " + "; ".join(items) + "."
    else:
        sentence = ". ".join(items)
        if not sentence.endswith((".", "!", "?")):
            sentence += "."
    return sentence


async def should_drop_burst_duplicate(user_id: int, text: str) -> bool:
    normalized = normalize_message_text(text)
    if not normalized:
        return True

    now = time.monotonic()
    async with RECENT_INPUTS_LOCK:
        stale_before = now - settings.MESSAGE_BURST_DEDUP_SECONDS
        stale_keys = [key for key, ts in RECENT_INPUTS.items() if ts < stale_before]
        for key in stale_keys:
            RECENT_INPUTS.pop(key, None)

        key = (user_id, normalized)
        last_seen = RECENT_INPUTS.get(key)
        if last_seen is not None and now - last_seen < settings.MESSAGE_BURST_DEDUP_SECONDS:
            return True

        RECENT_INPUTS[key] = now
        return False


async def safe_answer(msg: Message, text: str) -> bool:
    for attempt in range(1, SEND_RETRY_COUNT + 1):
        try:
            await msg.answer(text)
            return True
        except Exception as exc:
            log.warning("msg.answer failed on attempt %d/%d: %s", attempt, SEND_RETRY_COUNT, exc)
            if attempt < SEND_RETRY_COUNT:
                await asyncio.sleep(SEND_RETRY_DELAY_SECONDS)
    return False


def split_for_telegram(text: str) -> list[str]:
    limit = max(1, settings.TELEGRAM_MAX_MESSAGE_CHARS)
    normalized = text.strip()
    if not normalized:
        return [""]
    if len(normalized) <= limit:
        return [normalized]

    chunks: list[str] = []
    remaining = normalized
    while len(remaining) > limit:
        window = remaining[:limit]
        split_at = max(
            window.rfind("\n\n"),
            window.rfind("\n"),
            window.rfind(". "),
            window.rfind("! "),
            window.rfind("? "),
            window.rfind(" "),
        )
        if split_at < limit // 2:
            split_at = limit

        chunk = remaining[:split_at].strip()
        if not chunk:
            chunk = remaining[:limit]
            split_at = limit

        chunks.append(chunk)
        remaining = remaining[split_at:].lstrip()

    if remaining:
        chunks.append(remaining)
    return chunks


async def safe_answer_chunks(msg: Message, text: str) -> bool:
    chunks = split_for_telegram(text)
    for index, chunk in enumerate(chunks, start=1):
        if not await safe_answer(msg, chunk):
            log.warning(
                "Failed to deliver chunk %d/%d to user=%s",
                index,
                len(chunks),
                msg.from_user.id if msg.from_user else "?",
            )
            return False
    return True


@router.message(CommandStart())
async def cmd_start(msg: Message) -> None:
    await safe_answer(
        msg,
        "Привет! Я запоминаю наши разговоры и использую их в контексте.\n"
        "Просто напиши что-нибудь.\n\n"
        "/reset - очистить историю",
    )


@router.message(Command("reset"))
async def cmd_reset(msg: Message) -> None:
    user_id = msg.from_user.id

    db = await get_db()
    try:
        await reset_history(db, user_id=user_id)
    finally:
        await db.close()

    await safe_answer(msg, "История очищена. Начнем заново.")


@router.message()
async def handle_message(msg: Message) -> None:
    if not msg.text:
        return

    user_id = msg.from_user.id
    user_text = msg.text.strip()
    dialog_id = _dialog_id(user_id)

    if await should_drop_burst_duplicate(user_id, user_text):
        log.info("Dropped burst duplicate for user=%s text=%r", user_id, user_text[:80])
        return

    db = await get_db()
    try:
        fact_hits = await retrieve_facts(db, user_id=user_id, dialog_id=dialog_id, query=user_text)
        retrieved = await retrieve(db, user_id=user_id, query=user_text, exclude_text=user_text)
        # Keep the prompt anchored in the user's own words so the model
        # does not treat its earlier mistaken replies as reliable facts.
        history = await get_last_n(
            db,
            user_id=user_id,
            n=4,
            include_assistant=False,
            include_questions=False,
        )
    finally:
        await db.close()

    db = await get_db()
    try:
        user_message_id = await save_message(db, user_id=user_id, dialog_id=dialog_id, role="user", text=user_text)
        extracted_facts = await upsert_extracted_facts(
            db,
            user_id=user_id,
            dialog_id=dialog_id,
            text=user_text,
            source_message_id=user_message_id,
        )
    finally:
        await db.close()

    if user_message_id is None:
        log.info("Skipped duplicate history write for user=%s text=%r", user_id, user_text[:80])

    if extracted_facts:
        log.info("Extracted %d fact(s) from user=%s", len(extracted_facts), user_id)

    db = await get_db()
    try:
        fresh_fact_hits = await retrieve_facts(db, user_id=user_id, dialog_id=dialog_id, query=user_text)
        direct_fact_hits = await list_active_facts(db, user_id=user_id, dialog_id=dialog_id)
    finally:
        await db.close()

    log.info("FACT_RETRIEVED -> %s", fact_hits)
    log.info("RETRIEVED -> %s", retrieved)
    log.info("FACT_REFRESHED -> %s", fresh_fact_hits)
    log.info("FACT_ACTIVE -> %s", direct_fact_hits)

    direct_answer_fallback = maybe_build_fact_answer(user_text, direct_fact_hits)
    fact_answer_hits = fresh_fact_hits or direct_fact_hits[: settings.FACTS_TOP_K]
    if direct_answer_fallback:
        fact_answer_hits = expand_fact_answer_hits(
            fact_answer_hits,
            active_facts=direct_fact_hits,
        )
    route_query = _is_route_query(user_text)
    if route_query:
        filtered_route_hits = [fact for fact in fact_answer_hits if _is_route_fact(fact)]
        if filtered_route_hits:
            fact_answer_hits = filtered_route_hits

    raw_memory_block = ""
    if not route_query and not direct_answer_fallback and len(fresh_fact_hits) < 3:
        raw_memory_block = build_memory_block(retrieved)

    if direct_answer_fallback:
        fact_memory_block = build_fact_answer_block(fact_answer_hits)
    else:
        fact_memory_block = build_fact_block(fresh_fact_hits)

    memory_parts = [fact_memory_block, raw_memory_block]
    memory_block = trim_retrieval_block("\n\n".join(part for part in memory_parts if part))
    bot_name = _fact_value_by_key(direct_fact_hits, "bot_name")
    user_name = _fact_value_by_key(direct_fact_hits, "имя")
    log.info(
        "ANSWER_MODE -> %s",
        "fact_llm_with_fallback" if direct_answer_fallback else "default_llm",
    )
    log.info("CONTEXT -> %s", memory_block)
    system_prompt = build_system_prompt(
        memory_block,
        fact_answer_mode=bool(direct_answer_fallback),
        bot_name=bot_name,
        user_name=user_name,
    )
    messages = trim_history(
        [{"role": "system", "content": system_prompt}] +
        history +
        [{"role": "user", "content": user_text}]
    )

    try:
        await msg.bot.send_chat_action(msg.chat.id, "typing")
    except Exception as exc:
        log.warning("send_chat_action failed: %s", exc)

    try:
        answer = await complete(messages)
    except RuntimeError as exc:
        if direct_answer_fallback:
            if not await safe_answer_chunks(msg, direct_answer_fallback):
                log.warning("Failed to deliver direct fact fallback to user=%s", user_id)
                return

            db = await get_db()
            try:
                await save_message(
                    db,
                    user_id=user_id,
                    dialog_id=dialog_id,
                    role="assistant",
                    text=direct_answer_fallback,
                )
            finally:
                await db.close()
            return

        await safe_answer(msg, f"⚠️ {exc}")
        return

    answer = _shape_answer_text(answer, user_text)

    if not await safe_answer_chunks(msg, answer):
        log.warning("Failed to deliver assistant response to user=%s", user_id)
        return

    db = await get_db()
    try:
        await save_message(db, user_id=user_id, dialog_id=dialog_id, role="assistant", text=answer)
    finally:
        await db.close()
