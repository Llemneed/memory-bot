from __future__ import annotations

import asyncio
import logging
import os

from aiogram import Bot, Dispatcher
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.fsm.storage.memory import MemoryStorage

from config import settings
from database.sqlite import init_db
from telegram.handlers import router
from telegram.middleware import LoggingMiddleware

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger(__name__)


def build_session() -> AiohttpSession | None:
    proxy = os.getenv("TELEGRAM_PROXY", "").strip()
    if not proxy:
        return None

    log.info("Telegram proxy enabled: %s", proxy)
    return AiohttpSession(proxy=proxy)


async def main() -> None:
    await init_db()

    bot = Bot(token=settings.BOT_TOKEN, session=build_session())
    dp = Dispatcher(storage=MemoryStorage())
    dp.message.middleware(LoggingMiddleware())
    dp.include_router(router)

    log.info("Bot started")
    await dp.start_polling(bot, allowed_updates=["message"])


if __name__ == "__main__":
    asyncio.run(main())
