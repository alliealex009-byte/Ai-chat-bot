"""Throttled broadcast with flood-wait and blocked-chat handling (transport-agnostic, easy to test)."""
from __future__ import annotations

import asyncio
import logging
from typing import Awaitable, Callable, Optional

log = logging.getLogger(__name__)


class Blocked(Exception):
    """Chat/user is unreachable (bot blocked, kicked, chat deleted)."""


class FloodWait(Exception):
    def __init__(self, seconds: float):
        super().__init__(f"flood wait {seconds}s")
        self.seconds = seconds


async def broadcast(
    targets: list[int],
    send: Callable[[int], Awaitable[None]],
    on_blocked: Optional[Callable[[int], Awaitable[None]]] = None,
    cancel: Optional[asyncio.Event] = None,
    rate_per_sec: float = 15.0,
) -> dict:
    """Send to each target at a safe rate (Telegram allows ~30 msg/s overall). Returns counters."""
    res = {"sent": 0, "blocked": 0, "failed": 0, "cancelled": False, "total": len(targets)}
    delay = 1.0 / max(rate_per_sec, 0.1)
    for cid in targets:
        if cancel is not None and cancel.is_set():
            res["cancelled"] = True
            break
        for attempt in range(2):
            try:
                await send(cid)
                res["sent"] += 1
                break
            except FloodWait as e:
                if attempt == 0:
                    await asyncio.sleep(min(e.seconds + 1, 60))
                    continue
                res["failed"] += 1
            except Blocked:
                res["blocked"] += 1
                if on_blocked:
                    await on_blocked(cid)
                break
            except Exception as e:  # noqa: BLE001
                log.warning("broadcast to %s failed: %s", cid, type(e).__name__)
                res["failed"] += 1
                break
        await asyncio.sleep(delay)
    return res
