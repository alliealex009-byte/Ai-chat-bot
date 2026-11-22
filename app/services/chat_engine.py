"""Channel-independent chat engine shared by the Telegram bot and the HTTP API.

Both channels call the same code, so history and memories are shared per user_id.
"""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Optional

from app.ai.errors import AIError, AIModelMissing, AITimeout
from app.ai.prompts import looks_like_injection, sanitize_user_text
from app.ai.router import AIRouter
from app.config import Settings
from app.database.conversations import ConversationRepo
from app.database.memories import MemoryRepo
from app.database.users import UserRepo
from app.database.web import WebAuthRepo
from app.personality import build_system_prompt, wants_long_answer
from app.services.memory import MemoryService
from app.services.queue import InferenceQueue, QueueClosed, QueueFull, QueueTimeout, UserBusy

log = logging.getLogger(__name__)

# User-facing, safe (no internals). Kept in RIA's voice.
MSG_BUSY = "Abhi thodi bheed hai yaar 🥺 Ek minute baad try karo na!"
MSG_USER_BUSY = "Ruko ruko, pehle wale message ka reply aa raha hai 😅"
MSG_ERROR = "Uff, mera dimag thoda hang ho gaya 😵 Thodi der baad phir bolo na!"
MSG_TIMEOUT = "Aaj sochne mein bahut time lag raha hai 😅 Ek baar phir bhejo?"
MSG_EMPTY = "Kuch likho toh sahi 😄"
MSG_DB_ERROR = "Mera memory wala hissa abhi so raha hai 😴 Thodi der baad aao!"


@dataclass
class ChatReply:
    status: str  # ok | busy | user_busy | error | timeout | empty | db_error
    text: str
    provider: Optional[str] = None
    model: Optional[str] = None
    latency_ms: int = 0


class ChatEngine:
    def __init__(self, settings: Settings, router: AIRouter, queue: InferenceQueue, users: UserRepo,
                 conversations: ConversationRepo, memories: MemoryRepo, memory_service: MemoryService,
                 web_auth: WebAuthRepo):
        self.s = settings
        self.router = router
        self.queue = queue
        self.users = users
        self.conversations = conversations
        self.memories = memories
        self.memory_service = memory_service
        self.web_auth = web_auth
        self.started_at = time.time()
        self.stats = {"messages": 0, "ok": 0, "errors": 0, "busy": 0, "injection_attempts": 0,
                      "by_channel": {"telegram": 0, "web": 0}}
        self._bg: set[asyncio.Task] = set()

    # -- chat --------------------------------------------------------------
    async def chat(self, user_id: int, text: str, channel: str = "telegram",
                   first_name: str = "", username: str = "") -> ChatReply:
        text = sanitize_user_text(text, self.s.max_input_chars)
        if not text:
            return ChatReply("empty", MSG_EMPTY)
        self.stats["messages"] += 1
        self.stats["by_channel"][channel] = self.stats["by_channel"].get(channel, 0) + 1
        if looks_like_injection(text):
            self.stats["injection_attempts"] += 1
            log.warning("Possible prompt-injection attempt user=%s", user_id)

        async def job() -> ChatReply:
            user = await self.users.get_or_create(user_id, first_name, username)
            history = await self.conversations.recent(user_id, self.s.history_messages, self.s.history_char_budget)
            memories = await self.memory_service.prompt_memories(user_id) if user.get("memory_enabled", True) else []
            long_form = wants_long_answer(text)
            system = build_system_prompt(user.get("language", self.s.default_language),
                                         user.get("preferred_name") or user.get("first_name"), memories, long_form)
            messages = [{"role": "system", "content": system}, *history, {"role": "user", "content": text}]
            result = await self.router.chat(
                messages, max_tokens=self.s.ai_max_tokens_long if long_form else self.s.ai_max_tokens
            )
            await self.conversations.add(user_id, "user", text, channel)
            await self.conversations.add(user_id, "assistant", result.text, channel)
            await self.users.bump_counters(user_id)
            return ChatReply("ok", result.text, result.provider, result.model, result.latency_ms)

        try:
            reply = await self.queue.submit(user_id, job)
        except UserBusy:
            return ChatReply("user_busy", MSG_USER_BUSY)
        except (QueueFull, QueueClosed):
            self.stats["busy"] += 1
            return ChatReply("busy", MSG_BUSY)
        except (QueueTimeout, AITimeout):
            self.stats["errors"] += 1
            return ChatReply("timeout", MSG_TIMEOUT)
        except AIModelMissing:
            self.stats["errors"] += 1
            return ChatReply("error", MSG_ERROR)
        except AIError:
            self.stats["errors"] += 1
            return ChatReply("error", MSG_ERROR)
        except Exception as e:  # noqa: BLE001 - DB or unexpected; never leak details
            self.stats["errors"] += 1
            log.exception("chat pipeline failed user=%s: %s", user_id, type(e).__name__)
            name = type(e).__module__.split(".")[0]
            return ChatReply("db_error" if name == "pymongo" else "error",
                             MSG_DB_ERROR if name == "pymongo" else MSG_ERROR)

        self.stats["ok"] += 1
        self._spawn(self.memory_service.maybe_extract(user_id))
        return reply

    def _spawn(self, coro) -> None:
        task = asyncio.create_task(self._safe(coro))
        self._bg.add(task)
        task.add_done_callback(self._bg.discard)

    @staticmethod
    async def _safe(coro) -> None:
        try:
            await coro
        except Exception as e:  # noqa: BLE001
            log.warning("background task failed: %s", type(e).__name__)

    async def drain(self, timeout: float = 10.0) -> None:
        if self._bg:
            await asyncio.wait(list(self._bg), timeout=timeout)

    # -- user data ---------------------------------------------------------
    async def reset(self, user_id: int) -> int:
        return await self.conversations.clear(user_id)

    async def forget(self, user_id: int) -> dict:
        """Delete ALL stored data for a user (history, memories, profile, web sessions)."""
        msgs = await self.conversations.clear(user_id)
        mems = await self.memories.delete_all(user_id)
        await self.web_auth.revoke_all(user_id)
        await self.users.delete(user_id)
        return {"messages": msgs, "memories": mems}

    async def history_for_web(self, user_id: int, limit: int = 40) -> list[dict]:
        return await self.conversations.last_n_text(user_id, limit)
