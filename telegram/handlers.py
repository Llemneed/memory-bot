"""
Telegram handlers.

Реализует пайплайн:
  User Message
    → Save Message
    → Retrieve Memory
    → Build Context
    → LLM
    → Answer
    → Save Answer
"""
from __future__ import annotations

import logging

from aiogram import Router
from aiogram.filters import CommandStart
from aiogram.types import Message

from database.sqlite import get_db
from dialogs.history import get_last_n, save_message
from llm.g4f_client import complete
from llm.prompts import build_system_prompt
from memory.constraints import trim_history, trim_retrieval_block
from memory.context_builder import build_memory_block
from memory.retrieval import retrieve

log = logging.getLogger(__name__)
router = Router()


def _dialog_id(user_id: int) -> str:
    """Для MVP один диалог на пользователя."""
    return f"dialog_{user_id}"


@router.message(CommandStart())
async def cmd_start(msg: Message) -> None:
    await msg.answer(
        "Привет! Я запоминаю наши разговоры и использую их в контексте.\n"
        "Просто напиши что-нибудь."
    )


@router.message()
async def handle_message(msg: Message) -> None:
    if not msg.text:
        return

    user_id = msg.from_user.id
    user_text = msg.text.strip()
    dialog_id = _dialog_id(user_id)

    async with await get_db() as db:
        # 1. Сохраняем входящее сообщение
        await save_message(db, user_id=user_id, dialog_id=dialog_id, role="user", text=user_text)

        # 2. Retrieval: ищем релевантные фрагменты из прошлого
        retrieved = await retrieve(db, user_id=user_id, query=user_text)

        # 3. Строим last-N историю
        history = await get_last_n(db, user_id=user_id)

    # 4. Собираем контекст
    memory_block = build_memory_block(retrieved)
    memory_block = trim_retrieval_block(memory_block)
    system_prompt = build_system_prompt(memory_block)

    messages = [{"role": "system", "content": system_prompt}] + history
    messages = trim_history(messages)

    # 5. Вызов LLM
    await msg.bot.send_chat_action(msg.chat.id, "typing")
    try:
        answer = await complete(messages)
    except RuntimeError as e:
        await msg.answer(f"⚠️ {e}")
        return

    # 6. Отправляем ответ
    await msg.answer(answer)

    # 7. Сохраняем ответ
    async with await get_db() as db:
        await save_message(db, user_id=user_id, dialog_id=dialog_id, role="assistant", text=answer)
