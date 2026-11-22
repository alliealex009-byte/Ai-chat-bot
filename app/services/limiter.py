"""Rate limiting and duplicate-update protection (in-memory, per process)."""
from __future__ import annotations

import time
from collections import OrderedDict, deque
from typing import Callable, Deque, Dict, Hashable


class SlidingWindowLimiter:
    """Allows `limit` events per `window` seconds per key."""

    def __init__(self, limit: int, window_seconds: float, clock: Callable[[], float] = time.monotonic):
        self.limit = limit
        self.window = window_seconds
        self.clock = clock
        self._events: Dict[Hashable, Deque[float]] = {}

    def _prune(self, q: Deque[float], now: float) -> None:
        while q and now - q[0] >= self.window:
            q.popleft()

    def allow(self, key: Hashable = "global") -> bool:
        now = self.clock()
        q = self._events.setdefault(key, deque())
        self._prune(q, now)
        if len(q) >= self.limit:
            return False
        q.append(now)
        return True

    def retry_after(self, key: Hashable = "global") -> float:
        q = self._events.get(key)
        if not q:
            return 0.0
        now = self.clock()
        self._prune(q, now)
        if len(q) < self.limit:
            return 0.0
        return max(0.0, self.window - (now - q[0]))

    def gc(self) -> None:
        """Drop idle keys so memory stays bounded."""
        now = self.clock()
        for k in list(self._events):
            q = self._events[k]
            self._prune(q, now)
            if not q:
                del self._events[k]


class DedupeCache:
    """Remembers recently seen ids (e.g. Telegram update_id) in a bounded LRU."""

    def __init__(self, size: int = 5000):
        self.size = size
        self._seen: "OrderedDict[Hashable, None]" = OrderedDict()

    def seen(self, key: Hashable) -> bool:
        """Return True if key was already seen; otherwise record it and return False."""
        if key in self._seen:
            self._seen.move_to_end(key)
            return True
        self._seen[key] = None
        if len(self._seen) > self.size:
            self._seen.popitem(last=False)
        return False
