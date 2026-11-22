"""RIA entry point: one process runs Telegram polling + the HTTP API, with graceful shutdown.

Run:  python -m app.main
"""
from __future__ import annotations

import asyncio
import logging
import signal
import sys

from app.config import load_settings
from app.utils.logging import setup_logging
from app.utils.singleton import AlreadyRunning, SingleInstance

log = logging.getLogger("ria")


async def run() -> int:
    try:
        settings = load_settings()
    except Exception as e:  # pydantic ValidationError etc. - show a readable message, no secrets
        print(f"Configuration error: {e}", file=sys.stderr)
        return 2
    setup_logging(settings.log_level, settings.log_dir, settings.secrets())

    lock = SingleInstance("data/ria.lock")
    try:
        lock.acquire()
    except AlreadyRunning as e:
        log.error("%s", e)
        return 3

    from app.api.server import create_api
    from app.bot import build_application, polling_watchdog, start_polling, stop_polling
    from app.context import build_context
    from app.services.maintenance import cleanup_loop

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)

    log.info("Starting RIA (model=%s, mode=%s, concurrency=%d)", settings.ollama_model, settings.ai_mode,
             settings.max_concurrent_inference)
    ctx = await build_context(settings)  # retries MongoDB with backoff, creates indexes
    ctx.queue.start()
    ctx.router.start()
    asyncio.create_task(ctx.router.ollama.warmup())

    tasks = [asyncio.create_task(cleanup_loop(settings, ctx.conversations, ctx.user_limiter, ctx.global_limiter))]
    server = None
    if settings.api_enabled:
        import contextlib

        import uvicorn

        class NoSignalServer(uvicorn.Server):
            """We own SIGINT/SIGTERM (graceful shutdown); stop uvicorn from replacing our handlers."""

            def install_signal_handlers(self) -> None:  # uvicorn < 0.30
                pass

            @contextlib.contextmanager
            def capture_signals(self):  # uvicorn >= 0.30
                yield

        config = uvicorn.Config(create_api(ctx), host=settings.api_host, port=settings.api_port,
                                log_level="warning", access_log=False, proxy_headers=True,
                                forwarded_allow_ips="127.0.0.1")
        server = NoSignalServer(config)
        tasks.append(asyncio.create_task(server.serve()))
        log.info("API listening on %s:%d", settings.api_host, settings.api_port)

    tg_app = build_application(ctx)
    await start_polling(tg_app, ctx)
    tasks.append(asyncio.create_task(polling_watchdog(tg_app, ctx)))
    log.info("RIA is up")

    await stop.wait()
    log.info("Shutting down gracefully...")
    await stop_polling(tg_app, ctx)             # stop taking new Telegram updates
    await ctx.queue.shutdown(drain_timeout=20)  # let in-flight replies finish
    await ctx.engine.drain(5)
    if server:
        server.should_exit = True
    for t in tasks:
        t.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)
    await ctx.router.close()
    await ctx.mongo.close()
    lock.release()
    log.info("Bye")
    return 0


def main() -> None:
    sys.exit(asyncio.run(run()))


if __name__ == "__main__":
    main()
