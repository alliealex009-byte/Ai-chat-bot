"""Hugging Face Space backend tests (need fastapi + httpx; skipped otherwise). VPS calls are faked."""
import importlib.util
import sys
from pathlib import Path

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")
from fastapi.testclient import TestClient  # noqa: E402


@pytest.fixture
def hf(monkeypatch):
    monkeypatch.setenv("RIA_API_URL", "https://ria-api.example.com")
    monkeypatch.setenv("RIA_API_TOKEN", "s" * 40)
    monkeypatch.setenv("ADMIN_PASSWORD", "correct horse battery")
    monkeypatch.setenv("SESSION_SECRET", "x" * 32)
    monkeypatch.setenv("LOCAL_DEV", "1")
    path = Path(__file__).resolve().parent.parent / "hf_space" / "app.py"
    spec = importlib.util.spec_from_file_location("hf_space_app", path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["hf_space_app"] = mod
    spec.loader.exec_module(mod)
    mod.calls = []

    async def fake_vps(method, path, *, session=None, json=None, route=""):
        mod.calls.append((method, path, session, json))
        if path == "/api/v1/auth/redeem":
            return (200, {"session_token": "tok123"}) if json["code"] == "GOODCODE" else (400, {"detail": "bad"})
        if path == "/api/v1/chat":
            return 200, {"reply": "Hieee!", "status": "ok", "provider": "ollama", "model": "gemma3:4b", "latency_ms": 9,
                         "internal_debug": "must not pass through"}
        if path == "/api/v1/status":
            return 200, {"status": "ok", "ollama": True}
        return 200, {"status": "ok", "messages": []}

    mod.vps = fake_vps
    return mod


def test_pages_and_healthz_no_secrets(hf):
    c = TestClient(hf.app)
    assert c.get("/healthz").json() == {"status": "ok"}
    for page in ("/", "/admin"):
        r = c.get(page)
        assert r.status_code == 200 and "s" * 40 not in r.text and "correct horse" not in r.text
        assert "Bearer" not in r.text and "RIA_API_TOKEN" not in r.text
    assert "default-src 'self'" in c.get("/").headers["content-security-policy"]


def test_login_sets_httponly_cookie_and_chat_forwards_session(hf):
    c = TestClient(hf.app)
    assert c.post("/api/login", json={"code": "WRONG"}).status_code == 400
    r = c.post("/api/login", json={"code": "GOODCODE"})
    assert r.status_code == 200 and "httponly" in r.headers["set-cookie"].lower()
    assert "tok123" not in r.text                              # never in the body / JS-visible
    r = c.post("/api/chat", json={"message": "hi"})
    assert r.json()["reply"] == "Hieee!" and "internal_debug" not in r.text
    assert hf.calls[-1][2] == "tok123"


def test_chat_without_login_is_rejected(hf):
    assert TestClient(hf.app).post("/api/chat", json={"message": "hi"}).status_code == 401


def test_admin_requires_password_and_hides_vps_token(hf):
    c = TestClient(hf.app)
    assert c.get("/admin/api/overview").status_code == 401
    assert c.post("/admin/api/login", json={"password": "nope"}).status_code == 401
    assert c.post("/admin/api/login", json={"password": "correct horse battery"}).status_code == 200
    r = c.get("/admin/api/overview")
    assert r.status_code == 200 and "status" in r.json() and "s" * 40 not in r.text


def test_forged_admin_cookie_rejected(hf):
    c = TestClient(hf.app)
    c.cookies.set("ria_admin", "9999999999.deadbeef", path="/admin")
    assert c.get("/admin/api/overview").status_code == 401


def test_admin_cookie_signature_and_expiry(hf):
    import time
    assert hf._admin_ok(hf._sign(int(time.time()) + 60))
    assert not hf._admin_ok(hf._sign(int(time.time()) - 5))      # expired
    assert not hf._admin_ok("9999999999.deadbeef")               # forged
    assert not hf._admin_ok(None) and not hf._admin_ok("garbage")


def test_cross_origin_post_blocked(hf):
    c = TestClient(hf.app)
    r = c.post("/api/login", json={"code": "GOODCODE"}, headers={"Origin": "https://evil.example"})
    assert r.status_code == 403


def test_replica_disabled_by_default(hf):
    c = TestClient(hf.app)
    assert c.get("/replica/health").status_code == 404
    assert c.post("/replica/chat", json={"messages": []}).status_code == 404
