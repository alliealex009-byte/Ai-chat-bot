"""Async Ollama /api/chat client (local, CPU inference)."""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Optional

import aiohttp

from app.ai.errors import AIError, AIModelMissing, AITimeout, AIUnavailable, ChatResult
from app.ai.prompts import clean_model_output
from app.config import Settings

log = logging.getLogger(__name__)


class OllamaClient:
    provider = "ollama"

    def __init__(self, settings: Settings):
        self.s = settings
        self.model = settings.ollama_model
        self._session: Optional[aiohttp.ClientSession] = None
        self.last_ok: Optional[float] = None
        self.last_error: Optional[str] = None

    # -- session -----------------------------------------------------------
    def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            timeout = aiohttp.ClientTimeout(
                total=self.s.ollama_timeout_seconds, connect=self.s.ollama_connect_timeout_seconds
            )
            connector = aiohttp.TCPConnector(limit=self.s.max_concurrent_inference + 4)
            self._session = aiohttp.ClientSession(timeout=timeout, connector=connector)
        return self._session

    async def close(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()

    # -- API ---------------------------------------------------------------
    def _options(self, max_tokens: int, temperature: Optional[float]) -> dict:
        return {
            "temperature": self.s.ai_temperature if temperature is None else temperature,
            "top_p": self.s.ai_top_p,
            "num_predict": max_tokens,
            "num_ctx": self.s.ai_context_length,
            "num_thread": self.s.ai_num_threads,
            "repeat_penalty": self.s.ai_repeat_penalty,
        }

    async def chat(
        self,
        messages: list[dict],
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
    ) -> ChatResult:
        payload = {
            "model": self.model,
            "messages": messages,
            "stream": False,
            "keep_alive": self.s.ollama_keep_alive,
            "options": self._options(max_tokens or self.s.ai_max_tokens, temperature),
        }
        url = f"{self.s.ollama_base_url}/api/chat"
        attempts = self.s.ollama_retries + 1
        last_exc: Exception = AIUnavailable("no attempt made")
        for attempt in range(attempts):
            started = time.monotonic()
            try:
                async with self._get_session().post(url, json=payload) as resp:
                    if resp.status == 404:
                        raise AIModelMissing(f"Model '{self.model}' not found in Ollama (run: ollama pull {self.model})")
                    if resp.status >= 500:
                        raise AIUnavailable(f"Ollama HTTP {resp.status}")
                    if resp.status != 200:
                        body = (await resp.text())[:200]
                        raise AIError(f"Ollama HTTP {resp.status}: {body}")
                    data = await resp.json(content_type=None)
                text = clean_model_output((data.get("message") or {}).get("content", ""))
                if not text:
                    raise AIError("Ollama returned an empty reply")
                self.last_ok, self.last_error = time.time(), None
                return ChatResult(
                    text=text,
                    provider=self.provider,
                    model=self.model,
                    latency_ms=int((time.monotonic() - started) * 1000),
                    prompt_tokens=int(data.get("prompt_eval_count") or 0),
                    completion_tokens=int(data.get("eval_count") or 0),
                )
            except AIModelMissing as e:
                self.last_error = str(e)
                raise  # retrying will not help, and we never switch models silently
            except asyncio.TimeoutError:
                last_exc = AITimeout(f"Ollama timed out after {self.s.ollama_timeout_seconds}s")
            except (aiohttp.ClientError, AIUnavailable) as e:
                last_exc = e if isinstance(e, AIError) else AIUnavailable(f"Ollama unreachable: {type(e).__name__}")
            except AIError as e:
                self.last_error = str(e)
                raise
            self.last_error = str(last_exc)
            if attempt < attempts - 1:
                delay = min(2 ** attempt, 8)
                log.warning("Ollama attempt %d/%d failed (%s); retrying in %ss", attempt + 1, attempts, last_exc, delay)
                await asyncio.sleep(delay)
        raise last_exc

    async def health(self) -> dict:
        """Cheap check: server reachable and configured model installed."""
        info = {"ok": False, "model": self.model, "model_installed": False, "error": None}
        try:
            timeout = aiohttp.ClientTimeout(total=4)
            async with self._get_session().get(f"{self.s.ollama_base_url}/api/tags", timeout=timeout) as r:
                if r.status != 200:
                    info["error"] = f"HTTP {r.status}"
                    return info
                data = await r.json(content_type=None)
            names = {m.get("name", "") for m in data.get("models", [])}
            info["model_installed"] = self.model in names or f"{self.model}:latest" in names
            info["ok"] = info["model_installed"]
            if not info["model_installed"]:
                info["error"] = "model not installed"
        except Exception as e:  # noqa: BLE001 - health must never raise
            info["error"] = type(e).__name__
        return info

    async def warmup(self) -> None:
        """Load the model into RAM so the first user message isn't slow. Never raises."""
        try:
            await self.chat([{"role": "user", "content": "hi"}], max_tokens=4)
            log.info("Ollama model %s warmed up", self.model)
        except Exception as e:  # noqa: BLE001
            log.warning("Warmup failed: %s", e)
