"""RIA Hugging Face Space: web chat + admin dashboard + (optional) inference replica.

This Space is a thin, STATELESS front end. It stores no user data: history and memories live in the
VPS MongoDB and are reached only through the authenticated VPS HTTPS API.
All secrets come from Space Secrets (environment variables); none are ever sent to the browser.
"""
from __future__ import annotations

import hashlib
import hmac
import os
import secrets
import time
from collections import deque
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

import httpx
from fastapi import Cookie, FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field

# ---- configuration (Space Secrets / Variables) ---------------------------------------------
RIA_API_URL = os.environ.get("RIA_API_URL", "").rstrip("/")          # https://ria-api.example.com
RIA_API_TOKEN = os.environ.get("RIA_API_TOKEN", "")                   # same as VPS API_TOKEN
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "")
SESSION_SECRET = os.environ.get("SESSION_SECRET", "") or secrets.token_hex(32)  # random per boot if unset
ENABLE_REPLICA = os.environ.get("ENABLE_REPLICA", "false").lower() == "true"
REPLICA_TOKEN = os.environ.get("REPLICA_TOKEN", "")
OLLAMA_LOCAL = os.environ.get("OLLAMA_LOCAL_URL", "http://127.0.0.1:11434")
REPLICA_MODEL = os.environ.get("OLLAMA_MODEL", "gemma3:4b")
LOCAL_DEV = os.environ.get("LOCAL_DEV", "0") == "1"                   # allows http cookies for local tests

STATIC = Path(__file__).parent / "static"
app = FastAPI(title="RIA Space", docs_url=None, redoc_url=None, openapi_url=None)

if not RIA_API_URL.startswith("https://") and not LOCAL_DEV:
    print("WARNING: RIA_API_URL must be an https:// URL (set the Space secret).")

_client: Optional[httpx.AsyncClient] = None
metrics: deque = deque(maxlen=500)  # (ts, route, ok, latency_ms) — in-memory only, resets when the Space sleeps


def client() -> httpx.AsyncClient:
    global _client
    if _client is None:
        _client = httpx.AsyncClient(
            base_url=RIA_API_URL, timeout=httpx.Timeout(150.0, connect=8.0),
            headers={"Authorization": f"Bearer {RIA_API_TOKEN}"},
        )
    return _client


# ---- tiny in-memory rate limiter ----------------------------------------------------------
_hits: dict[str, deque] = {}


def rate_ok(key: str, limit: int, window: int) -> bool:
    now = time.monotonic()
    q = _hits.setdefault(key, deque())
    while q and now - q[0] > window:
        q.popleft()
    if len(q) >= limit:
        return False
    q.append(now)
    if len(_hits) > 5000:
        for k in [k for k, v in _hits.items() if not v][:1000]:
            _hits.pop(k, None)
    return True


def ip_of(request: Request) -> str:
    xff = request.headers.get("x-forwarded-for", "")
    return (xff.split(",")[0].strip() if xff else (request.client.host if request.client else "?"))


# ---- middleware: CSRF-style origin check + headers -----------------------------------------
@app.middleware("http")
async def guard(request: Request, call_next):
    if request.method in ("POST", "PUT", "DELETE", "PATCH"):
        origin = request.headers.get("origin")
        if origin and urlparse(origin).netloc != request.headers.get("host", ""):
            return JSONResponse({"detail": "bad origin"}, status_code=403)
    resp = await call_next(request)
    resp.headers.setdefault("X-Content-Type-Options", "nosniff")
    resp.headers.setdefault("Referrer-Policy", "no-referrer")
    resp.headers.setdefault("Cache-Control", "no-store")
    resp.headers.setdefault(
        "Content-Security-Policy",
        "default-src 'self'; style-src 'self' 'unsafe-inline'; script-src 'self' 'unsafe-inline'; "
        "connect-src 'self'; img-src 'self' data:; frame-ancestors 'self' https://huggingface.co",
    )
    return resp


# ---- VPS proxy helper ---------------------------------------------------------------------
async def vps(method: str, path: str, *, session: Optional[str] = None, json: Optional[dict] = None,
              route: str = "") -> tuple[int, dict]:
    headers = {"X-Session-Token": session} if session else {}
    t0 = time.monotonic()
    try:
        r = await client().request(method, path, json=json, headers=headers)
        ok = r.status_code < 500
        try:
            data = r.json()
        except ValueError:
            data = {}
        status = r.status_code
    except (httpx.HTTPError, RuntimeError):
        ok, status, data = False, 502, {"detail": "ria server unreachable"}
    metrics.append((time.time(), route or path, ok, int((time.monotonic() - t0) * 1000)))
    return status, data


