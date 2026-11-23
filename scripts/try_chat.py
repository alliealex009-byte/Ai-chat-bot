#!/usr/bin/env python3
"""Chat with Ria in your terminal using your REAL Ollama gemma3:4b and the exact same pipeline as Telegram
(persona, few-shots, gender, retries, polishing). Nothing is saved (in-memory fake database), Telegram is not used.

Run on the VPS:   cd /opt/ria && source venv/bin/activate && python scripts/try_chat.py
Commands: /boy  /girl  (set user gender)   /reset  /quit
Use it to tune app/personality.py quickly: edit -> run again -> chat.
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.ai.router import AIRouter  # noqa: E402
from app.config import load_settings  # noqa: E402
from app.context import assemble_with_db  # noqa: E402
from app.services.queue import InferenceQueue  # noqa: E402
from tests.fakes import FakeDB  # noqa: E402


async def main() -> None:
    s = load_settings()
    router = AIRouter(s)
    queue = InferenceQueue(1, 5, 1, 300)
    queue.start()
    ctx = assemble_with_db(s, None, router, queue, FakeDB())
    h = await router.ollama.health()
    print(f"Ollama ok={h['ok']} model={h['model']} installed={h['model_installed']}")
    print("Talk to Ria. /boy /girl /reset /quit\n")
    uid = 1
    while True:
        try:
            text = (await asyncio.to_thread(input, "you: ")).strip()
        except (EOFError, KeyboardInterrupt):
            break
        if text == "/quit":
            break
        if text in ("/boy", "/girl"):
            await ctx.users.get_or_create(uid, "Tester", "tester")
            await ctx.users.set_gender(uid, "male" if text == "/boy" else "female")
            print("(gender set)")
            continue
        if text == "/reset":
            await ctx.engine.reset(uid)
            print("(history cleared)")
            continue
        if not text:
            continue
        r = await ctx.engine.chat(uid, text, "telegram", "Tester", "tester")
        print(f"ria: {r.text}   [{r.status} {r.latency_ms} ms]\n")
    await queue.shutdown(1)
    await router.close()


if __name__ == "__main__":
    asyncio.run(main())
