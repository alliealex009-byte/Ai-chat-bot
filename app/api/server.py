"""Authenticated HTTP API served by the VPS (behind nginx + HTTPS).

Two layers of authentication for user data:
  1. Service token  : `Authorization: Bearer <API_TOKEN>`  (held only by the HF Space backend)
  2. User session   : `X-Session-Token: <token>`           (issued by redeeming a /link code from Telegram)
The session token pins every request to exactly one user_id, which gives per-user isolation.
Public endpoint: only GET /api/v1/health, and it returns no details.
"""
from __future__ import annotations

import hmac
import logging
import time
from typing import Optional

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app.ai.errors import AIError
from app.ai.prompts import sanitize_user_text
from app.context import AppContext
from app.personality import build_system_prompt
from app.services.limiter import SlidingWindowLimiter
from app.services.queue import QueueClosed, QueueFull, QueueTimeout, UserBusy

log = logging.getLogger(__name__)

PLAYGROUND_USER_ID = -1  # reserved queue key; never a real Telegram id


class ChatIn(BaseModel):
    message: str = Field(min_length=1, max_length=4000)


class PlaygroundIn(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    system: Optional[str] = Field(default=None, max_length=4000)
    temperature: Optional[float] = Field(default=None, ge=0.0, le=1.5)
    max_tokens: Optional[int] = Field(default=None, ge=16, le=500)


class RedeemIn(BaseModel):
    code: str = Field(min_length=4, max_length=32)


def create_api(ctx: AppContext) -> FastAPI:
    s = ctx.settings
    app = FastAPI(title="RIA API", version="1.0", docs_url=None, redoc_url=None, openapi_url=None)
    if s.api_cors_origins:
        app.add_middleware(CORSMiddleware, allow_origins=s.api_cors_origins, allow_methods=["GET", "POST", "DELETE"],
                           allow_headers=["Authorization", "X-Session-Token", "Content-Type"])

    api_user_limiter = SlidingWindowLimiter(s.api_rate_limit_per_minute, 60)
    api_global_limiter = SlidingWindowLimiter(s.api_global_rate_limit_per_minute, 60)
    redeem_limiter = SlidingWindowLimiter(10, 60)
    auth_fail_limiter = SlidingWindowLimiter(20, 60)

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        resp = await call_next(request)
        resp.headers["Cache-Control"] = "no-store"
        resp.headers["X-Content-Type-Options"] = "nosniff"
        return resp

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception):
        log.error("API error on %s: %s", request.url.path, type(exc).__name__)
        return JSONResponse({"detail": "internal error"}, status_code=500)

    # -- auth dependencies -------------------------------------------------
    def _client_ip(request: Request) -> str:
        return request.headers.get("x-real-ip") or (request.client.host if request.client else "?")

    async def service_auth(request: Request, authorization: Optional[str] = Header(default=None)) -> None:
        ip = _client_ip(request)
        if auth_fail_limiter.retry_after(ip) > 0:  # too many recent failures from this IP
            raise HTTPException(429, "too many requests")
        token = ""
        if authorization and authorization.lower().startswith("bearer "):
            token = authorization[7:].strip()
        if not token or not hmac.compare_digest(token.encode(), (s.api_token or "").encode()):
            auth_fail_limiter.allow(ip)  # record the failure only
            raise HTTPException(401, "unauthorized")
        if not api_global_limiter.allow("global"):
            raise HTTPException(429, "server busy", headers={"Retry-After": "10"})

    async def user_auth(_: None = Depends(service_auth), x_session_token: Optional[str] = Header(default=None)) -> int:
        uid = await ctx.web_auth.user_for_token(x_session_token or "")
        if uid is None:
            raise HTTPException(401, "invalid or expired session")
        if not api_user_limiter.allow(uid):
            raise HTTPException(429, "slow down", headers={"Retry-After": str(int(api_user_limiter.retry_after(uid)) + 1)})
        return uid

    # -- public ------------------------------------------------------------
    @app.get("/api/v1/health")
    async def health():
        h = await ctx.health(detailed=False)
        return {"status": h["status"]}  # nothing else is public

    # -- service-level (admin dashboard) ----------------------------------
    @app.get("/api/v1/status", dependencies=[Depends(service_auth)])
    async def status():
        return await ctx.health(detailed=True)

    @app.get("/api/v1/model", dependencies=[Depends(service_auth)])
    async def model():
        st = await ctx.router.status()
        return {"primary": st["primary"], "hf_replica": st["hf_replica"], "openrouter": st["openrouter"],
                "ai_mode": st["ai_mode"]}

    @app.get("/api/v1/stats", dependencies=[Depends(service_auth)])
    async def stats():
        e = ctx.engine
        st = await ctx.router.status()
        return {
            "uptime_seconds": int(time.time() - ctx.started_at),
            "users": await ctx.users.count(),
            "stored_messages": await ctx.conversations.total(),
            "stored_memories": await ctx.memories.count(),
            "requests": e.stats,
            "served_by": st["served"],
            "provider_errors": st["errors"],
            "latency": st["latency"],
            "queue": ctx.queue.stats(),
        }

    # -- admin playground: stateless inference, nothing is stored ---------
    @app.post("/api/v1/playground", dependencies=[Depends(service_auth)])
    async def playground(body: PlaygroundIn):
        text = sanitize_user_text(body.message, s.max_input_chars)
        if not text:
            raise HTTPException(400, "empty message")
        system = sanitize_user_text(body.system, 2000) if body.system else build_system_prompt(s.default_language)
        messages = [{"role": "system", "content": system}, {"role": "user", "content": text}]

        async def job():
            return await ctx.router.chat(messages, max_tokens=body.max_tokens or s.ai_max_tokens_long,
                                         temperature=body.temperature)

        try:
            r = await ctx.queue.submit(PLAYGROUND_USER_ID, job)
        except (UserBusy, QueueFull, QueueClosed, QueueTimeout):
            raise HTTPException(503, "busy", headers={"Retry-After": "5"})
        except AIError:
            raise HTTPException(502, "inference failed")
        return {"reply": r.text, "provider": r.provider, "model": r.model, "latency_ms": r.latency_ms,
                "completion_tokens": r.completion_tokens}

    # -- auth: redeem link code -------------------------------------------
    @app.post("/api/v1/auth/redeem", dependencies=[Depends(service_auth)])
    async def redeem(body: RedeemIn, request: Request):
        if not redeem_limiter.allow(_client_ip(request)):
            raise HTTPException(429, "too many attempts")
        token = await ctx.web_auth.redeem(body.code)
        if not token:
            raise HTTPException(400, "invalid or expired code")
        return {"session_token": token}

    @app.post("/api/v1/auth/logout")
    async def logout(uid: int = Depends(user_auth), x_session_token: Optional[str] = Header(default=None)):
        await ctx.web_auth.revoke(x_session_token or "")
        return {"ok": True}

    # -- per-user ----------------------------------------------------------
    @app.post("/api/v1/chat")
    async def chat(body: ChatIn, uid: int = Depends(user_auth)):
        reply = await ctx.engine.chat(uid, body.message, channel="web")
        code = {"ok": 200, "empty": 400}.get(reply.status, 503 if reply.status in ("busy", "user_busy", "timeout", "db_error", "error") else 200)
        payload = {"status": reply.status, "reply": reply.text, "provider": reply.provider,
                   "model": reply.model, "latency_ms": reply.latency_ms}
        return JSONResponse(payload, status_code=code, headers={"Retry-After": "5"} if code == 503 else None)

    @app.get("/api/v1/history")
    async def history(uid: int = Depends(user_auth)):
        return {"messages": await ctx.engine.history_for_web(uid, 40)}

    @app.get("/api/v1/memory")
    async def memory_list(uid: int = Depends(user_auth)):
        return {"memories": [{"id": str(m["_id"]), "text": m["text"]} for m in await ctx.memories.list(uid)]}

    @app.delete("/api/v1/memory/{memory_id}")
    async def memory_delete(memory_id: str, uid: int = Depends(user_auth)):
        # Match by stringified id inside THIS user's memories only (isolation).
        for m in await ctx.memories.list(uid):
            if str(m["_id"]) == memory_id:
                await ctx.memories.delete_one(uid, m["_id"])
                return {"ok": True}
        raise HTTPException(404, "not found")

    @app.post("/api/v1/reset")
    async def reset(uid: int = Depends(user_auth)):
        await ctx.engine.reset(uid)
        return {"ok": True}

    @app.delete("/api/v1/me")
    async def forget(uid: int = Depends(user_auth)):
        return {"ok": True, "deleted": await ctx.engine.forget(uid)}

    return app
