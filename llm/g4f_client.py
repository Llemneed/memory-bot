from __future__ import annotations

import asyncio
import logging
from typing import Any

import g4f.Provider as Providers
from g4f.client import AsyncClient

from config import settings

log = logging.getLogger(__name__)

FALLBACK_PROVIDERS = [
    Providers.PollinationsAI,
    Providers.DeepInfra,
    Providers.HuggingChat,
    Providers.You,
    None,
]


async def _call_provider(provider: Any, messages: list[dict], model: str) -> str:
    client = AsyncClient(provider=provider)
    response = await asyncio.wait_for(
        client.chat.completions.create(model=model, messages=messages),
        timeout=settings.LLM_TIMEOUT,
    )
    text = response.choices[0].message.content
    if not text or not text.strip():
        raise ValueError("Empty response from provider")
    return text.strip()


async def complete(messages: list[dict]) -> str:
    model = settings.G4F_MODEL
    max_tries = min(settings.LLM_MAX_RETRIES, len(FALLBACK_PROVIDERS))

    for attempt, provider in enumerate(FALLBACK_PROVIDERS[:max_tries], start=1):
        provider_name = getattr(provider, "__name__", "Auto") if provider else "Auto"
        log.info("LLM attempt %d/%d via %s", attempt, max_tries, provider_name)
        try:
            result = await _call_provider(provider, messages, model)
            log.info("LLM OK via %s (%d chars)", provider_name, len(result))
            return result
        except asyncio.TimeoutError:
            log.warning("Provider %s timed out after %ds", provider_name, settings.LLM_TIMEOUT)
        except Exception as exc:
            log.warning("Provider %s failed: %s", provider_name, exc)

    raise RuntimeError(f"Все {max_tries} провайдеров недоступны. Попробуй позже.")