def _passthrough(status: int, data: dict) -> JSONResponse:
    if status == 502 or status >= 500 and "reply" not in data:
        return JSONResponse({"detail": "RIA abhi available nahi hai, thodi der baad try karo."}, status_code=503)
    # Only forward fields we know are safe/expected.
    safe = {k: v for k, v in data.items() if k in {
        "reply", "status", "provider", "model", "latency_ms", "messages", "memories", "ok", "deleted", "detail"}}
    return JSONResponse(safe, status_code=status)


# ---- pages ---------------------------------------------------------------------------------
@app.get("/")
async def index():
    return FileResponse(STATIC / "index.html")


@app.get("/admin")
async def admin_page():
    return FileResponse(STATIC / "admin.html")


@app.get("/healthz")
async def healthz():
    """Space's own liveness (no details)."""
    return {"status": "ok"}


# ---- user web chat -------------------------------------------------------------------------
class LoginIn(BaseModel):
    code: str = Field(min_length=4, max_length=32)


class ChatIn(BaseModel):
    message: str = Field(min_length=1, max_length=4000)


def _set_session(resp: Response, token: str) -> None:
    resp.set_cookie("ria_session", token, max_age=30 * 86400, httponly=True, secure=not LOCAL_DEV, samesite="lax", path="/")


@app.post("/api/login")
async def login(body: LoginIn, request: Request):
    if not rate_ok(f"login:{ip_of(request)}", 6, 60):
        raise HTTPException(429, "too many attempts")
    status, data = await vps("POST", "/api/v1/auth/redeem", json={"code": body.code}, route="login")
    if status != 200 or "session_token" not in data:
        return JSONResponse({"detail": "Code galat ya expire ho gaya. Telegram par /link se naya lo."},
                            status_code=400 if status == 400 else 503)
    resp = JSONResponse({"ok": True})
    _set_session(resp, data["session_token"])
    return resp


@app.post("/api/logout")
async def logout(ria_session: Optional[str] = Cookie(default=None)):
    if ria_session:
        await vps("POST", "/api/v1/auth/logout", session=ria_session, route="logout")
    resp = JSONResponse({"ok": True})
    resp.delete_cookie("ria_session", path="/")
    return resp


def _need(session: Optional[str]) -> str:
    if not session:
        raise HTTPException(401, "login required")
    return session


@app.post("/api/chat")
async def chat(body: ChatIn, request: Request, ria_session: Optional[str] = Cookie(default=None)):
    s = _need(ria_session)
    if not rate_ok(f"chat:{s[:12]}", 20, 60):
        raise HTTPException(429, "slow down")
    status, data = await vps("POST", "/api/v1/chat", session=s, json={"message": body.message}, route="chat")
    return _passthrough(status, data)


@app.get("/api/history")
async def history(ria_session: Optional[str] = Cookie(default=None)):
    return _passthrough(*await vps("GET", "/api/v1/history", session=_need(ria_session), route="history"))


@app.get("/api/memory")
async def memory(ria_session: Optional[str] = Cookie(default=None)):
    return _passthrough(*await vps("GET", "/api/v1/memory", session=_need(ria_session), route="memory"))


@app.delete("/api/memory/{memory_id}")
async def memory_del(memory_id: str, ria_session: Optional[str] = Cookie(default=None)):
    if not memory_id.isalnum() or len(memory_id) > 64:
        raise HTTPException(400, "bad id")
    return _passthrough(*await vps("DELETE", f"/api/v1/memory/{memory_id}", session=_need(ria_session), route="memory"))


@app.post("/api/reset")
async def reset(ria_session: Optional[str] = Cookie(default=None)):
    return _passthrough(*await vps("POST", "/api/v1/reset", session=_need(ria_session), route="reset"))


# ---- admin ---------------------------------------------------------------------------------
def _sign(exp: int) -> str:
    sig = hmac.new(SESSION_SECRET.encode(), str(exp).encode(), hashlib.sha256).hexdigest()
    return f"{exp}.{sig}"


def _admin_ok(token: Optional[str]) -> bool:
    try:
        exp_s, sig = (token or "").split(".", 1)
        exp = int(exp_s)
    except ValueError:
        return False
    return exp > time.time() and hmac.compare_digest(_sign(exp), f"{exp}.{sig}")


def _require_admin(token: Optional[str]) -> None:
    if not ADMIN_PASSWORD or not _admin_ok(token):
        raise HTTPException(401, "admin login required")


class AdminLogin(BaseModel):
    password: str = Field(min_length=1, max_length=200)


class PlayIn(BaseModel):
    message: str = Field(min_length=1, max_length=2000)
    system: Optional[str] = Field(default=None, max_length=4000)
    temperature: Optional[float] = Field(default=None, ge=0.0, le=1.5)
    max_tokens: Optional[int] = Field(default=None, ge=16, le=500)


