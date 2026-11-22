"""Web-chat identity: one-time link codes (created from Telegram) -> per-user session tokens.

Only SHA-256 hashes are stored. A session token identifies exactly one Telegram user, so web
chat shares the same history and memories as Telegram while staying isolated per user.
"""
from __future__ import annotations

import hashlib
import secrets
from datetime import timedelta
from typing import Any, Optional

from app.database.mongo import utcnow

_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # no ambiguous chars


def _h(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


class WebAuthRepo:
    def __init__(self, db: Any, code_ttl_seconds: int = 600, session_ttl_days: int = 30):
        self.codes = db.link_codes
        self.sessions = db.web_sessions
        self.code_ttl = code_ttl_seconds
        self.session_ttl = session_ttl_days

    async def create_link_code(self, user_id: int) -> str:
        await self.codes.delete_many({"user_id": user_id})  # one active code per user
        code = "".join(secrets.choice(_ALPHABET) for _ in range(8))
        await self.codes.insert_one(
            {"code_hash": _h(code), "user_id": user_id, "expires_at": utcnow() + timedelta(seconds=self.code_ttl)}
        )
        return code

    async def redeem(self, code: str) -> Optional[str]:
        """Consume a link code and return a new session token (or None if invalid/expired)."""
        code = (code or "").strip().upper().replace("-", "").replace(" ", "")
        if len(code) != 8:
            return None
        doc = await self.codes.find_one({"code_hash": _h(code)})
        if not doc:
            return None
        await self.codes.delete_one({"_id": doc["_id"]})  # single use
        if doc["expires_at"] < utcnow():
            return None
        token = secrets.token_urlsafe(32)
        await self.sessions.insert_one(
            {
                "token_hash": _h(token),
                "user_id": doc["user_id"],
                "created_at": utcnow(),
                "expires_at": utcnow() + timedelta(days=self.session_ttl),
            }
        )
        return token

    async def user_for_token(self, token: str) -> Optional[int]:
        if not token:
            return None
        doc = await self.sessions.find_one({"token_hash": _h(token)})
        if not doc or doc["expires_at"] < utcnow():
            return None
        return int(doc["user_id"])

    async def revoke(self, token: str) -> None:
        await self.sessions.delete_one({"token_hash": _h(token)})

    async def revoke_all(self, user_id: int) -> None:
        await self.sessions.delete_many({"user_id": user_id})
        await self.codes.delete_many({"user_id": user_id})
