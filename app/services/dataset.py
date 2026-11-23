"""Export a training/analysis dataset from stored private chats (owner-triggered).

Pseudonymous (random per-export salt), private chats only (no groups, no secretary-mode chats of third parties),
lines with passwords/IDs/etc. dropped. Output is JSONL ready for review or fine-tuning elsewhere (e.g. a GPU box):
Gemma on this CPU VPS is not trained here; chatting never changes the model weights.
"""
from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone

from app.ai.prompts import is_sensitive


async def build_dataset(ctx, path: str, window: int = 12) -> dict:
    docs = await ctx.conversations.export_dm()
    salt = os.urandom(8).hex()
    by_user: dict[int, list[dict]] = {}
    for d in docs:
        if is_sensitive(d["content"]):
            continue
        by_user.setdefault(d["user_id"], []).append({"role": d["role"], "content": d["content"]})
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    rows = 0
    with open(path, "w", encoding="utf-8") as f:
        for uid, msgs in by_user.items():
            pid = hashlib.sha256(f"{salt}:{uid}".encode()).hexdigest()[:10]
            for i in range(0, len(msgs), window):
                chunk = msgs[i:i + window]
                if any(m["role"] == "assistant" for m in chunk) and any(m["role"] == "user" for m in chunk):
                    f.write(json.dumps({"user": pid, "messages": chunk}, ensure_ascii=False) + "\n")
                    rows += 1
    return {"users": len(by_user), "rows": rows, "messages": sum(len(m) for m in by_user.values()),
            "at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
