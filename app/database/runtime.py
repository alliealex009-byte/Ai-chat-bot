"""Owner-controlled runtime switches, stored in MongoDB (document _id="global") with a short in-memory cache."""
from __future__ import annotations

import time
from typing import Any

DEFAULTS: dict[str, Any] = {
    "bot_enabled": True,       # master switch
    "dm_enabled": True,        # reply in private chats
    "group_enabled": True,     # reply in groups
    "stickers_enabled": True,
    "sticker_chance": 15,      # percent of replies that may get a sticker
}
CHANCE_STEPS = [0, 5, 15, 30, 50]


class RuntimeSettings:
    def __init__(self, db: Any, ttl: float = 10.0):
        self.col = db.runtime
        self.ttl = ttl
        self._cache: dict[str, Any] | None = None
        self._at = 0.0

    async def all(self) -> dict[str, Any]:
        now = time.monotonic()
        if self._cache is None or now - self._at > self.ttl:
            doc = await self.col.find_one({"_id": "global"}) or {}
            self._cache = {**DEFAULTS, **{k: doc[k] for k in DEFAULTS if k in doc}}
            self._at = now
        return dict(self._cache)

    async def set(self, key: str, value: Any) -> None:
        if key not in DEFAULTS:
            raise KeyError(key)
        await self.col.update_one({"_id": "global"}, {"$set": {key: value}}, upsert=True)
        self._cache = None  # next read refreshes

    async def toggle(self, key: str) -> bool:
        cur = (await self.all())[key]
        await self.set(key, not cur)
        return not cur

    async def cycle_chance(self) -> int:
        cur = (await self.all())["sticker_chance"]
        nxt = CHANCE_STEPS[(CHANCE_STEPS.index(cur) + 1) % len(CHANCE_STEPS)] if cur in CHANCE_STEPS else 15
        await self.set("sticker_chance", nxt)
        return nxt
