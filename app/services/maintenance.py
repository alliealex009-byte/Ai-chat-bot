"""Periodic cleanup of old conversation data and limiter state."""
from __future__ import annotations

import asyncio
import logging

from app.config import Settings
from app.database.conversations import ConversationRepo

log = logging.getLogger(__name__)


async def cleanup_loop(settings: Settings, conversations: ConversationRepo, *limiters) -> None:
    interval = settings.cleanup_interval_minutes * 60
    while True:
        try:
            await asyncio.sleep(interval)
            removed = await conversations.cleanup_older_than(settings.conversation_retention_days)
            for lim in limiters:
                lim.gc()
            if removed:
                log.info("Retention cleanup removed %d old messages", removed)
        except asyncio.CancelledError:
            raise
        except Exception as e:  # noqa: BLE001
            log.warning("Cleanup failed: %s", type(e).__name__)
