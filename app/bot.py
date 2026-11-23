"""Telegram application wiring (single polling process)."""
from __future__ import annotations

import logging

from telegram import Update
from telegram.error import Conflict, NetworkError, RetryAfter, TimedOut
from telegram.ext import (Application, ApplicationBuilder, CallbackQueryHandler, ChatMemberHandler, CommandHandler,
                          ContextTypes, MessageHandler, filters)

from app.context import AppContext
from app.tg import business, chat, commands, media, owner, start

log = logging.getLogger(__name__)

POLL_UPDATES = ["message", "callback_query", "my_chat_member", "business_connection", "business_message"]


async def _on_my_chat_member(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Track where Ria is present: groups she's added to/removed from, and users who block her."""
    ctx: AppContext = context.application.bot_data["ctx"]
    ev = update.my_chat_member
    if ev is None:
        return
    status, chat = ev.new_chat_member.status, ev.chat
    gone = status in ("left", "kicked")
    if chat.type == "private":
        await ctx.users.get_or_create(chat.id, chat.first_name or "", chat.username or "")
        await ctx.users.set_blocked(chat.id, gone)
    elif chat.type in ("group", "supergroup"):
        if gone:
            await ctx.chats.set_active(chat.id, False)
        else:
            await ctx.chats.touch(chat.id, chat.type, chat.title or "")


async def _on_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    ctx: AppContext = context.application.bot_data["ctx"]
    err = context.error
    if isinstance(err, Conflict):
        # Another process is polling with the same token.
        ctx.telegram_last_error = "Conflict: another getUpdates consumer exists"
        log.error("Telegram Conflict: a second polling process is using this bot token!")
        return
    if isinstance(err, (NetworkError, TimedOut, RetryAfter)):
        ctx.telegram_last_error = type(err).__name__
        log.warning("Telegram network issue: %s (polling auto-retries)", type(err).__name__)
        return
    log.error("Unhandled handler error: %s", type(err).__name__, exc_info=err)


def build_application(ctx: AppContext) -> Application:
    builder = (
        ApplicationBuilder()
        .token(ctx.settings.telegram_bot_token)
        .concurrent_updates(True)  # a slow inference must not block other users
        .connection_pool_size(16)
        .get_updates_connection_pool_size(2)
        .read_timeout(20).write_timeout(20).connect_timeout(10).pool_timeout(10)
        .get_updates_read_timeout(30)
    )
    try:  # optional flood-limit helper (python-telegram-bot[rate-limiter])
        from telegram.ext import AIORateLimiter

        builder = builder.rate_limiter(AIORateLimiter(max_retries=3))
    except Exception:  # noqa: BLE001
        log.info("AIORateLimiter unavailable; using manual RetryAfter handling only")
    app = builder.build()
    app.bot_data["ctx"] = ctx

    private = filters.ChatType.PRIVATE
    # Secretary mode (Telegram Business). Own handler group, runs before everything else.
    try:
        from telegram.ext import BusinessConnectionHandler

        app.add_handler(BusinessConnectionHandler(business.on_business_connection), group=-2)
        app.add_handler(MessageHandler(filters.UpdateType.BUSINESS_MESSAGE, business.on_business_message), group=-2)
    except ImportError:  # python-telegram-bot older than 21.1
        log.warning("Secretary mode unavailable: python-telegram-bot too old")
    for name, fn in [
        ("start", start.start), ("help", start.help_cmd), ("about", start.about),
        ("reset", commands.reset), ("memory", commands.memory), ("forget", commands.forget),
        ("language", commands.language), ("settings", commands.settings), ("name", commands.name),
        ("link", commands.link), ("gender", commands.gender), ("health", commands.health),
    ]:
        app.add_handler(CommandHandler(name, fn, filters=private))
    # Owner panel (numeric-id authorised). Registered before the generic handlers.
    owner_ids = sorted(ctx.settings.owner_ids)
    if owner_ids:
        is_owner = filters.User(user_id=owner_ids)
        app.add_handler(MessageHandler(private & is_owner & (filters.TEXT | filters.Sticker.ALL), owner.owner_input), group=-1)
        for name in ("owner", "panel"):
            app.add_handler(CommandHandler(name, owner.panel, filters=private & is_owner))
        app.add_handler(CallbackQueryHandler(owner.owner_callback, pattern=r"^own:"))
    else:
        log.warning("No OWNER_USER_IDS set: owner panel is disabled")
    app.add_handler(CallbackQueryHandler(start.start_callback, pattern=r"^st:"))
    app.add_handler(CallbackQueryHandler(commands.on_callback, pattern=r"^(forget|lang|mem):"))
    app.add_handler(ChatMemberHandler(_on_my_chat_member, ChatMemberHandler.MY_CHAT_MEMBER))
    # DMs always; groups are filtered inside on_text (only when "Ria" is said, bot is tagged, or Ria is replied to)
    app.add_handler(MessageHandler((private | filters.ChatType.GROUPS) & filters.TEXT & ~filters.COMMAND, chat.on_text))
    app.add_handler(MessageHandler(private & ~filters.TEXT & ~filters.COMMAND & ~filters.StatusUpdate.ALL, media.on_media))
    app.add_error_handler(_on_error)
    return app


def _polling_error(ctx: AppContext):
    def cb(exc: Exception) -> None:
        ctx.telegram_last_error = type(exc).__name__
        if isinstance(exc, Conflict):
            log.error("Telegram Conflict: another process is polling with this bot token! "
                      "Only ONE polling process may run (stop other copies of the bot).")
        else:
            log.warning("Telegram polling error: %s", type(exc).__name__)
    return cb


async def _begin_polling(app: Application, ctx: AppContext) -> None:
    await app.updater.start_polling(
        allowed_updates=POLL_UPDATES, drop_pending_updates=False, bootstrap_retries=-1,
        poll_interval=0.0, error_callback=_polling_error(ctx),
    )
    ctx.telegram_running = True


async def start_polling(app: Application, ctx: AppContext) -> None:
    await app.initialize()
    await app.start()
    await _begin_polling(app, ctx)
    me = await app.bot.get_me()
    log.info("Telegram polling started as @%s", me.username)


async def polling_watchdog(app: Application, ctx: AppContext, interval: int = 30) -> None:
    """Restart polling if it stopped (e.g. after a Conflict or an unexpected updater error)."""
    import asyncio

    delay = interval
    while True:
        await asyncio.sleep(delay)
        try:
            if app.updater.running:
                ctx.telegram_running, delay = True, interval
                continue
            ctx.telegram_running = False
            log.error("Telegram polling is not running; restarting (last error: %s)", ctx.telegram_last_error)
            await _begin_polling(app, ctx)
            log.info("Telegram polling recovered")
            delay = interval
        except asyncio.CancelledError:
            raise
        except Exception as e:  # noqa: BLE001
            delay = min(delay * 2, 300)  # exponential backoff
            log.warning("Polling restart failed (%s); retry in %ss", type(e).__name__, delay)


async def stop_polling(app: Application, ctx: AppContext) -> None:
    ctx.telegram_running = False
    try:
        if app.updater and app.updater.running:
            await app.updater.stop()
        if app.running:
            await app.stop()
        await app.shutdown()
    except Exception as e:  # noqa: BLE001
        log.warning("Telegram shutdown issue: %s", type(e).__name__)
