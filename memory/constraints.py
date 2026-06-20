"""
Constraints - zashchita ot perepolneniya konteksta.

Obrezaet istoriyu i retrieval do bezopasnykh razmerov.
"""
from __future__ import annotations

from config import settings

# Grubaya otsenka: 1 token ~= 4 simvola
_CHARS_PER_TOKEN = 4
_MAX_HISTORY_CHARS = 4000


def trim_history(messages: list[dict]) -> list[dict]:
    """
    Obrezaet istoriyu dialoga sprava nalevo,
    chtoby summarnyy razmer ne prevyshal limit.
    Pervoe soobshchenie (system) vsegda sokhranyaetsya.
    """
    if not messages:
        return messages

    system = [m for m in messages if m["role"] == "system"]
    rest = [m for m in messages if m["role"] != "system"]
    if not rest:
        return system

    # Always keep the latest non-system message so the current user request
    # never disappears from context even when the conversation gets long.
    kept = [rest[-1]]
    total = len(rest[-1].get("content", ""))

    for msg in reversed(rest[:-1]):
        size = len(msg.get("content", ""))
        if total + size > _MAX_HISTORY_CHARS:
            break
        kept.insert(0, msg)
        total += size

    return system + kept


def trim_retrieval_block(block: str) -> str:
    """Obrezaet blok pamyati do MAX_CONTEXT_CHARS simvolov."""
    if len(block) <= settings.MAX_CONTEXT_CHARS:
        return block

    marker = "\n[...обрезано...]"
    kept_lines = block.splitlines()

    while kept_lines and len("\n".join(kept_lines) + marker) > settings.MAX_CONTEXT_CHARS:
        kept_lines.pop()

    if kept_lines:
        return "\n".join(kept_lines) + marker
    return marker.lstrip("\n")
