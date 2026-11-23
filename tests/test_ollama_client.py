"""Ollama client tests against a real local fake Ollama HTTP server (needs aiohttp; skipped otherwise)."""
import asyncio

import pytest

aiohttp = pytest.importorskip("aiohttp")
web = pytest.importorskip("aiohttp.web")

from app.ai.errors import AIModelMissing, AITimeout, AIUnavailable  # noqa: E402
from app.ai.ollama import OllamaClient  # noqa: E402
from tests.fakes import make_settings  # noqa: E402


class FakeOllama:
    def __init__(self):
        self.hits = 0
        self.handler = None
        self.last_payload = None

    async def start(self):
        app = web.Application()
        app.router.add_post("/api/chat", self.chat)
        app.router.add_get("/api/tags", self.tags)
        self.runner = web.AppRunner(app)
        await self.runner.setup()
        self.site = web.TCPSite(self.runner, "127.0.0.1", 0)
        await self.site.start()
        self.port = self.site._server.sockets[0].getsockname()[1]
        return f"http://127.0.0.1:{self.port}"

    async def stop(self):
        await self.runner.cleanup()

    async def chat(self, request):
        self.hits += 1
        self.last_payload = await request.json()
        return await self.handler(request)

    async def tags(self, request):
        return web.json_response({"models": [{"name": "gemma3:4b"}, {"name": "qwen3:4b"}]})


async def _client(fake, **over):
    url = await fake.start()
    return OllamaClient(make_settings(**{"ollama_base_url": url, "ollama_retries": 1, **over}))


async def test_success_uses_chat_api_and_configured_options():
    fake = FakeOllama()

    async def ok(req):
        return web.json_response({"message": {"role": "assistant", "content": "<think>hmm</think>Hieee! 💗"},
                                  "prompt_eval_count": 10, "eval_count": 5})

    fake.handler = ok
    c = await _client(fake)
    r = await c.chat([{"role": "user", "content": "hi"}])
    assert r.text == "Hieee! 💗" and r.provider == "ollama" and r.completion_tokens == 5
    p = fake.last_payload
    assert p["model"] == "gemma3:4b" and p["stream"] is False
    assert p["options"]["num_predict"] == 100 and p["options"]["num_ctx"] == 4096 and p["options"]["top_p"] == 0.9
    await c.close(); await fake.stop()


async def test_missing_model_not_retried_and_not_switched():
    fake = FakeOllama()

    async def nf(req):
        return web.json_response({"error": "model not found"}, status=404)

    fake.handler = nf
    c = await _client(fake)
    with pytest.raises(AIModelMissing):
        await c.chat([{"role": "user", "content": "hi"}])
    assert fake.hits == 1 and fake.last_payload["model"] == "gemma3:4b"
    await c.close(); await fake.stop()


async def test_server_error_retries_then_succeeds():
    fake = FakeOllama()

    async def flaky(req):
        if fake.hits == 1:
            return web.Response(status=503)
        return web.json_response({"message": {"content": "ok ji"}})

    fake.handler = flaky
    c = await _client(fake)
    assert (await c.chat([{"role": "user", "content": "hi"}])).text == "ok ji"
    assert fake.hits == 2
    await c.close(); await fake.stop()


async def test_timeout_raises_aitimeout():
    fake = FakeOllama()

    async def slow(req):
        await asyncio.sleep(2)
        return web.json_response({"message": {"content": "late"}})

    fake.handler = slow
    c = await _client(fake, ollama_timeout_seconds=1.2, ollama_retries=0)
    with pytest.raises(AITimeout):
        await c.chat([{"role": "user", "content": "hi"}])
    await c.close(); await fake.stop()


async def test_connection_refused_is_unavailable_and_health_reports_down():
    c = OllamaClient(make_settings(ollama_base_url="http://127.0.0.1:1", ollama_retries=0))
    with pytest.raises(AIUnavailable):
        await c.chat([{"role": "user", "content": "hi"}])
    h = await c.health()
    assert h["ok"] is False
    await c.close()


async def test_empty_reply_is_error_and_health_checks_model_installed():
    fake = FakeOllama()

    async def empty(req):
        return web.json_response({"message": {"content": "  "}})

    fake.handler = empty
    c = await _client(fake, ollama_retries=0)
    from app.ai.errors import AIError
    with pytest.raises(AIError):
        await c.chat([{"role": "user", "content": "hi"}])
    h = await c.health()
    assert h["ok"] and h["model_installed"]
    await c.close(); await fake.stop()
