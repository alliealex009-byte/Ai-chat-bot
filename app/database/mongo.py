"""MongoDB connection (PyMongo native async driver) with pooling and indexes.

Motor is deprecated/end-of-life, so we use pymongo.AsyncMongoClient (pymongo >= 4.13).
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Optional

from app.config import Settings

log = logging.getLogger(__name__)


class Mongo:
    def __init__(self, settings: Settings):
        self.s = settings
        self.client: Any = None
        self.db: Any = None

    async def connect(self, retries: int = 5) -> None:
        from pymongo import AsyncMongoClient  # imported lazily so tests can run without the driver

        self.client = AsyncMongoClient(
            self.s.effective_mongo_uri,
            maxPoolSize=self.s.mongo_max_pool_size,
            minPoolSize=1,
            serverSelectionTimeoutMS=self.s.mongo_timeout_ms,
            connectTimeoutMS=self.s.mongo_timeout_ms,
            socketTimeoutMS=15000,
            retryWrites=True,
            retryReads=True,
            tz_aware=True,
        )
        self.db = self.client[self.s.mongo_db_name]
        delay = 1
        for attempt in range(1, retries + 1):
            if await self.ping():
                log.info("MongoDB connected (db=%s)", self.s.mongo_db_name)
                await self.ensure_indexes()
                return
            log.warning("MongoDB not reachable (attempt %d/%d); retrying in %ss", attempt, retries, delay)
            await asyncio.sleep(delay)
            delay = min(delay * 2, 15)
        raise RuntimeError("Could not connect to MongoDB; check MONGO_* settings and the ria-mongo container")

    async def ping(self) -> bool:
        try:
            await self.client.admin.command("ping")
            return True
        except Exception:  # noqa: BLE001
            return False

    async def ensure_indexes(self) -> None:
        db = self.db
        await db.messages.create_index([("user_id", 1), ("ts", -1)])
        await db.messages.create_index([("ts", 1)])
        await db.memories.create_index([("user_id", 1), ("key", 1)], unique=True)
        await db.memories.create_index([("user_id", 1), ("updated_at", -1)])
        await db.web_sessions.create_index([("token_hash", 1)], unique=True)
        await db.web_sessions.create_index([("user_id", 1)])
        await db.web_sessions.create_index([("expires_at", 1)], expireAfterSeconds=0)
        await db.users.create_index([("username_lc", 1)])
        await db.business_connections.create_index([("user_id", 1)])
        await db.chats.create_index([("active", 1), ("last_seen", -1)])
        await db.stickers.create_index([("set_name", 1)])
        await db.link_codes.create_index([("code_hash", 1)], unique=True)
        await db.link_codes.create_index([("expires_at", 1)], expireAfterSeconds=0)

    async def close(self) -> None:
        if self.client is not None:
            await self.client.close()


def utcnow():
    from datetime import datetime, timezone

    return datetime.now(timezone.utc)
