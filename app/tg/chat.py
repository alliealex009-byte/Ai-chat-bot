"""Text messages: DMs always; groups only when someone says "Ria", @tags the bot, or replies to Ria."""
from __future__ import annotations

import logging

from telegram import ReplyParameters, Update
from telegram.ext import ContextTypes

from app.ai.prompts import is_sensitive
from app.services.limiter import SlidingWindowLimiter
from app.services.triggers import should_respond_in_group, strip_mention
from app.tg.stickers import maybe_send_sticker
from app.tg.utils import safe_reply, typing_indicator

log = logging.getLogger(__name__)
_warn = SlidingWindowLimiter(1, 30)

MSG_SLOW_DOWN = "arre thoda dheere yaar 😅 itni jaldi nahi"
MSG_GLOBAL_BUSY = "abhi bahut log baat kar rahe hain 🥺 thodi der baad aana"
MSG_PAUSED = "ria thodi der ke liye break pe hai 😴"


async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    ctx = context.application.bot_data["ctx"]
    msg, user, chat = update.message, update.effective_user, update.effective_chat
    if msg is None or user is None or chat is None or not msg.text or user.is_bot:
        return
    if ctx.dedupe.seen(update.update_id):  # Telegram may redeliver after restarts/network errors
        return
    is_group = chat.type in ("group", "supergroup")
    rt = await ctx.runtime.all()
    text = msg.text
    reply_kwargs: dict = {}

    if is_group:
        await ctx.chats.touch(chat.id, chat.type, chat.title or "")
        bot_username = context.bot.username or ""
        rb = msg.reply_to_message
        replied_to_bot = bool(rb and rb.from_user and rb.from_user.id == context.bot.id)
        if not should_respond_in_group(text, bot_username, replied_to_bot):
            return
        if not rt["bot_enabled"] or not rt["group_enabled"] or user.id in ctx.banned:
            return
        chat_doc = await ctx.chats.get(chat.id)
        if chat_doc and chat_doc.get("enabled") is False:
            return
        if not ctx.chat_limiter.allow(chat.id):
            return
        text = strip_mention(text, bot_username) or "hi"
        reply_kwargs["reply_parameters"] = ReplyParameters(message_id=msg.message_id, allow_sending_without_reply=True)
    else:
        if user.id in ctx.banned:
            return
        if ctx.user_state.get(user.id) == "name":  # user pressed "Naam badlo" and now sends the name
            ctx.user_state.pop(user.id, None)
            new = " ".join(text.split())[:40]
            if not new or is_sensitive(new):
                return await safe_reply(msg, "Ye naam thik nahi lag raha, chhota sa naam batao 🙂")
            await ctx.users.get_or_create(user.id, user.first_name or "", user.username or "")
            await ctx.users.set_preferred_name(user.id, new)
            return await safe_reply(msg, f"Okayy, ab se {new} bulaungi 💗")
        if not rt["bot_enabled"] or not rt["dm_enabled"]:
            if _warn.allow(("paused", user.id)):
                await safe_reply(msg, MSG_PAUSED)
            return

    if not ctx.user_limiter.allow(user.id):
        if not is_group and _warn.allow(user.id):  # at most one "slow down" notice per 30s per user
            await safe_reply(msg, MSG_SLOW_DOWN)
        return
    if not ctx.global_limiter.allow("global"):
        if not is_group:
            await safe_reply(msg, MSG_GLOBAL_BUSY)
        return

    if ctx.settings.log_message_content:
        log.debug("msg user=%s text=%r", user.id, text[:80])

    async with typing_indicator(context.bot, chat.id):
        reply = await ctx.engine.chat(
            user.id, text, "telegram", user.first_name or "", user.username or "",
            scope=chat.id if is_group else None, group=is_group,
        )
    await safe_reply(msg, reply.text, **reply_kwargs)
    if reply.status == "ok":
        await maybe_send_sticker(ctx, context.bot, chat.id, reply.text, msg.message_id if is_group else None)
