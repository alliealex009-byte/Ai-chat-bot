import pytest

from app.ai.errors import AIError, AIModelMissing, AIUnavailable
from app.ai.router import AIRouter
from tests.fakes import FakeProvider, make_settings


def _router(local, replica=None, openrouter=None):
    off = lambda n: type("Off", (), {"enabled": False, "provider": n, "status": lambda self: {"enabled": False},
                                     "start": lambda self: None})()
    return AIRouter(make_settings(), ollama=local, replica=replica or off("hf_replica"),
                    openrouter=openrouter or off("openrouter"))


async def test_local_gemma_is_primary():
    local = FakeProvider("ollama")
    r = await _router(local).chat([{"role": "user", "content": "hi"}])
    assert r.provider == "ollama" and r.model == "gemma3:4b"


async def test_no_fallback_when_disabled_and_error_propagates():
    local = FakeProvider("ollama", [AIUnavailable("down")])
    with pytest.raises(AIUnavailable):
        await _router(local).chat([{"role": "user", "content": "hi"}])


async def test_openrouter_only_after_local_fails_and_is_reported():
    local = FakeProvider("ollama", [AIUnavailable("down")])
    paid = FakeProvider("openrouter", default="fallback reply")
    router = _router(local, openrouter=paid)
    r = await router.chat([{"role": "user", "content": "hi"}])
    assert r.provider == "openrouter"                      # provider is reported, never hidden
    assert router.errors["ollama"] == 1 and router.counts["openrouter"] == 1
    r2 = await router.chat([{"role": "user", "content": "again"}])   # local healthy again -> local
    assert r2.provider == "ollama" and len(paid.calls) == 1


async def test_replica_tried_before_paid_fallback_and_skipped_if_local_ok():
    local = FakeProvider("ollama", [AIUnavailable("x"), "fine"])
    replica = FakeProvider("hf_replica", default="from replica")
    paid = FakeProvider("openrouter")
    router = _router(local, replica, paid)
    assert (await router.chat([{"role": "user", "content": "a"}])).provider == "hf_replica"
    assert (await router.chat([{"role": "user", "content": "b"}])).provider == "ollama"
    assert not paid.calls


async def test_all_providers_fail_raises_last_error():
    local = FakeProvider("ollama", [AIUnavailable("a")])
    paid = FakeProvider("openrouter", [AIError("b")])
    with pytest.raises(AIError):
        await _router(local, openrouter=paid).chat([{"role": "user", "content": "hi"}])


async def test_missing_model_is_never_silently_replaced():
    local = FakeProvider("ollama", [AIModelMissing("gemma3:4b not found")])
    router = _router(local)
    with pytest.raises(AIModelMissing):
        await router.chat([{"role": "user", "content": "hi"}])
    assert local.model == "gemma3:4b"                       # no qwen/other model substitution anywhere


async def test_latency_summary():
    local = FakeProvider("ollama")
    router = _router(local)
    for _ in range(3):
        await router.chat([{"role": "user", "content": "hi"}])
    assert router.latency_summary()["count"] == 3
