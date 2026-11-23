"""Graceful handling of stickers, photos, voice and other unsupported media.

Image understanding / speech-to-text are intentionally NOT implemented in this release.
To add them later, register a handler here that calls a separate module; the rest is unaffected.
"""
from __future__ import annotations

import random

from telegram import Update
from telegram.ext import ContextTypes

from app.tg.utils import safe_reply

STICKER = [
    "hehe cute 😄 ab bolo, mood kya hai?",
    "arre waah 😂 ye wala mast tha!",
    "haha 🙈 aur bhejo na, ya kuch bolo bhi 😌",
    "okayyy 😎 sticker se kaam nahi chalega, kuch likho 💗",
    "uff 😂 tum bhi na! kya chal raha aaj?",
]
PHOTO = [
    "Photo dikh toh gayi 🥺 par abhi main images samajh nahi sakti. Text mein bata do kya hai usme?",
]
VOICE = [
    "Voice message sun nahi paungi abhi yaar 🥲 Bas text padh sakti hu, type karke bhejo na!",
]
OTHER = [
    "Ye wali file/media main abhi handle nahi kar paati 🙈 Text mein baat karte hain?",
]


async def on_media(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    ctx = context.application.bot_data["ctx"]
    m = update.message
    if m is None or ctx.dedupe.seen(("media", update.update_id)):
        return
    if m.sticker:
        pool = STICKER
    elif m.photo:
        pool = PHOTO
    elif m.voice or m.audio or m.video_note:
        pool = VOICE
    else:
        pool = OTHER
    if not ctx.user_limiter.allow(("media", update.effective_user.id)):
        return
    await safe_reply(m, random.choice(pool))
    if m.sticker:
        from app.tg.stickers import maybe_send_sticker
        try:
            await maybe_send_sticker(ctx, context.bot, m.chat_id, getattr(m.sticker, "emoji", "") or "😄", None)
        except Exception:  # noqa: BLE001 - cosmetic
            pass
