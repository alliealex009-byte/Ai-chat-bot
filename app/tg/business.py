"""Secretary mode (Telegram Business): Ria answers private chats of the account that connected the bot.

Telegram itself decides which chats the bot can see (Settings > Business > Chatbots: all private chats except...,
or only selected chats). We only reply when the connection is enabled, allows replying, the sender is not the
account owner, and the owner has not just written in that chat himself (human takeover pause).
"""
from __future__ import annotations

import logging
import time

from telegram import Update
from telegram.ext import ApplicationHandlerStop, ContextTypes


log = logging.getLogger(__name__)


def _can_reply(conn) -> bool:
    rights = getattr(conn, "rights", None)
    if rights is not None and hasattr(rights, "can_reply"):
        return bool(rights.can_reply)
    return bool(getattr(conn, "can_reply", True))


async def on_business_connection(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    ctx = context.application.bot_data["ctx"]
    c = update.business_connection
    if c is None:
        return
    name = getattr(c.user, "first_name", "") or ""
    await ctx.business.upsert(c.id, c.user.id, name, _can_reply(c), bool(getattr(c, "is_enabled", True)))
    log.info("Business connection %s user=%s enabled=%s", "updated", c.user.id, getattr(c, "is_enabled", True))


async def _hint_for(owner_name: str) -> list[str]:
    who = owner_name or "the account owner"
    return [
        f"SECRETARY MODE: you are replying in {who}'s private chat while they are away. You are Ria, not {who}. "
        f"If the person wants {who}, say {who} is busy right now and you'll pass the message along. "
        "Do not make promises, plans or decisions on their behalf."
    ]


async def _handle(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    ctx = context.application.bot_data["ctx"]
    msg = update.business_message
    if msg is None or not msg.text or not msg.business_connection_id:
        return
    cid, chat, sender = msg.business_connection_id, msg.chat, msg.from_user
    if sender is None or sender.is_bot:
        return
    if ctx.dedupe.seen(update.update_id):
        return
    conn = await ctx.business.get(cid)
    if conn is None:  # connection event missed (e.g. bot was offline): fetch it once
        try:
            c = await context.bot.get_business_connection(cid)
            await ctx.business.upsert(c.id, c.user.id, getattr(c.user, "first_name", "") or "", _can_reply(c),
                                      bool(getattr(c, "is_enabled", True)))
            conn = await ctx.business.get(cid)
        except Exception as e:  # noqa: BLE001
            log.warning("business connection lookup failed: %s", type(e).__name__)
            return
    if not conn or not conn.get("is_enabled") or not conn.get("can_reply"):
        return
    key = (cid, chat.id)
    if sender.id == conn["user_id"]:  # the account owner wrote here himself: pause the secretary in this chat
        ctx.secretary_pause[key] = time.monotonic()
        return
    rt = await ctx.runtime.all()
    if not rt["bot_enabled"] or not rt["secretary_enabled"] or sender.id in ctx.banned:
        return
    paused_at = ctx.secretary_pause.get(key)
    if paused_at is not None and time.monotonic() - paused_at < ctx.settings.secretary_pause_minutes * 60:
        return
    if not ctx.user_limiter.allow(sender.id) or not ctx.global_limiter.allow("global"):
        return

    try:  # optional: show as read (needs the "mark messages as read" permission and a recent PTB)
        await context.bot.read_business_message(business_connection_id=cid, chat_id=chat.id, message_id=msg.message_id)
    except Exception:  # noqa: BLE001
        pass
    try:
        await context.bot.send_chat_action(chat_id=chat.id, action="typing", business_connection_id=cid)
    except Exception:  # noqa: BLE001
        pass
    reply = await ctx.engine.chat(
        sender.id, msg.text, "telegram", sender.first_name or "", sender.username or "",
        hints=await _hint_for(conn.get("user_name", "")),
    )
    try:
        await context.bot.send_message(chat_id=chat.id, text=reply.text, business_connection_id=cid)
    except Exception as e:  # noqa: BLE001
        log.warning("business send failed: %s", type(e).__name__)


async def on_business_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        await _handle(update, context)
    except Exception as e:  # noqa: BLE001 - never let a customer chat crash the bot
        log.warning("business message failed: %s", type(e).__name__)
    raise ApplicationHandlerStop  # other handlers use update.message, which is empty for business messages
