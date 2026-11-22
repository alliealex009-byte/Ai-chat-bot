"""Optional OpenRouter fallback with timeout, retry and spending limits.

Disabled by default. Only used when local inference fails. Every use is logged and counted.
"""
from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timezone
from typing import Optional

import aiohttp

from app.ai.errors import AIBudgetExceeded, AIError, AITimeout, AIUnavailable, ChatResult
from app.ai.prompts import clean_model_output
from app.config import Settings

log = logging.getLogger(__name__)


class OpenRouterClient:
    provider = "openrouter"

    def __init__(self, settings: Settings):
        self.s = settings
        self.model = settings.openrouter_model or ""
        self._session: Optional[aiohttp.ClientSession] = None
        self._day = self._today()
        self.requests_today = 0
        self.tokens_today = 0
        self.last_error: Optional[str] = None

    @staticmethod
    def _today() -> str:
        return datetime.now(timezone.utc).strftime("%Y-%m-%d")

    @property
    def enabled(self) -> bool:
        return bool(self.s.api_fallback_active and self.s.openrouter_api_key and self.model)

    def _roll_day(self) -> None:
        today = self._today()
        if today != self._day:
            self._day, self.requests_today, self.tokens_today = today, 0, 0

    def check_budget(self) -> None:
        self._roll_day()
        if self.s.openrouter_daily_request_limit and self.requests_today >= self.s.openrouter_daily_request_limit:
            raise AIBudgetExceeded("OpenRouter daily request limit reached")
        if self.s.openrouter_daily_token_limit and self.tokens_today >= self.s.openrouter_daily_token_limit:
            raise AIBudgetExceeded("OpenRouter daily token limit reached")

    def status(self) -> dict:
        self._roll_day()
        return {
            "enabled": self.enabled,
            "model": self.model if self.enabled else None,
            "requests_today": self.requests_today,
            "tokens_today": self.tokens_today,
            "request_limit": self.s.openrouter_daily_request_limit,
            "token_limit": self.s.openrouter_daily_token_limit,
        }

    def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=self.s.openrouter_timeout_seconds, connect=8)
            )
        return self._session

    async def close(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()

    async def chat(self, messages: list[dict], max_tokens: Optional[int] = None,
                   temperature: Optional[float] = None) -> ChatResult:
        if not self.enabled:
            raise AIUnavailable("OpenRouter fallback is disabled")
        self.check_budget()
        payload = {
            "model": self.model,
            "messages": messages,
            "max_tokens": max_tokens or self.s.ai_max_tokens,
            "temperature": self.s.ai_temperature if temperature is None else temperature,
            "top_p": self.s.ai_top_p,
        }
        headers = {
            "Authorization": f"Bearer {self.s.openrouter_api_key}",
            "Content-Type": "application/json",
            "X-Title": "RIA",
        }
        url = f"{self.s.openrouter_base_url}/chat/completions"
        attempts = self.s.openrouter_retries + 1
        last_exc: Exception = AIUnavailable("no attempt made")
        for attempt in range(attempts):
            started = time.monotonic()
            try:
                async with self._get_session().post(url, json=payload, headers=headers) as resp:
                    if resp.status in (401, 402, 403):
                        raise AIError(f"OpenRouter auth/billing error HTTP {resp.status}")
                    if resp.status == 429 or resp.status >= 500:
                        raise AIUnavailable(f"OpenRouter HTTP {resp.status}")
                    if resp.status != 200:
                        raise AIError(f"OpenRouter HTTP {resp.status}")
                    data = await resp.json(content_type=None)
                text = clean_model_output(data["choices"][0]["message"]["content"] or "")
                if not text:
                    raise AIError("OpenRouter returned an empty reply")
                usage = data.get("usage") or {}
                total = int(usage.get("total_tokens") or 0)
                self.requests_today += 1
                self.tokens_today += total
                return ChatResult(
                    text=text, provider=self.provider, model=self.model,
                    latency_ms=int((time.monotonic() - started) * 1000),
                    prompt_tokens=int(usage.get("prompt_tokens") or 0),
                    completion_tokens=int(usage.get("completion_tokens") or 0),
                )
            except asyncio.TimeoutError:
                last_exc = AITimeout("OpenRouter timed out")
            except aiohttp.ClientConnectionError as e:
                last_exc = AIUnavailable(f"OpenRouter unreachable: {type(e).__name__}")
            except AIUnavailable as e:
                last_exc = e
            except (KeyError, IndexError, TypeError, ValueError):
                raise AIError("OpenRouter returned an unexpected response")
            self.last_error = str(last_exc)
            if attempt < attempts - 1:
                await asyncio.sleep(min(2 ** attempt, 6))
        raise last_exc
