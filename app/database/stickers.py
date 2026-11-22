"""Sticker library managed by the owner panel. Ria sends stickers from here only."""
from __future__ import annotations

import random
import time
from typing import Any, Iterable, Optional

from app.database.mongo import utcnow

MAX_STICKERS = 3000


class StickersRepo:
    def __init__(self, db: Any):
        self.col = db.stickers
        self._cache: Optional[list[dict]] = None
        self._at = 0.0

    async def _all(self) -> list[dict]:
        if self._cache is None or time.monotonic() - self._at > 60:
            self._cache = await self.col.find({}).to_list(length=MAX_STICKERS)
            self._at = time.monotonic()
        return self._cache

    def _dirty(self) -> None:
        self._cache = None

    async def add(self, unique_id: str, file_id: str, emoji: str = "", set_name: str = "") -> bool:
        """Returns True if new."""
        existed = await self.col.find_one({"_id": unique_id})
        await self.col.update_one(
            {"_id": unique_id},
            {"$set": {"file_id": file_id, "emoji": (emoji or "").replace("️", ""),
                      "set_name": set_name or "", "added_at": utcnow()}},
            upsert=True,
        )
        self._dirty()
        return existed is None

    async def add_many(self, items: Iterable[dict]) -> int:
        n = 0
        for it in items:
            if await self.add(it["unique_id"], it["file_id"], it.get("emoji", ""), it.get("set_name", "")):
                n += 1
        return n

    async def remove(self, unique_id: str) -> bool:
        res = await self.col.delete_one({"_id": unique_id})
        self._dirty()
        return res.deleted_count > 0

    async def remove_pack(self, set_name: str) -> int:
        if not set_name:
            return 0
        res = await self.col.delete_many({"set_name": set_name})
        self._dirty()
        return res.deleted_count

    async def remove_by_file_id(self, file_id: str) -> None:
        await self.col.delete_many({"file_id": file_id})
        self._dirty()

    async def count(self) -> int:
        return len(await self._all())

    async def packs(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for d in await self._all():
            out[d.get("set_name") or "(single stickers)"] = out.get(d.get("set_name") or "(single stickers)", 0) + 1
        return out

    async def pick(self, emojis: Iterable[str] = ()) -> Optional[dict]:
        """Prefer a sticker whose emoji appears in the reply; otherwise any sticker."""
        items = await self._all()
        if not items:
            return None
        wanted = {e.replace("️", "") for e in emojis}
        matches = [d for d in items if d.get("emoji") in wanted] if wanted else []
        return random.choice(matches or items)
