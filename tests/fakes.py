"""In-memory stand-ins for MongoDB collections and AI providers (no external services needed)."""
from __future__ import annotations

import itertools
from types import SimpleNamespace
from typing import Any, Optional

from app.ai.errors import AIError, AIUnavailable, ChatResult

_ids = itertools.count(1)


def _match(doc: dict, flt: dict) -> bool:
    for k, cond in flt.items():
        v = doc.get(k)
        if isinstance(cond, dict):
            for op, arg in cond.items():
                if op == "$lt" and not (v is not None and v < arg):
                    return False
                if op == "$in" and v not in arg:
                    return False
        elif v != cond:
            return False
    return True


class FakeCursor:
    def __init__(self, docs: list[dict]):
        self.docs = docs

    def sort(self, key: str, direction: int = 1):
        self.docs = sorted(self.docs, key=lambda d: d.get(key), reverse=direction < 0)
        return self

    def limit(self, n: int):
        self.docs = self.docs[:n]
        return self

    async def to_list(self, length: Optional[int] = None):
        return [dict(d) for d in self.docs[:length]]


class FakeCollection:
    def __init__(self):
        self.docs: list[dict] = []

    async def find_one(self, flt: dict):
        for d in self.docs:
            if _match(d, flt):
                return dict(d)
        return None

    def find(self, flt: Optional[dict] = None):
        return FakeCursor([d for d in self.docs if _match(d, flt or {})])

    async def insert_one(self, doc: dict):
        doc = dict(doc)
        doc.setdefault("_id", next(_ids))
        self.docs.append(doc)
        return SimpleNamespace(inserted_id=doc["_id"])

    async def update_one(self, flt: dict, update: dict, upsert: bool = False):
        for d in self.docs:
            if _match(d, flt):
                d.update(update.get("$set", {}))
                for k, n in update.get("$inc", {}).items():
                    d[k] = d.get(k, 0) + n
                return SimpleNamespace(matched_count=1)
        if upsert:
            base = {k: v for k, v in flt.items() if not isinstance(v, dict)}
            base.update(update.get("$setOnInsert", {}))
            base.update(update.get("$set", {}))
            for k, n in update.get("$inc", {}).items():
                base[k] = base.get(k, 0) + n
            base.setdefault("_id", next(_ids))
            self.docs.append(base)
        return SimpleNamespace(matched_count=0)

    async def delete_one(self, flt: dict):
        for i, d in enumerate(self.docs):
            if _match(d, flt):
                del self.docs[i]
                return SimpleNamespace(deleted_count=1)
        return SimpleNamespace(deleted_count=0)

    async def delete_many(self, flt: dict):
        keep = [d for d in self.docs if not _match(d, flt)]
        n = len(self.docs) - len(keep)
        self.docs = keep
        return SimpleNamespace(deleted_count=n)

    async def count_documents(self, flt: dict):
        return sum(1 for d in self.docs if _match(d, flt))


class FakeDB:
    def __init__(self):
        self.users = FakeCollection()
        self.messages = FakeCollection()
        self.memories = FakeCollection()
        self.link_codes = FakeCollection()
        self.web_sessions = FakeCollection()


class FakeProvider:
    """Scriptable AI provider. `script` items: str (reply) or Exception (raised)."""

    def __init__(self, name: str = "ollama", script: Optional[list] = None, default: str = "Hieee! 💗"):
        self.provider = name
        self.model = "gemma3:4b"
        self.script = list(script or [])
        self.default = default
        self.calls: list[list[dict]] = []
        self.enabled = True

    async def chat(self, messages, max_tokens=None, temperature=None):
        self.calls.append(messages)
        item = self.script.pop(0) if self.script else self.default
        if isinstance(item, Exception):
            raise item
        return ChatResult(text=item, provider=self.provider, model=self.model, latency_ms=5)

    async def health(self):
        return {"ok": True, "model": self.model, "model_installed": True, "error": None}


def make_settings(**over: Any):
    from app.config import Settings

    base = dict(telegram_bot_token="123456:ABCDEF_test_token_value_1234567890", mongo_password="pw",
                api_token="a" * 40)
    base.update(over)
    return Settings(**base)
