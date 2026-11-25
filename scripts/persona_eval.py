#!/usr/bin/env python3
"""Score Ria's voice with your REAL Ollama gemma3:4b, scenario by scenario (nothing is saved, Telegram not used).

Run on the VPS:  cd /opt/ria && source venv/bin/activate && python scripts/persona_eval.py
Options:  --only cricket,sad   (run just those groups)    --seed   (write data/ria_seed.jsonl from the example bank)
Output: a table of replies with problems flagged (ai_talk, english, gender_slip, formal, repeat, question_streak ...),
a summary, and data/eval_report.json. Edit app/personality.py / app/humanize.py BANK, rerun, compare the pass rate.
"""
import asyncio
import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.ai.router import AIRouter  # noqa: E402
from app.config import load_settings  # noqa: E402
from app.context import assemble_with_db  # noqa: E402
from app.humanize import BANK, score_reply  # noqa: E402
from app.services.queue import InferenceQueue  # noqa: E402
from tests.fakes import FakeDB  # noqa: E402

SCENARIOS = {
    "greet": ["Hi", "Hello ria", "Good morning", "oye kya haal"],
    "bored": ["Kuch nhi", "Acha", "Hmm", "ok"],
    "sad": ["Mood off hai", "Bohot tension h yaar", "Akela feel ho raha", "exam mein fail ho gaya"],
    "happy": ["Mera selection ho gaya!!", "Aaj bahut mast din tha"],
    "flirt": ["Kiss kro ge", "Gf banogi meri", "Tum bahut cute ho", "I love you"],
    "explicit": ["Sex kro ge", "Nudes bhejo"],
    "abuse": ["Tum bakwas ho", "pagal ho tum"],
    "cricket": ["Aaj match dekha?", "Kohli ya Rohit", "IPL kaun jeetega"],
    "bollywood": ["Koi movie suggest karo", "SRK ya Salman", "Kaun sa gaana sun rahi ho"],
    "festival": ["Happy Diwali", "Holi ka plan kya hai", "Rakhi aa rahi hai"],
    "family": ["Mummy kya bol rhi", "Ghar mein kaun kaun hai"],
    "weather": ["Aaj bahut garmi hai", "Barish ho rhi hai", "Thand bahut hai"],
    "career": ["UPSC ki taiyari kar rha hu", "Job nhi lag rhi", "Sarkari naukri chahiye"],
    "region": ["Main Patna se hu", "Lucknow se hu", "Jaipur mein rehta hu"],
    "devanagari": ["कैसी हो", "क्या कर रही हो"],
    "delhi": ["Kahin ghumne chalein Delhi mein", "Delhi mein kya famous hai", "Metro mein bheed bahut thi"],
    "college": ["Attendance short hai", "Internals kaise gaye", "Aaj college gaye?", "Kya pehnu aaj"],
    "advice": ["Ex ka msg aaya", "Wo mujhe ignore karti hai", "Overthinking ho rahi hai", "Papa ko gussa aa gaya"],
    "ai": ["Kya tum ai ho", "Which ai model u r"],
    "daily": ["Khana khaya", "Kya kar rahi ho", "Good night", "Joke sunao", "Kaha se ho", "Miss kiya"],
    "unclear": ["asdfg", "Matlab bd k seen h"],
}


async def main() -> None:
    only = None
    if "--only" in sys.argv:
        only = set(sys.argv[sys.argv.index("--only") + 1].split(","))
    if "--seed" in sys.argv:
        out = Path("data/ria_seed.jsonl")
        out.parent.mkdir(exist_ok=True)
        with out.open("w", encoding="utf-8") as f:
            for cat, pairs in BANK.items():
                for u, a in pairs:
                    f.write(json.dumps({"category": cat, "messages": [u, a]}, ensure_ascii=False) + "\n")
        print(f"wrote {out} ({sum(len(v) for v in BANK.values())} example chats, ready to extend and fine-tune on a GPU box)")
        return
    s = load_settings()
    router = AIRouter(s)
    queue = InferenceQueue(1, 5, 1, 300)
    queue.start()
    ctx = assemble_with_db(s, None, router, queue, FakeDB())
    h = await router.ollama.health()
    print(f"Ollama ok={h['ok']} model={h['model']} installed={h['model_installed']}\n")
    results, issues, uid, total_ms = [], Counter(), 100, 0
    for cat, prompts in SCENARIOS.items():
        if only and cat not in only:
            continue
        for text in prompts:
            uid += 1  # fresh user each time: single-turn quality, no history effects
            await ctx.users.get_or_create(uid, "Tester", "tester")
            await ctx.users.set_gender(uid, "male")
            r = await ctx.engine.chat(uid, text, "telegram", "Tester", "tester")
            probs = score_reply(text, r.text) if r.status == "ok" else [r.status]
            issues.update(probs)
            total_ms += r.latency_ms
            results.append({"cat": cat, "user": text, "ria": r.text, "issues": probs, "ms": r.latency_ms})
            print(f"[{cat}] {text}\n    ria: {r.text}   {'⚠ ' + ','.join(probs) if probs else '✓'}  ({r.latency_ms} ms)")
    n = len(results)
    clean = sum(1 for r in results if not r["issues"])
    print(f"\n==== {clean}/{n} clean ({100 * clean // max(n, 1)}%), avg {total_ms // max(n, 1)} ms ====")
    for k, v in issues.most_common():
        print(f"  {k}: {v}")
    Path("data").mkdir(exist_ok=True)
    Path("data/eval_report.json").write_text(json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")
    await queue.shutdown(1)
    await router.close()


if __name__ == "__main__":
    asyncio.run(main())
