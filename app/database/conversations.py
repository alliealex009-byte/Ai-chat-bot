"""Conversation history. All reads/writes are scoped by user_id."""
from __future__ import annotations

from datetime import timedelta
from typing import Any

from app.database.mongo import utcnow


class ConversationRepo:
    def __init__(self, db: Any, max_per_user: int = 200):
        self.col = db.messages
        self.max_per_user = max_per_user

    async def add(self, user_id: int, role: str, content: str, channel: str = "telegram") -> None:
        assert role in ("user", "assistant")
        await self.col.insert_one(
            {"user_id": user_id, "role": role, "content": content, "channel": channel, "ts": utcnow()}
        )
        # Cheap cap: only check occasionally (when role == user) to avoid extra round trips.
        if role == "user":
            total = await self.col.count_documents({"user_id": user_id})
            if total > self.max_per_user + 20:
                excess = total - self.max_per_user
                old = await self.col.find({"user_id": user_id}).sort("ts", 1).limit(excess).to_list(length=excess)
                ids = [d["_id"] for d in old]
                if ids:
                    await self.col.delete_many({"_id": {"$in": ids}})

    async def recent(self, user_id: int, limit: int, char_budget: int) -> list[dict]:
        """Most recent messages (chronological), trimmed to fit a character budget."""
        docs = await self.col.find({"user_id": user_id}).sort("ts", -1).limit(limit).to_list(length=limit)
        picked: list[dict] = []
        used = 0
        for d in docs:  # newest first
            size = len(d["content"])
            if picked and used + size > char_budget:
                break
            picked.append({"role": d["role"], "content": d["content"]})
            used += size
        picked.reverse()
        while picked and picked[0]["role"] != "user":  # always start with a user turn
            picked.pop(0)
        return picked

    async def last_n_text(self, user_id: int, n: int) -> list[dict]:
        docs = await self.col.find({"user_id": user_id}).sort("ts", -1).limit(n).to_list(length=n)
        return [{"role": d["role"], "content": d["content"]} for d in reversed(docs)]

    async def count(self, user_id: int) -> int:
        return await self.col.count_documents({"user_id": user_id})

    async def clear(self, user_id: int) -> int:
        res = await self.col.delete_many({"user_id": user_id})
        return res.deleted_count

    async def cleanup_older_than(self, days: int) -> int:
        cutoff = utcnow() - timedelta(days=days)
        res = await self.col.delete_many({"ts": {"$lt": cutoff}})
        return res.deleted_count

    async def total(self) -> int:
        return await self.col.count_documents({})
