"""Graceful handling of stickers, photos, voice and other unsupported media.

Stickers are understood through the emoji they carry (+ pack name) and answered by the model like a friend would.
Photos in private chat are understood by the local Gemma 3 vision model (Ollama) and answered like a friend would;
the picture is never stored (only the caption/text and Ria's reply are kept). Voice notes need speech-to-text, which
is not installed, so Ria asks for text. Groups are not handled here.
"""
from __future__ import annotations

import base64
import random

from telegram import Update
from telegram.ext import ContextTypes

from app.tg.utils import safe_reply, typing_indicator

MAX_PHOTO_BYTES = 4_000_000

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


def _pick_size(sizes):
    """Largest size up to ~1280px: enough detail for the model, small enough for a CPU."""
    ok = [p for p in sizes if max(getattr(p, "width", 0) or 0, getattr(p, "height", 0) or 0) <= 1280]
    return (ok or list(sizes))[-1] if (ok or sizes) else None


async def _handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE, ctx) -> bool:
    """React to a photo like a friend. Returns False when it could not be handled (caller sends the fallback text)."""
    m, user = update.message, update.effective_user
    rt = await ctx.runtime.all()
    if user.id in ctx.banned or not rt["bot_enabled"] or not rt["dm_enabled"]:
        return True  # silently ignored, same as text
    if not ctx.user_limiter.allow(user.id):
        return True
    photo = _pick_size(m.photo)
    if photo is None or (getattr(photo, "file_size", 0) or 0) > MAX_PHOTO_BYTES:
        return False
    try:
        f = await context.bot.get_file(photo.file_id)
        data = bytes(await f.download_as_bytearray())
    except Exception:  # noqa: BLE001 - network/Telegram hiccup
        return False
    if not data or len(data) > MAX_PHOTO_BYTES:
        return False
    caption = (m.caption or "").strip()[:300] or "(photo bheji hai)"
    async with typing_indicator(context.bot, m.chat_id):
        reply = await ctx.engine.chat(user.id, caption, "telegram", user.first_name or "", user.username or "",
                                      images=[base64.b64encode(data).decode()])
    await safe_reply(m, reply.text)
    return True


async def _handle_sticker(update: Update, context: ContextTypes.DEFAULT_TYPE, ctx) -> bool:
    """Understand a sticker through its emoji + pack name and answer it like a friend. False -> caller sends a canned reaction."""
    from app.emoji import sticker_text

    m, user = update.message, update.effective_user
    rt = await ctx.runtime.all()
    if user.id in ctx.banned or not rt["bot_enabled"] or not rt["dm_enabled"]:
        return True
    if not ctx.user_limiter.allow(user.id):
        return True
    text = sticker_text(getattr(m.sticker, "emoji", "") or "", getattr(m.sticker, "set_name", "") or "")
    async with typing_indicator(context.bot, m.chat_id):
        reply = await ctx.engine.chat(user.id, text, "telegram", user.first_name or "", user.username or "")
    if reply.status != "ok":
        return False
    await safe_reply(m, reply.text)
    try:
        from app.tg.stickers import maybe_send_sticker
        await maybe_send_sticker(ctx, context.bot, m.chat_id, getattr(m.sticker, "emoji", "") or reply.text, None)
    except Exception:  # noqa: BLE001 - cosmetic
        pass
    return True


async def on_media(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    ctx = context.application.bot_data["ctx"]
    m = update.message
    if m is None or ctx.dedupe.seen(("media", update.update_id)):
        return
    if m.photo and ctx.settings.vision_enabled and await _handle_photo(update, context, ctx):
        return
    if m.sticker and await _handle_sticker(update, context, ctx):
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