@app.post("/admin/api/login")
async def admin_login(body: AdminLogin, request: Request):
    if not ADMIN_PASSWORD:
        raise HTTPException(503, "ADMIN_PASSWORD not configured")
    if not rate_ok(f"alogin:{ip_of(request)}", 5, 300):
        raise HTTPException(429, "too many attempts")
    if not hmac.compare_digest(body.password.encode(), ADMIN_PASSWORD.encode()):
        raise HTTPException(401, "wrong password")
    resp = JSONResponse({"ok": True})
    exp = int(time.time()) + 8 * 3600
    resp.set_cookie("ria_admin", _sign(exp), max_age=8 * 3600, httponly=True, secure=not LOCAL_DEV,
                    samesite="strict", path="/admin")
    return resp


@app.post("/admin/api/logout")
async def admin_logout():
    resp = JSONResponse({"ok": True})
    resp.delete_cookie("ria_admin", path="/admin")
    return resp


@app.get("/admin/api/overview")
async def admin_overview(ria_admin: Optional[str] = Cookie(default=None)):
    _require_admin(ria_admin)
    out: dict = {}
    for key, path in (("health", "/api/v1/health"), ("status", "/api/v1/status"),
                      ("model", "/api/v1/model"), ("stats", "/api/v1/stats")):
        st, data = await vps("GET", path, route=f"admin:{key}")
        out[key] = data if st == 200 else {"error": "unavailable"}
    now = time.time()
    recent = [m for m in metrics if now - m[0] < 3600]
    lat = sorted(m[3] for m in recent if m[2])
    out["space"] = {
        "requests_last_hour": len(recent),
        "errors_last_hour": sum(1 for m in recent if not m[2]),
        "avg_latency_ms": int(sum(lat) / len(lat)) if lat else None,
        "p95_latency_ms": lat[int(0.95 * (len(lat) - 1))] if lat else None,
        "series": [{"t": int(m[0]), "ms": m[3], "ok": m[2]} for m in list(metrics)[-60:]],
        "replica_enabled": ENABLE_REPLICA,
    }
    return out


@app.post("/admin/api/playground")
async def admin_playground(body: PlayIn, ria_admin: Optional[str] = Cookie(default=None)):
    _require_admin(ria_admin)
    st, data = await vps("POST", "/api/v1/playground", json=body.model_dump(exclude_none=True), route="playground")
    if st == 200:
        return {k: data.get(k) for k in ("reply", "provider", "model", "latency_ms", "completion_tokens")}
    return JSONResponse({"detail": "playground unavailable" if st >= 500 else "request rejected"}, status_code=503 if st >= 500 else st)


# ---- optional inference replica (disabled by default) -------------------------------------
def _replica_auth(authorization: Optional[str]) -> None:
    if not ENABLE_REPLICA or not REPLICA_TOKEN:
        raise HTTPException(404, "not found")
    tok = authorization[7:].strip() if authorization and authorization.lower().startswith("bearer ") else ""
    if not hmac.compare_digest(tok.encode(), REPLICA_TOKEN.encode()):
        raise HTTPException(401, "unauthorized")


class ReplicaChat(BaseModel):
    messages: list[dict] = Field(max_length=40)
    max_tokens: int = Field(100, ge=1, le=600)
    temperature: float = Field(0.75, ge=0, le=1.5)


@app.get("/replica/health")
async def replica_health(request: Request):
    _replica_auth(request.headers.get("authorization"))
    try:
        async with httpx.AsyncClient(timeout=5) as c:
            r = await c.get(f"{OLLAMA_LOCAL}/api/tags")
        names = {m.get("name") for m in r.json().get("models", [])}
        ok = REPLICA_MODEL in names
    except Exception:  # noqa: BLE001
        ok = False
    return {"ok": ok, "model": REPLICA_MODEL}


@app.post("/replica/chat")
async def replica_chat(body: ReplicaChat, request: Request):
    _replica_auth(request.headers.get("authorization"))
    payload = {"model": REPLICA_MODEL, "messages": body.messages, "stream": False,
               "options": {"num_predict": body.max_tokens, "temperature": body.temperature, "num_ctx": 4096}}
    try:
        async with httpx.AsyncClient(timeout=120) as c:
            r = await c.post(f"{OLLAMA_LOCAL}/api/chat", json=payload)
        r.raise_for_status()
        d = r.json()
    except Exception:  # noqa: BLE001
        raise HTTPException(503, "replica unavailable")
    return {"text": (d.get("message") or {}).get("content", ""), "model": REPLICA_MODEL,
            "prompt_tokens": d.get("prompt_eval_count", 0), "completion_tokens": d.get("eval_count", 0)}
