"""Known group chats (for owner broadcast / per-group on-off)."""
from __future__ import annotations

from typing import Any, Optional

from app.database.mongo import utcnow


class ChatsRepo:
    def __init__(self, db: Any):
        self.col = db.chats

    async def touch(self, chat_id: int, chat_type: str, title: str = "") -> None:
        await self.col.update_one(
            {"_id": chat_id},
            {"$set": {"type": chat_type, "title": (title or "")[:100], "last_seen": utcnow(), "active": True},
             "$setOnInsert": {"enabled": True, "created_at": utcnow()}},
            upsert=True,
        )

    async def get(self, chat_id: int) -> Optional[dict]:
        return await self.col.find_one({"_id": chat_id})

    async def set_active(self, chat_id: int, active: bool) -> None:
        await self.col.update_one({"_id": chat_id}, {"$set": {"active": active}})

    async def set_enabled(self, chat_id: int, enabled: bool) -> None:
        await self.col.update_one({"_id": chat_id}, {"$set": {"enabled": enabled}})

    async def groups(self, limit: int = 200) -> list[dict]:
        docs = await self.col.find({"active": True}).sort("last_seen", -1).limit(limit).to_list(length=limit)
        return [d for d in docs if d.get("type") in ("group", "supergroup")]

    async def group_ids(self) -> list[int]:
        return [d["_id"] for d in await self.groups(5000)]

    async def count(self) -> int:
        return len(await self.groups(5000))
