"""
Middleware: логирование входящих сообщений.
"""
from __future__ import annotations

import logging
import time
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import Message

log = logging.getLogger(__name__)


class LoggingMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[Message, dict[str, Any]], Awaitable[Any]],
        event: Message,
        data: dict[str, Any],
    ) -> Any:
        start = time.monotonic()
        user = event.from_user
        log.info(
            "→ user=%d text=%r",
            user.id if user else 0,
            (event.text or "")[:80],
        )
        result = await handler(event, data)
        elapsed = time.monotonic() - start
        log.info("← done in %.2fs", elapsed)
        return result
