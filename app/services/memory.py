"""Long-term memory: selective extraction with Gemma, with safeguards against sensitive data."""
from __future__ import annotations

import logging

from app.ai.errors import AIError
from app.ai.prompts import MEMORY_EXTRACT_SYSTEM, is_sensitive, parse_memory_json
from app.ai.router import AIRouter
from app.config import Settings
from app.database.conversations import ConversationRepo
from app.database.memories import MemoryRepo
from app.database.users import UserRepo
from app.services.queue import InferenceQueue, QueueFull, UserBusy, QueueTimeout, QueueClosed

log = logging.getLogger(__name__)


class MemoryService:
    def __init__(self, settings: Settings, router: AIRouter, queue: InferenceQueue,
                 users: UserRepo, conversations: ConversationRepo, memories: MemoryRepo):
        self.s = settings
        self.router = router
        self.queue = queue
        self.users = users
        self.conversations = conversations
        self.memories = memories

    async def prompt_memories(self, user_id: int) -> list[str]:
        if not self.s.memory_enabled:
            return []
        return await self.memories.top_texts(user_id, self.s.memories_in_prompt)

    async def maybe_extract(self, user_id: int) -> int:
        """Extract memories if enough new messages accumulated. Returns number of new memories."""
        if not self.s.memory_enabled:
            return 0
        user = await self.users.get(user_id)
        if not user or not user.get("memory_enabled", True):
            return 0
        if user.get("msgs_since_extract", 0) < self.s.memory_extract_every_n_messages:
            return 0
        n = self.s.memory_extract_every_n_messages * 2
        recent = await self.conversations.last_n_text(user_id, n)
        # Only what the USER said: RIA's own lines are never turned into facts about the user.
        user_lines = [m["content"] for m in recent if m["role"] == "user" and not is_sensitive(m["content"])]
        if not user_lines:
            await self.users.reset_extract_counter(user_id)
            return 0
        transcript = "\n".join(f"- {line[:300]}" for line in user_lines[-self.s.memory_extract_every_n_messages:])
        messages = [
            {"role": "system", "content": MEMORY_EXTRACT_SYSTEM},
            {"role": "user", "content": f"User messages:\n{transcript}\n\nJSON array:"},
        ]

        async def job():
            return await self.router.ollama.chat(messages, max_tokens=160, temperature=0.2)

        try:
            result = await self.queue.submit(user_id, job)
        except (QueueFull, UserBusy, QueueTimeout, QueueClosed):
            return 0  # try again later; counter not reset
        except AIError as e:
            log.info("Memory extraction skipped: %s", type(e).__name__)
            return 0
        facts = parse_memory_json(result.text)
        added = 0
        for fact in facts:
            if await self.memories.upsert(user_id, fact, source="auto"):
                added += 1
        await self.users.reset_extract_counter(user_id)
        log.info("Memory extraction user=%s new=%d", user_id, added)
        return added
