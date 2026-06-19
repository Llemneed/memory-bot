"""
Memory MVP Bot — точка входа.
"""
from __future__ import annotations

import asyncio
import logging

from aiogram import Bot, Dispatcher
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


async def main() -> None:
    await init_db()

    bot = Bot(token=settings.BOT_TOKEN)
    dp = Dispatcher(storage=MemoryStorage())
    dp.message.middleware(LoggingMiddleware())
    dp.include_router(router)

    log.info("Bot started")
    await dp.start_polling(bot, allowed_updates=["message"])


if __name__ == "__main__":
    asyncio.run(main())
