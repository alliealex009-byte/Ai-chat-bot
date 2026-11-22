"""Telegram application wiring (single polling process)."""
from __future__ import annotations

import logging

from telegram import Update
from telegram.error import Conflict, NetworkError, RetryAfter, TimedOut
from telegram.ext import (Application, ApplicationBuilder, CallbackQueryHandler, CommandHandler,
                          ContextTypes, MessageHandler, filters)

from app.context import AppContext
from app.tg import chat, commands, media, start

log = logging.getLogger(__name__)

POLL_UPDATES = ["message", "callback_query"]


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
    for name, fn in [
        ("start", start.start), ("help", start.help_cmd), ("about", start.about),
        ("reset", commands.reset), ("memory", commands.memory), ("forget", commands.forget),
        ("language", commands.language), ("settings", commands.settings), ("name", commands.name),
        ("link", commands.link), ("health", commands.health),
    ]:
        app.add_handler(CommandHandler(name, fn, filters=private))
    app.add_handler(CallbackQueryHandler(commands.on_callback))
    app.add_handler(MessageHandler(private & filters.TEXT & ~filters.COMMAND, chat.on_text))
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
