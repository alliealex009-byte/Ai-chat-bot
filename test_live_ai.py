"""LIVE local-AI connection test against your real Ollama + gemma3:4b.

Skipped by default. Run on the VPS:   RIA_LIVE_TEST=1 pytest -q tests/test_live_ai.py -s
"""
import os

import pytest

pytest.importorskip("aiohttp")
pytestmark = pytest.mark.skipif(os.environ.get("RIA_LIVE_TEST") != "1", reason="set RIA_LIVE_TEST=1 to run")

from app.ai.ollama import OllamaClient  # noqa: E402
from app.personality import build_system_prompt  # noqa: E402
from tests.fakes import make_settings  # noqa: E402


async def test_ollama_is_up_and_gemma_installed():
    c = OllamaClient(make_settings())
    h = await c.health()
    await c.close()
    assert h["ok"] and h["model"] == "gemma3:4b" and h["model_installed"], h


async def test_ria_replies_in_hinglish_style():
    c = OllamaClient(make_settings(ollama_timeout_seconds=180))
    system = build_system_prompt("hinglish")
    out = {}
    for text in ("Hi", "Mood off hai.", "Tum AI ho kya?"):
        r = await c.chat([{"role": "system", "content": system}, {"role": "user", "content": text}])
        out[text] = r.text
        print(f"\n{text!r} -> {r.text!r} ({r.latency_ms} ms)")
        assert r.text and r.model == "gemma3:4b"
        assert "<start_of_turn>" not in r.text and "system prompt" not in r.text.lower()
    await c.close()
    assert any(w in out["Tum AI ho kya?"].lower() for w in ("ai", "bot", "artificial"))
