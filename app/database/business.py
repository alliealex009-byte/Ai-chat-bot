"""Telegram Business ("Secretary mode") connections: which account connected the bot and what it may do."""
from __future__ import annotations

from typing import Any, Optional

from app.database.mongo import utcnow


class BusinessRepo:
    def __init__(self, db: Any):
        self.col = db.business_connections

    async def upsert(self, conn_id: str, user_id: int, user_name: str, can_reply: bool, is_enabled: bool) -> None:
        await self.col.update_one(
            {"_id": conn_id},
            {"$set": {"user_id": user_id, "user_name": (user_name or "")[:60], "can_reply": bool(can_reply),
                      "is_enabled": bool(is_enabled), "updated_at": utcnow()},
             "$setOnInsert": {"created_at": utcnow()}},
            upsert=True,
        )

    async def get(self, conn_id: str) -> Optional[dict]:
        return await self.col.find_one({"_id": conn_id})

    async def active(self) -> list[dict]:
        return await self.col.find({"is_enabled": True}).to_list(100)

    async def count_active(self) -> int:
        return await self.col.count_documents({"is_enabled": True})
