"""Application context: builds and owns all long-lived services (one set per process)."""
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Optional

from app.ai.router import AIRouter
from app.config import Settings
from app.database.chats import ChatsRepo
from app.database.conversations import ConversationRepo
from app.database.memories import MemoryRepo
from app.database.mongo import Mongo
from app.database.runtime import RuntimeSettings
from app.database.stickers import StickersRepo
from app.database.users import UserRepo
from app.database.web import WebAuthRepo
from app.services.chat_engine import ChatEngine
from app.services.limiter import DedupeCache, SlidingWindowLimiter
from app.services.memory import MemoryService
from app.services.queue import InferenceQueue


@dataclass
class AppContext:
    settings: Settings
    mongo: Mongo
    router: AIRouter
    queue: InferenceQueue
    users: UserRepo
    conversations: ConversationRepo
    memories: MemoryRepo
    web_auth: WebAuthRepo
    memory_service: MemoryService
    engine: ChatEngine
    user_limiter: SlidingWindowLimiter
    global_limiter: SlidingWindowLimiter
    dedupe: DedupeCache
    runtime: RuntimeSettings
    chats: ChatsRepo
    stickers: StickersRepo
    chat_limiter: SlidingWindowLimiter
    started_at: float = field(default_factory=time.time)
    banned: set = field(default_factory=set)
    owner_state: dict = field(default_factory=dict)      # owner_id -> pending panel action
    owner_tasks: set = field(default_factory=set)        # running broadcast tasks
    broadcast_cancel: Optional[asyncio.Event] = None
    sticker_gap: dict = field(default_factory=dict)      # chat_id -> replies since last sticker
    telegram_running: bool = False
    telegram_last_error: Optional[str] = None

    async def health(self, detailed: bool = False) -> dict:
        """Health snapshot. `detailed=False` is safe for unauthenticated/public use."""
        ollama = await self.router.ollama.health()
        mongo_ok = await self.mongo.ping()
        ok = bool(ollama["ok"] and mongo_ok)
        basic = {
            "status": "ok" if ok else "degraded",
            "ollama": ollama["ok"],
            "mongo": mongo_ok,
            "telegram_polling": self.telegram_running,
            "uptime_seconds": int(time.time() - self.started_at),
        }
        if not detailed:
            return basic
        basic.update(
            {
                "model": self.settings.ollama_model,
                "model_installed": ollama["model_installed"],
                "queue": self.queue.stats(),
                "latency": self.router.latency_summary(),
                "hf_replica": self.router.replica.status(),
                "openrouter": self.router.openrouter.status(),
            }
        )
        return basic


async def build_context(settings: Settings, mongo: Optional[Mongo] = None) -> AppContext:
    """Connect to MongoDB (with retries) and assemble every service."""
    mongo = mongo or Mongo(settings)
    await mongo.connect()
    router = AIRouter(settings)
    queue = InferenceQueue(settings.max_concurrent_inference, settings.max_queue_size,
                           settings.max_queued_per_user, settings.queue_wait_timeout_seconds)
    return assemble_with_db(settings, mongo, router, queue, mongo.db)


def assemble_with_db(settings: Settings, mongo: Mongo, router: AIRouter, queue: InferenceQueue, db) -> AppContext:
    users = UserRepo(db, settings.default_language)
    conversations = ConversationRepo(db, settings.max_stored_messages_per_user)
    memories = MemoryRepo(db, settings.max_memories_per_user)
    web_auth = WebAuthRepo(db, settings.api_link_code_ttl_seconds, settings.api_session_ttl_days)
    memory_service = MemoryService(settings, router, queue, users, conversations, memories)
    engine = ChatEngine(settings, router, queue, users, conversations, memories, memory_service, web_auth)
    return AppContext(
        settings=settings, mongo=mongo, router=router, queue=queue, users=users,
        conversations=conversations, memories=memories, web_auth=web_auth,
        memory_service=memory_service, engine=engine,
        user_limiter=SlidingWindowLimiter(settings.user_rate_limit_messages, settings.user_rate_limit_window_seconds),
        global_limiter=SlidingWindowLimiter(settings.global_rate_limit_messages, settings.global_rate_limit_window_seconds),
        dedupe=DedupeCache(settings.dedupe_cache_size),
        runtime=RuntimeSettings(db), chats=ChatsRepo(db), stickers=StickersRepo(db),
        chat_limiter=SlidingWindowLimiter(settings.group_rate_limit_messages, 60),
    )
