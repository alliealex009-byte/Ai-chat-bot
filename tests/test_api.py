"""VPS API tests (need fastapi + httpx; skipped otherwise)."""
import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")
from fastapi.testclient import TestClient  # noqa: E402

from app.api.server import create_api  # noqa: E402

TOKEN = "a" * 40
SVC = {"Authorization": f"Bearer {TOKEN}"}


class _Mongo:
    async def ping(self):
        return True


def _client(stack):
    import asyncio

    stack.ctx.mongo = _Mongo()
    stack.queue.start  # queue workers need a running loop; TestClient has its own, so start lazily below
    app = create_api(stack.ctx)

    @app.on_event("startup")
    async def _start():
        stack.queue.start()

    return TestClient(app, raise_server_exceptions=False)  # let our 500 handler answer


def _session(c, stack, uid):
    import asyncio

    async def go():
        code = await stack.ctx.web_auth.create_link_code(uid)
        return code

    return asyncio.new_event_loop().run_until_complete(go())


def _login(c, stack, uid):
    code = _session(c, stack, uid)
    r = c.post("/api/v1/auth/redeem", json={"code": code}, headers=SVC)
    assert r.status_code == 200
    return {**SVC, "X-Session-Token": r.json()["session_token"]}


def test_health_is_public_and_minimal(stack):
    with _client(stack) as c:
        r = c.get("/api/v1/health")
        assert r.status_code == 200 and set(r.json()) == {"status"}


def test_private_endpoints_require_service_token(stack):
    with _client(stack) as c:
        for path in ("/api/v1/status", "/api/v1/model", "/api/v1/stats"):
            assert c.get(path).status_code == 401
            assert c.get(path, headers={"Authorization": "Bearer wrong"}).status_code == 401
            assert c.get(path, headers=SVC).status_code == 200
        assert c.post("/api/v1/chat", json={"message": "hi"}).status_code == 401


def test_chat_needs_valid_user_session_too(stack):
    with _client(stack) as c:
        assert c.post("/api/v1/chat", json={"message": "hi"}, headers=SVC).status_code == 401
        assert c.post("/api/v1/chat", json={"message": "hi"}, headers={**SVC, "X-Session-Token": "nope"}).status_code == 401


def test_chat_roundtrip_and_user_isolation(stack):
    with _client(stack) as c:
        a = _login(c, stack, 1)
        b = _login(c, stack, 2)
        stack.local.script = ["Hieee!", "Kya haal?"]
        ra = c.post("/api/v1/chat", json={"message": "user A secret talk"}, headers=a)
        assert ra.status_code == 200 and ra.json()["reply"] == "Hieee!" and ra.json()["provider"] == "ollama"
        c.post("/api/v1/chat", json={"message": "hello from B"}, headers=b)
        ha = c.get("/api/v1/history", headers=a).json()["messages"]
        hb = c.get("/api/v1/history", headers=b).json()["messages"]
        assert any("A secret" in m["content"] for m in ha)
        assert not any("A secret" in m["content"] for m in hb)
        import asyncio
        asyncio.new_event_loop().run_until_complete(stack.ctx.memories.upsert(1, "Likes tea"))
        mem_a = c.get("/api/v1/memory", headers=a).json()["memories"]
        assert [m["text"] for m in mem_a] == ["Likes tea"]
        assert c.get("/api/v1/memory", headers=b).json()["memories"] == []
        # B cannot delete A's memory by id
        assert c.delete(f"/api/v1/memory/{mem_a[0]['id']}", headers=b).status_code == 404
        assert c.delete(f"/api/v1/memory/{mem_a[0]['id']}", headers=a).status_code == 200


def test_delete_me_wipes_user_and_session(stack):
    with _client(stack) as c:
        a = _login(c, stack, 1)
        c.post("/api/v1/chat", json={"message": "hi"}, headers=a)
        assert c.delete("/api/v1/me", headers=a).json()["ok"]
        assert c.get("/api/v1/history", headers=a).status_code == 401


def test_link_code_is_single_use(stack):
    import asyncio
    with _client(stack) as c:
        code = asyncio.new_event_loop().run_until_complete(stack.ctx.web_auth.create_link_code(9))
        assert c.post("/api/v1/auth/redeem", json={"code": code}, headers=SVC).status_code == 200
        assert c.post("/api/v1/auth/redeem", json={"code": code}, headers=SVC).status_code == 400
        assert c.post("/api/v1/auth/redeem", json={"code": code}).status_code == 401


def test_user_rate_limit_and_validation(stack):
    stack.settings.__dict__["api_rate_limit_per_minute"] = 3
    with _client(stack) as c:
        a = _login(c, stack, 1)
        codes = [c.get("/api/v1/history", headers=a).status_code for _ in range(5)]
        assert codes[:3] == [200, 200, 200] and 429 in codes[3:]
        b = _login(c, stack, 2)
        assert c.post("/api/v1/chat", json={"message": ""}, headers=b).status_code == 422


def test_internal_errors_are_not_leaked(stack):
    with _client(stack) as c:
        async def boom():
            raise RuntimeError("secret internals mongodb://u:pw@host")
        stack.ctx.users.count = boom
        r = c.get("/api/v1/stats", headers=SVC)
        assert r.status_code == 500 and "secret" not in r.text and "mongodb" not in r.text


def test_failure_status_codes_for_ai_down(stack):
    from app.ai.errors import AIUnavailable
    with _client(stack) as c:
        a = _login(c, stack, 1)
        stack.local.script = [AIUnavailable("x")]
        r = c.post("/api/v1/chat", json={"message": "hi"}, headers=a)
        assert r.status_code == 503 and "x" not in r.json()["reply"]


def test_playground_is_stateless(stack):
    with _client(stack) as c:
        r = c.post("/api/v1/playground", json={"message": "Hi", "temperature": 0.5}, headers=SVC)
        assert r.status_code == 200 and r.json()["model"] == "gemma3:4b"
        assert c.post("/api/v1/playground", json={"message": "Hi"}).status_code == 401
        assert len(stack.db.messages.docs) == 0
