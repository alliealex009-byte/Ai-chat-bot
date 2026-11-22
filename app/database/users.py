"""User profiles. Every query is keyed by user_id (Telegram numeric id)."""
from __future__ import annotations

from typing import Any, Optional

from app.database.mongo import utcnow

VALID_LANGUAGES = ("hinglish", "hindi", "english")


class UserRepo:
    def __init__(self, db: Any, default_language: str = "hinglish"):
        self.col = db.users
        self.default_language = default_language

    async def get_or_create(self, user_id: int, first_name: str = "", username: str = "") -> dict:
        now = utcnow()
        await self.col.update_one(
            {"_id": user_id},
            {
                "$setOnInsert": {
                    "created_at": now,
                    "language": self.default_language,
                    "preferred_name": None,
                    "memory_enabled": True,
                    "message_count": 0,
                    "msgs_since_extract": 0,
                },
                "$set": {"first_name": (first_name or "")[:64], "username": (username or "")[:64], "last_seen": now},
            },
            upsert=True,
        )
        return await self.col.find_one({"_id": user_id})

    async def get(self, user_id: int) -> Optional[dict]:
        return await self.col.find_one({"_id": user_id})

    async def set_language(self, user_id: int, language: str) -> bool:
        if language not in VALID_LANGUAGES:
            return False
        await self.col.update_one({"_id": user_id}, {"$set": {"language": language}})
        return True

    async def set_preferred_name(self, user_id: int, name: Optional[str]) -> None:
        name = " ".join((name or "").split())[:40] or None
        await self.col.update_one({"_id": user_id}, {"$set": {"preferred_name": name}})

    async def set_memory_enabled(self, user_id: int, enabled: bool) -> None:
        await self.col.update_one({"_id": user_id}, {"$set": {"memory_enabled": bool(enabled)}})

    async def bump_counters(self, user_id: int) -> dict:
        await self.col.update_one({"_id": user_id}, {"$inc": {"message_count": 1, "msgs_since_extract": 1}})
        return await self.col.find_one({"_id": user_id}) or {}

    async def reset_extract_counter(self, user_id: int) -> None:
        await self.col.update_one({"_id": user_id}, {"$set": {"msgs_since_extract": 0}})

    async def delete(self, user_id: int) -> None:
        await self.col.delete_one({"_id": user_id})

    async def count(self) -> int:
        return await self.col.count_documents({})
