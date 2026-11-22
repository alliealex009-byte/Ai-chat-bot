"""Long-term memories (short facts). All operations are scoped by user_id."""
from __future__ import annotations

import hashlib
from typing import Any, Optional

from app.database.mongo import utcnow


def _key(text: str) -> str:
    return hashlib.sha1(" ".join(text.lower().split()).encode()).hexdigest()[:16]


class MemoryRepo:
    def __init__(self, db: Any, max_per_user: int = 50):
        self.col = db.memories
        self.max_per_user = max_per_user

    async def upsert(self, user_id: int, text: str, source: str = "auto") -> bool:
        """Insert a memory, or refresh `updated_at` if the same fact exists. Returns True if new."""
        text = " ".join(text.split())[:160]
        if not text:
            return False
        now = utcnow()
        key = _key(text)
        existing = await self.col.find_one({"user_id": user_id, "key": key})
        if existing:
            await self.col.update_one({"_id": existing["_id"], "user_id": user_id}, {"$set": {"updated_at": now}})
            return False
        await self.col.insert_one(
            {"user_id": user_id, "key": key, "text": text, "source": source, "created_at": now, "updated_at": now}
        )
        total = await self.col.count_documents({"user_id": user_id})
        if total > self.max_per_user:
            excess = total - self.max_per_user
            old = await self.col.find({"user_id": user_id}).sort("updated_at", 1).limit(excess).to_list(length=excess)
            ids = [d["_id"] for d in old]
            if ids:
                await self.col.delete_many({"_id": {"$in": ids}, "user_id": user_id})
        return True

    async def list(self, user_id: int, limit: int = 50) -> list[dict]:
        return await self.col.find({"user_id": user_id}).sort("updated_at", -1).limit(limit).to_list(length=limit)

    async def top_texts(self, user_id: int, limit: int) -> list[str]:
        if limit <= 0:
            return []
        return [d["text"] for d in await self.list(user_id, limit)]

    async def update_text(self, user_id: int, memory_id: Any, new_text: str) -> bool:
        new_text = " ".join(new_text.split())[:160]
        if not new_text:
            return False
        try:
            res = await self.col.update_one(
                {"_id": memory_id, "user_id": user_id},
                {"$set": {"text": new_text, "key": _key(new_text), "updated_at": utcnow(), "source": "user"}},
            )
        except Exception:  # noqa: BLE001 - e.g. DuplicateKeyError: that fact already exists
            return False
        return res.matched_count > 0

    async def delete_one(self, user_id: int, memory_id: Any) -> bool:
        res = await self.col.delete_one({"_id": memory_id, "user_id": user_id})
        return res.deleted_count > 0

    async def delete_all(self, user_id: int) -> int:
        res = await self.col.delete_many({"user_id": user_id})
        return res.deleted_count

    async def count(self, user_id: Optional[int] = None) -> int:
        return await self.col.count_documents({"user_id": user_id} if user_id is not None else {})
