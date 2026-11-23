"""Gentle re-engagement: a short friendly message to users who went quiet for 2+ days.

Limits: at most 3 unanswered nudges per user, at least 3 days apart, ~20 users per cycle, owner can switch it off,
users who blocked the bot are never retried. Any message from the user resets the counter.
"""
from __future__ import annotations

import asyncio
import logging
import random
from datetime import timedelta

from app.database.mongo import utcnow

log = logging.getLogger(__name__)

NUDGES = [
    "{name}, kahan gayab ho yaar? 🥺 teri baatein miss kar rahi thi, ek 'hi' toh bol do 💗",
    "oyeee {name} 👀 itne din ho gaye! chai pe chat karein? ☕",
    "arre {name}! sab theek? aaj ka kuch interesting hua? batao na 😌",
    "{name}, suno na ✨ kal ki baat adhuri reh gayi thi, wapas aao 😄",
]
INACTIVE_FOR = timedelta(hours=48)
GAP_BETWEEN = timedelta(hours=72)


async def run_once(ctx, bot, now=None) -> int:
    rt = await ctx.runtime.all()
    if not rt["bot_enabled"] or not rt["nudges_enabled"]:
        return 0
    now = now or utcnow()
    sent = 0
    for u in await ctx.users.nudge_candidates(now - INACTIVE_FOR):
        last = u.get("last_nudge")
        if u["_id"] in ctx.banned or (last is not None and now - last < GAP_BETWEEN):
            continue
        name = (u.get("preferred_name") or u.get("first_name") or "dost").strip() or "dost"
        try:
            await bot.send_message(chat_id=u["_id"], text=random.choice(NUDGES).format(name=name[:30]))
            await ctx.users.mark_nudged(u["_id"])
            sent += 1
        except Exception as e:  # noqa: BLE001
            if type(e).__name__ in ("Forbidden", "BadRequest"):  # blocked the bot / chat gone: never retry
                await ctx.users.set_blocked(u["_id"], True)
            else:
                log.info("nudge failed: %s", type(e).__name__)
        await asyncio.sleep(0.2)
    return sent


async def nudge_loop(ctx, bot, interval: int = 1800) -> None:
    while True:
        try:
            await asyncio.sleep(interval)
            n = await run_once(ctx, bot)
            if n:
                log.info("Sent %d re-engagement nudges", n)
        except asyncio.CancelledError:
            raise
        except Exception as e:  # noqa: BLE001
            log.warning("nudge loop error: %s", type(e).__name__)
