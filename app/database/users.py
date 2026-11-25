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
                    "msgs_since_summary": 0,
                },
                "$set": {"first_name": (first_name or "")[:64], "username": (username or "")[:64],
                         "username_lc": (username or "").lower()[:64], "last_seen": now,
                         "nudges_sent": 0},
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

    async def set_gender(self, user_id: int, gender: Optional[str]) -> None:
        if gender in ("male", "female", None):
            await self.col.update_one({"_id": user_id}, {"$set": {"gender": gender}})

    async def set_memory_enabled(self, user_id: int, enabled: bool) -> None:
        await self.col.update_one({"_id": user_id}, {"$set": {"memory_enabled": bool(enabled)}})

    async def bump_counters(self, user_id: int) -> dict:
        await self.col.update_one({"_id": user_id}, {"$inc": {"message_count": 1, "msgs_since_extract": 1, "msgs_since_summary": 1}})
        return await self.col.find_one({"_id": user_id}) or {}

    async def reset_extract_counter(self, user_id: int) -> None:
        await self.col.update_one({"_id": user_id}, {"$set": {"msgs_since_extract": 0}})

    async def set_summary(self, user_id: int, summary: Optional[str]) -> None:
        summary = " ".join((summary or "").split())[:600] or None
        await self.col.update_one({"_id": user_id}, {"$set": {"summary": summary, "msgs_since_summary": 0}})

    async def reset_summary_counter(self, user_id: int) -> None:
        await self.col.update_one({"_id": user_id}, {"$set": {"msgs_since_summary": 0}})

    async def set_region(self, user_id: int, region: Optional[str]) -> None:
        await self.col.update_one({"_id": user_id}, {"$set": {"region": region}})

    async def touch_streak(self, user_id: int) -> int:
        """Consecutive-days chat streak (India time). Returns the current streak."""
        from datetime import timedelta
        today = (utcnow() + timedelta(hours=5, minutes=30)).date()
        doc = await self.col.find_one({"_id": user_id}) or {}
        last = doc.get("last_active_date")
        streak = int(doc.get("streak", 0))
        if last == today.isoformat():
            return streak or 1
        streak = streak + 1 if last == (today - timedelta(days=1)).isoformat() else 1
        await self.col.update_one({"_id": user_id}, {"$set": {"streak": streak, "last_active_date": today.isoformat()}})
        return streak

    async def nudge_candidates(self, inactive_before, limit: int = 20, max_nudges: int = 3) -> list[dict]:
        flt = {"last_seen": {"$lt": inactive_before}, "banned": {"$ne": True}, "blocked": {"$ne": True},
               "nudges_sent": {"$lt": max_nudges}}
        return await self.col.find(flt).limit(limit).to_list(length=limit)

    async def mark_nudged(self, user_id: int) -> None:
        await self.col.update_one({"_id": user_id}, {"$inc": {"nudges_sent": 1}, "$set": {"last_nudge": utcnow()}})

    async def delete(self, user_id: int) -> None:
        await self.col.delete_one({"_id": user_id})

    async def count(self) -> int:
        return await self.col.count_documents({})

    # -- owner controls ------------------------------------------------------
    async def set_banned(self, user_id: int, banned: bool) -> None:
        await self.col.update_one({"_id": user_id}, {"$set": {"banned": banned}}, upsert=True)

    async def list_banned(self) -> list[int]:
        return [d["_id"] for d in await self.col.find({"banned": True}).to_list(length=5000)]

    async def set_blocked(self, user_id: int, blocked: bool) -> None:
        await self.col.update_one({"_id": user_id}, {"$set": {"blocked": blocked}})

    async def broadcast_ids(self) -> list[int]:
        docs = await self.col.find({"blocked": {"$ne": True}, "banned": {"$ne": True}}).to_list(length=100000)
        return [d["_id"] for d in docs if isinstance(d["_id"], int) and d["_id"] > 0]

    async def find_by_username(self, username: str) -> Optional[dict]:
        return await self.col.find_one({"username_lc": username.lstrip("@").lower()})
