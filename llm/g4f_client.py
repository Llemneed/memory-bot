from __future__ import annotations

import asyncio
import logging
import os
from typing import Any

import g4f.Provider as Providers
from g4f.client import AsyncClient

from config import settings

log = logging.getLogger(__name__)


def _resolve_provider(token: str) -> Any:
    name = token.strip()
    if not name:
        return None
    if name.lower() == "auto":
        return None
    return getattr(Providers, name, None)


def _provider_chain() -> list[Any]:
    resolved: list[Any] = []
    for raw_name in settings.G4F_PROVIDER_ORDER.split(","):
        provider = _resolve_provider(raw_name)
        if provider is None and raw_name.strip() and raw_name.strip().lower() != "auto":
            log.warning("Unknown G4F provider in G4F_PROVIDER_ORDER: %s", raw_name.strip())
            continue
        resolved.append(provider)

    if resolved:
        return resolved

    return [
        Providers.PollinationsAI,
        Providers.DeepInfra,
        Providers.HuggingChat,
        Providers.You,
        None,
    ]


def _effective_proxy() -> str | None:
    proxy = settings.G4F_PROXY.strip() or os.getenv("TELEGRAM_PROXY", "").strip()
    return proxy or None


async def _call_provider(provider: Any, messages: list[dict], model: str) -> str:
    client = AsyncClient(
        provider=provider,
        proxies=_effective_proxy(),
    )
    response = await asyncio.wait_for(
        client.chat.completions.create(
            model=model,
            messages=messages,
            web_search=settings.G4F_WEB_SEARCH,
        ),
        timeout=settings.LLM_TIMEOUT,
    )
    text = response.choices[0].message.content
    if not text or not text.strip():
        raise ValueError("Empty response from provider")
    return text.strip()


async def complete(messages: list[dict]) -> str:
    model = settings.G4F_MODEL
    providers = _provider_chain()
    max_tries = min(settings.LLM_MAX_RETRIES, len(providers))

    for attempt, provider in enumerate(providers[:max_tries], start=1):
        provider_name = getattr(provider, "__name__", "Auto") if provider else "Auto"
        log.info(
            "LLM attempt %d/%d via %s (model=%s, web_search=%s, proxy=%s)",
            attempt,
            max_tries,
            provider_name,
            model,
            settings.G4F_WEB_SEARCH,
            bool(_effective_proxy()),
        )
        try:
            result = await _call_provider(provider, messages, model)
            log.info("LLM OK via %s (%d chars)", provider_name, len(result))
            return result
        except asyncio.TimeoutError:
            log.warning("Provider %s timed out after %ds", provider_name, settings.LLM_TIMEOUT)
        except Exception as exc:
            log.warning("Provider %s failed: %s", provider_name, exc)

    raise RuntimeError(f"Все {max_tries} провайдеров недоступны. Попробуй позже.")
