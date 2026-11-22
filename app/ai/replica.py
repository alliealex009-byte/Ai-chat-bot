"""Optional Hugging Face Space inference replica (Ollama gemma3:4b on the Space).

Disabled by default. The VPS never depends on it: it is only tried AFTER local Ollama fails,
and only while its health check is passing.
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Optional

import aiohttp

from app.ai.errors import AIError, AITimeout, AIUnavailable, ChatResult
from app.ai.prompts import clean_model_output
from app.config import Settings

log = logging.getLogger(__name__)


class HFReplicaClient:
    provider = "hf_replica"

    def __init__(self, settings: Settings):
        self.s = settings
        self.model = settings.ollama_model  # same model, never another one
        self.healthy = False
        self.last_check: Optional[float] = None
        self.last_error: Optional[str] = None
        self._session: Optional[aiohttp.ClientSession] = None
        self._task: Optional[asyncio.Task] = None

    @property
    def enabled(self) -> bool:
        return bool(self.s.hf_replica_enabled and self.s.hf_replica_url and self.s.hf_replica_token)

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self.s.hf_replica_token}"}

    def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=self.s.hf_replica_timeout_seconds, connect=6)
            )
        return self._session

    async def check_health(self) -> bool:
        if not self.enabled:
            return False
        try:
            async with self._get_session().get(
                f"{self.s.hf_replica_url.rstrip('/')}/replica/health",
                headers=self._headers(), timeout=aiohttp.ClientTimeout(total=10),
            ) as r:
                data = await r.json(content_type=None) if r.status == 200 else {}
                self.healthy = bool(r.status == 200 and data.get("ok") and data.get("model") == self.model)
                self.last_error = None if self.healthy else f"HTTP {r.status}"
        except Exception as e:  # noqa: BLE001
            self.healthy, self.last_error = False, type(e).__name__
        self.last_check = time.time()
        return self.healthy

    async def _loop(self) -> None:
        while True:
            await self.check_health()
            await asyncio.sleep(self.s.hf_replica_health_interval_seconds)

    def start(self) -> None:
        if self.enabled and self._task is None:
            self._task = asyncio.create_task(self._loop(), name="hf-replica-health")

    async def close(self) -> None:
        if self._task:
            self._task.cancel()
            self._task = None
        if self._session and not self._session.closed:
            await self._session.close()

    def status(self) -> dict:
        return {"enabled": self.enabled, "healthy": self.healthy, "model": self.model if self.enabled else None}

    async def chat(self, messages: list[dict], max_tokens: Optional[int] = None,
                   temperature: Optional[float] = None) -> ChatResult:
        if not self.enabled:
            raise AIUnavailable("HF replica disabled")
        if not self.healthy:
            raise AIUnavailable("HF replica unhealthy")
        started = time.monotonic()
        body = {"messages": messages, "max_tokens": max_tokens or self.s.ai_max_tokens,
                "temperature": self.s.ai_temperature if temperature is None else temperature}
        try:
            async with self._get_session().post(
                f"{self.s.hf_replica_url.rstrip('/')}/replica/chat", json=body, headers=self._headers()
            ) as r:
                if r.status >= 500 or r.status == 429:
                    self.healthy = False
                    raise AIUnavailable(f"HF replica HTTP {r.status}")
                if r.status != 200:
                    raise AIError(f"HF replica HTTP {r.status}")
                data = await r.json(content_type=None)
        except asyncio.TimeoutError:
            self.healthy = False
            raise AITimeout("HF replica timed out")
        except aiohttp.ClientError as e:
            self.healthy = False
            raise AIUnavailable(f"HF replica unreachable: {type(e).__name__}")
        text = clean_model_output(data.get("text", ""))
        if not text:
            raise AIError("HF replica returned empty reply")
        return ChatResult(
            text=text, provider=self.provider, model=str(data.get("model") or self.model),
            latency_ms=int((time.monotonic() - started) * 1000),
            prompt_tokens=int(data.get("prompt_tokens") or 0),
            completion_tokens=int(data.get("completion_tokens") or 0),
        )
