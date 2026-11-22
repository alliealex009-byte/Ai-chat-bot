"""Ria sometimes follows a reply with a sticker from the owner-managed library."""
from __future__ import annotations

import logging
import random
from typing import Optional

from app.ai.prompts import extract_emojis

log = logging.getLogger(__name__)
MIN_GAP = 3  # at least this many text replies between stickers in the same chat


async def maybe_send_sticker(ctx, bot, chat_id: int, reply_text: str, reply_to: Optional[int] = None) -> bool:
    rt = await ctx.runtime.all()
    gap = ctx.sticker_gap.get(chat_id, MIN_GAP) + 1
    ctx.sticker_gap[chat_id] = gap
    if len(ctx.sticker_gap) > 5000:
        ctx.sticker_gap.clear()
    if not rt["stickers_enabled"] or gap < MIN_GAP or random.randint(1, 100) > int(rt["sticker_chance"]):
        return False
    sticker = await ctx.stickers.pick(extract_emojis(reply_text))
    if not sticker:
        return False
    try:
        kwargs = {}
        if reply_to:
            from telegram import ReplyParameters

            kwargs["reply_parameters"] = ReplyParameters(message_id=reply_to, allow_sending_without_reply=True)
        await bot.send_sticker(chat_id=chat_id, sticker=sticker["file_id"], **kwargs)
        ctx.sticker_gap[chat_id] = 0
        return True
    except Exception as e:  # noqa: BLE001 - never break chat because of a sticker
        log.warning("sticker send failed: %s", type(e).__name__)
        if "wrong file" in str(e).lower() or "not found" in str(e).lower():
            await ctx.stickers.remove_by_file_id(sticker["file_id"])  # stale id: drop it
        return False
