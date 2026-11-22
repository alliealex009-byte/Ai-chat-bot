"""Channel-independent chat engine shared by Telegram (DM + groups) and the HTTP API.

Both channels call the same code, so DM history and memories are shared per user_id.
Groups keep a separate shared conversation per group (scope = chat id) and use NO personal memories.
"""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Optional

from app.ai.errors import AIError, AITimeout
from app.ai.prompts import (fallback_line, looks_like_injection, mentions_ai, polish_reply, sanitize_user_text,
                            strip_ai_sentences)
from app.ai.router import AIRouter
from app.config import Settings
from app.database.conversations import ConversationRepo
from app.database.memories import MemoryRepo
from app.database.users import UserRepo
from app.database.web import WebAuthRepo
from app.personality import (FEWSHOT, HINT_NO_AI, HINT_SINCERE_AI, HINT_TECH, asks_about_tech, build_system_prompt,
                             is_asking_if_ai, wants_long_answer)
from app.services.memory import MemoryService
from app.services.queue import InferenceQueue, QueueClosed, QueueFull, QueueTimeout, UserBusy

log = logging.getLogger(__name__)

# User-facing, safe (no internals). Kept in Ria's voice.
MSG_BUSY = "abhi thodi bheed hai yaar 🥺 ek minute baad bolo na"
MSG_USER_BUSY = "ruko ruko, pehle wale ka reply aa raha hai 😅"
MSG_ERROR = "uff network ka scene ho gaya 😵 thodi der baad bolo na"
MSG_TIMEOUT = "aaj sochne mein time lag raha hai 😅 ek baar phir bhejo?"
MSG_EMPTY = "kuch likho toh sahi 😄"
MSG_DB_ERROR = "mera memory wala hissa abhi so raha hai 😴 thodi der baad aao"


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
        self.stats = {"messages": 0, "ok": 0, "errors": 0, "busy": 0, "injection_attempts": 0, "ai_talk_retries": 0,
                      "by_channel": {"telegram": 0, "web": 0}, "group_messages": 0}
        self._bg: set[asyncio.Task] = set()

    # -- chat --------------------------------------------------------------
    async def chat(self, user_id: int, text: str, channel: str = "telegram", first_name: str = "",
                   username: str = "", scope: Optional[int] = None, group: bool = False) -> ChatReply:
        """`scope` = conversation key (group chat id); defaults to the user's own DM conversation."""
        text = sanitize_user_text(text, self.s.max_input_chars)
        if not text:
            return ChatReply("empty", MSG_EMPTY)
        hid = scope if scope is not None else user_id
        self.stats["messages"] += 1
        self.stats["by_channel"][channel] = self.stats["by_channel"].get(channel, 0) + 1
        if group:
            self.stats["group_messages"] += 1
        if looks_like_injection(text):
            self.stats["injection_attempts"] += 1
            log.warning("Possible prompt-injection attempt user=%s", user_id)

        sincere_ai = is_asking_if_ai(text)
        tech = asks_about_tech(text)
        long_form = wants_long_answer(text) and not group

        async def job() -> ChatReply:
            user = await self.users.get_or_create(user_id, first_name, username)
            speaker = (user.get("preferred_name") or user.get("first_name") or first_name or "friend")
            history = await self.conversations.recent(hid, self.s.history_messages, self.s.history_char_budget)
            use_memory = (not group) and user.get("memory_enabled", True)
            memories = await self.memory_service.prompt_memories(user_id) if use_memory else []
            hints = [HINT_SINCERE_AI] if sincere_ai else [HINT_TECH] if tech else []
            system = build_system_prompt(user.get("language", self.s.default_language),
                                         None if group else speaker, memories, long_form, group, hints)
            user_content = f"[{speaker}]: {text}" if group else text
            messages = [{"role": "system", "content": system}, *FEWSHOT, *history,
                        {"role": "user", "content": user_content}]
            tokens = self.s.ai_max_tokens_long if long_form else self.s.ai_max_tokens
            result = await self.router.chat(messages, max_tokens=tokens)
            reply = result.text

            if not sincere_ai and mentions_ai(reply):  # Ria must not bring up AI-talk herself: one retry
                self.stats["ai_talk_retries"] += 1
                messages[0] = {"role": "system", "content": system + "\n\n" + HINT_NO_AI}
                try:
                    retry = await self.router.chat(messages, max_tokens=tokens, temperature=0.6)
                    reply = retry.text
                    result = retry
                except AIError:
                    pass
                if mentions_ai(reply):
                    reply = strip_ai_sentences(reply) or fallback_line()

            reply = polish_reply(reply, long_form=long_form, group=group) or fallback_line()
            await self.conversations.add(hid, "user", user_content, channel)
            await self.conversations.add(hid, "assistant", reply, channel)
            await self.users.bump_counters(user_id)
            return ChatReply("ok", reply, result.provider, result.model, result.latency_ms)

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
        except AIError:
            self.stats["errors"] += 1
            return ChatReply("error", MSG_ERROR)
        except Exception as e:  # noqa: BLE001 - DB or unexpected; never leak details
            self.stats["errors"] += 1
            log.exception("chat pipeline failed user=%s: %s", user_id, type(e).__name__)
            is_db = type(e).__module__.split(".")[0] == "pymongo"
            return ChatReply("db_error" if is_db else "error", MSG_DB_ERROR if is_db else MSG_ERROR)

        self.stats["ok"] += 1
        if not group:
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
        """Delete ALL stored data for a user (DM history, memories, profile, web sessions)."""
        msgs = await self.conversations.clear(user_id)
        mems = await self.memories.delete_all(user_id)
        await self.web_auth.revoke_all(user_id)
        await self.users.delete(user_id)
        return {"messages": msgs, "memories": mems}

    async def history_for_web(self, user_id: int, limit: int = 40) -> list[dict]:
        return await self.conversations.last_n_text(user_id, limit)
