"""Provider routing: local Ollama (always primary) -> optional HF replica -> optional OpenRouter.

Providers are only tried in this fixed order and only after the previous one fails.
Every fallback is logged and counted; the provider used is returned in ChatResult.
"""
from __future__ import annotations

import logging
from collections import Counter
from typing import Optional

from app.ai.errors import AIError, AIModelMissing, ChatResult
from app.ai.fallback import OpenRouterClient
from app.ai.ollama import OllamaClient
from app.ai.replica import HFReplicaClient
from app.config import Settings

log = logging.getLogger(__name__)


class AIRouter:
    def __init__(self, settings: Settings, ollama: Optional[OllamaClient] = None,
                 replica: Optional[HFReplicaClient] = None, openrouter: Optional[OpenRouterClient] = None):
        self.s = settings
        self.ollama = ollama or OllamaClient(settings)
        self.replica = replica or HFReplicaClient(settings)
        self.openrouter = openrouter or OpenRouterClient(settings)
        self.counts: Counter = Counter()
        self.errors: Counter = Counter()
        self.latencies: list[int] = []  # last N local latencies (ms)

    def start(self) -> None:
        self.replica.start()

    async def close(self) -> None:
        await self.ollama.close()
        await self.replica.close()
        await self.openrouter.close()

    async def chat(self, messages: list[dict], max_tokens: Optional[int] = None,
                   temperature: Optional[float] = None) -> ChatResult:
        chain = [self.ollama]
        if self.replica.enabled:
            chain.append(self.replica)
        if self.openrouter.enabled:
            chain.append(self.openrouter)
        last: Exception = AIError("no provider")
        for i, provider in enumerate(chain):
            try:
                result = await provider.chat(messages, max_tokens=max_tokens, temperature=temperature)
            except AIError as e:
                last = e
                self.errors[provider.provider] += 1
                if isinstance(e, AIModelMissing):
                    log.error("%s", e)
                nxt = chain[i + 1].provider if i + 1 < len(chain) else None
                log.warning("Provider %s failed (%s)%s", provider.provider, type(e).__name__,
                            f"; falling back to {nxt}" if nxt else "; no more providers")
                continue
            self.counts[result.provider] += 1
            self._record(result)
            if i > 0:
                log.warning("Reply served by FALLBACK provider %s", result.provider)
            return result
        raise last

    def _record(self, r: ChatResult) -> None:
        self.latencies.append(r.latency_ms)
        del self.latencies[:-200]
        log.info("inference provider=%s model=%s latency_ms=%d tokens=%d", r.provider, r.model,
                 r.latency_ms, r.completion_tokens)

    def latency_summary(self) -> dict:
        if not self.latencies:
            return {"count": 0, "avg_ms": None, "p95_ms": None}
        xs = sorted(self.latencies)
        return {"count": len(xs), "avg_ms": int(sum(xs) / len(xs)), "p95_ms": xs[int(0.95 * (len(xs) - 1))]}

    async def status(self) -> dict:
        local = await self.ollama.health()
        return {
            "primary": {"provider": "ollama", "model": self.s.ollama_model, **local},
            "hf_replica": self.replica.status(),
            "openrouter": self.openrouter.status(),
            "ai_mode": self.s.ai_mode,
            "served": dict(self.counts),
            "errors": dict(self.errors),
            "latency": self.latency_summary(),
        }
