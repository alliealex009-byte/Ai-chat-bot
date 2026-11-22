"""Normal text-message handler."""
from __future__ import annotations

import logging

from telegram import Update
from telegram.ext import ContextTypes

from app.services.limiter import SlidingWindowLimiter
from app.tg.utils import safe_reply, typing_indicator

log = logging.getLogger(__name__)
_warn = SlidingWindowLimiter(1, 30)

MSG_SLOW_DOWN = "Arey thoda dheere dheere 😅 Itni jaldi mein reply nahi de paungi!"
MSG_GLOBAL_BUSY = "Abhi bahut log baat kar rahe hain 🥺 Thodi der baad aana!"


async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    ctx = context.application.bot_data["ctx"]
    msg, user = update.message, update.effective_user
    if msg is None or user is None or not msg.text:
        return

    # Duplicate update protection (Telegram can redeliver after restarts/network errors).
    if ctx.dedupe.seen(update.update_id):
        return

    if not ctx.user_limiter.allow(user.id):
        if _warn.allow(user.id):  # at most one "slow down" notice per 30s per user
            await safe_reply(msg, MSG_SLOW_DOWN)
        return
    if not ctx.global_limiter.allow("global"):
        await safe_reply(msg, MSG_GLOBAL_BUSY)
        return

    if ctx.settings.log_message_content:
        log.debug("msg user=%s text=%r", user.id, msg.text[:80])

    async with typing_indicator(context.bot, msg.chat_id):
        reply = await ctx.engine.chat(user.id, msg.text, "telegram", user.first_name or "", user.username or "")
    await safe_reply(msg, reply.text)
