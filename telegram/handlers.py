from __future__ import annotations

import asyncio
import logging

from aiogram import Router
from aiogram.filters import Command, CommandStart
from aiogram.types import Message

from database.sqlite import get_db
from dialogs.history import get_last_n, reset_history, save_message
from llm.g4f_client import complete
from llm.prompts import build_system_prompt
from memory.constraints import trim_history, trim_retrieval_block
from memory.context_builder import build_memory_block
from memory.retrieval import retrieve

log = logging.getLogger(__name__)
router = Router()

SEND_RETRY_COUNT = 3
SEND_RETRY_DELAY_SECONDS = 2


def _dialog_id(user_id: int) -> str:
    return f"dialog_{user_id}"


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

    db = await get_db()
    try:
        await save_message(db, user_id=user_id, dialog_id=dialog_id, role="user", text=user_text)
        retrieved = await retrieve(db, user_id=user_id, query=user_text)
        history = await get_last_n(db, user_id=user_id)
    finally:
        await db.close()

    memory_block = trim_retrieval_block(build_memory_block(retrieved))
    system_prompt = build_system_prompt(memory_block)
    messages = trim_history([{"role": "system", "content": system_prompt}] + history)

    try:
        await msg.bot.send_chat_action(msg.chat.id, "typing")
    except Exception as exc:
        log.warning("send_chat_action failed: %s", exc)

    try:
        answer = await complete(messages)
    except RuntimeError as exc:
        await safe_answer(msg, f"⚠️ {exc}")
        return

    if not await safe_answer(msg, answer):
        log.warning("Failed to deliver assistant response to user=%s", user_id)
        return

    db = await get_db()
    try:
        await save_message(db, user_id=user_id, dialog_id=dialog_id, role="assistant", text=answer)
    finally:
        await db.close()
