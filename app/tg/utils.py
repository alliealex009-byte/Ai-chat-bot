"""Telegram helpers: safe message splitting, typing indicator, flood-safe sending."""
from __future__ import annotations

import asyncio
import contextlib
import logging
from typing import List

log = logging.getLogger(__name__)

TG_LIMIT = 4096
SAFE_LIMIT = 3900


def split_message(text: str, limit: int = SAFE_LIMIT) -> List[str]:
    """Split on paragraph, line, sentence, then space boundaries; hard-cut only as last resort."""
    text = text.strip()
    if len(text) <= limit:
        return [text] if text else []
    parts: List[str] = []
    while len(text) > limit:
        window = text[:limit]
        cut = -1
        for sep in ("\n\n", "\n", ". ", "? ", "! ", " "):
            idx = window.rfind(sep)
            if idx >= limit // 2:
                cut = idx + len(sep)
                break
        if cut <= 0:
            cut = limit
        parts.append(text[:cut].rstrip())
        text = text[cut:].lstrip()
    if text:
        parts.append(text)
    return parts


@contextlib.asynccontextmanager
async def typing_indicator(bot, chat_id: int):
    """Keep the 'typing…' status alive while the block runs (Telegram expires it after ~5s)."""

    async def loop():
        while True:
            try:
                await bot.send_chat_action(chat_id=chat_id, action="typing")
            except Exception:  # noqa: BLE001 - cosmetic only
                pass
            await asyncio.sleep(4)

    task = asyncio.create_task(loop())
    try:
        yield
    finally:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await task


async def safe_reply(message, text: str, **kwargs) -> None:
    """Reply, honouring Telegram flood control (RetryAfter) and splitting long text."""
    from telegram.error import NetworkError, RetryAfter, TimedOut

    for chunk in split_message(text) or [""]:
        if not chunk:
            continue
        for attempt in range(3):
            try:
                await message.reply_text(chunk, **kwargs)
                break
            except RetryAfter as e:
                wait = float(getattr(e, "retry_after", 1)) + 0.5
                log.warning("Telegram flood limit; sleeping %.1fs", wait)
                await asyncio.sleep(min(wait, 30))
            except (TimedOut, NetworkError):
                await asyncio.sleep(1 + attempt)
            except Exception as e:  # noqa: BLE001
                log.warning("send failed: %s", type(e).__name__)
                return
