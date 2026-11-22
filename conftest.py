"""Test setup: lets `async def test_*` run without pytest-asyncio, and builds a wired engine on fakes."""
from __future__ import annotations

import asyncio
import inspect
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def pytest_pyfunc_call(pyfuncitem):
    if inspect.iscoroutinefunction(pyfuncitem.obj):
        args = {a: pyfuncitem.funcargs[a] for a in pyfuncitem._fixtureinfo.argnames}
        asyncio.run(pyfuncitem.obj(**args))
        return True
    return None


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    """Keep the developer's real environment out of the tests."""
    import os

    for k in list(os.environ):
        if k.startswith(("TELEGRAM_", "OLLAMA_", "MONGO_", "API_", "AI_", "OPENROUTER_", "HF_", "ENABLE_")):
            monkeypatch.delenv(k, raising=False)


@pytest.fixture
def stack():
    """Fully wired engine on in-memory fakes. Returns a SimpleNamespace."""
    from types import SimpleNamespace

    from app.ai.router import AIRouter
    from app.context import assemble_with_db
    from app.services.queue import InferenceQueue
    from tests.fakes import FakeDB, FakeProvider, make_settings

    s = make_settings(memories_in_prompt=5, memory_extract_every_n_messages=2)
    db = FakeDB()
    local = FakeProvider("ollama")
    router = AIRouter(s, ollama=local, replica=SimpleNamespace(enabled=False, provider="hf_replica", start=lambda: None,
                                                               close=None, status=lambda: {"enabled": False}),
                      openrouter=SimpleNamespace(enabled=False, provider="openrouter", status=lambda: {"enabled": False}))
    queue = InferenceQueue(2, 10, 1, 30)
    ctx = assemble_with_db(s, None, router, queue, db)
    return SimpleNamespace(ctx=ctx, db=db, local=local, router=router, queue=queue, settings=s, engine=ctx.engine)
