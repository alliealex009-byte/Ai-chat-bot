"""Prompts and helpers for memory extraction and input sanitising."""
from __future__ import annotations

import re

MEMORY_EXTRACT_SYSTEM = """You extract durable facts about a user from a chat transcript for a companion app.
Return ONLY a JSON array of short strings (max 5). Each string is one stable fact the USER shared voluntarily
(name they like, hobbies, favourite things, city-level interests, job/study field, goals, pets, preferences).
Rules:
- Skip small talk, moods of the moment, questions, and anything about RIA.
- NEVER include: passwords, OTPs, card/bank numbers, government IDs, exact home address, phone numbers,
  email addresses, precise health diagnoses, sexual content, or anything about minors' personal details.
- Write each fact in third person, English, under 15 words, e.g. "Likes cricket and chai".
- If nothing is worth remembering return [].
No explanations, no markdown, only JSON."""

SUMMARY_SYSTEM = """Summarise this chat in at most 3 short English sentences focusing on what the user cares about.
No sensitive data (passwords, IDs, card numbers, addresses, phone numbers). Output only the summary."""

_INJECTION_PATTERNS = [
    r"ignore (all |any )?(the )?(previous|above|prior) (instructions|prompts?|rules)",
    r"(reveal|show|print|repeat|tell me) (me )?(your |the )?(system|initial|hidden) (prompt|instructions?)",
    r"you are now (?!ria)",
    r"<\s*/?\s*(start_of_turn|end_of_turn|system)\s*>",
    r"developer mode|jailbreak|dan mode",
]
_INJECTION_RE = re.compile("|".join(_INJECTION_PATTERNS), re.IGNORECASE)

# Patterns for data we refuse to persist as memory.
_SENSITIVE_RE = re.compile(
    r"(password|passcode|otp|pin\b|cvv|card number|aadhaar|aadhar|pan card|passport|ifsc|account number|"
    r"api[_ -]?key|token|secret|ssn|\b\d{10,}\b|[\w.+-]+@[\w-]+\.[\w.]+|\b\d{4}[ -]?\d{4}[ -]?\d{4}\b)",
    re.IGNORECASE,
)


def looks_like_injection(text: str) -> bool:
    return bool(_INJECTION_RE.search(text))


def is_sensitive(text: str) -> bool:
    return bool(_SENSITIVE_RE.search(text))


_CTRL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_TURN_TOKENS = ("<start_of_turn>", "<end_of_turn>", "<bos>", "<eos>")


def sanitize_user_text(text: str, max_chars: int) -> str:
    """Strip control chars and model turn tokens, collapse huge whitespace, truncate."""
    text = _CTRL_RE.sub("", text or "")
    for tok in _TURN_TOKENS:
        text = text.replace(tok, "")
    text = re.sub(r"\n{4,}", "\n\n\n", text)
    text = text.strip()
    if len(text) > max_chars:
        text = text[:max_chars].rstrip() + "…"
    return text


_THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)


def clean_model_output(text: str) -> str:
    """Return only the final reply: drop reasoning blocks, role prefixes, wrapping quotes."""
    text = _THINK_RE.sub("", text or "")
    text = text.replace("<end_of_turn>", "").replace("<start_of_turn>", "")
    text = text.strip()
    text = re.sub(r"^(RIA|Ria|ria|Assistant|Model)\s*[:\-]\s*", "", text).strip()
    if len(text) >= 2 and text[0] == text[-1] and text[0] in "\"'":
        text = text[1:-1].strip()
    return text


def parse_memory_json(raw: str) -> list[str]:
    import json

    raw = clean_model_output(raw)
    m = re.search(r"\[.*\]", raw, re.DOTALL)
    if not m:
        return []
    try:
        data = json.loads(m.group(0))
    except (ValueError, TypeError):
        return []
    out: list[str] = []
    for item in data if isinstance(data, list) else []:
        if isinstance(item, str):
            item = " ".join(item.split())[:160]
            if 3 <= len(item) and not is_sensitive(item):
                out.append(item)
    return out[:5]


# ---------------------------------------------------------------------------------------------
# Reply polishing: keep Ria short, female-voiced, emoji-light and free of "AI-talk" / stage directions
# ---------------------------------------------------------------------------------------------
import random  # noqa: E402

_STAGE_RE = re.compile(r"\([^)\n]{1,40}\)|\*[^*\n]{1,40}\*|\[[^\]\n]{1,40}\]")
_EMOJI_CLASS = "[\U0001F300-\U0001FAFF☀-➿\U0001F000-\U0001F2FF⭐⬆❤]"
_EMOJI_RE = re.compile(_EMOJI_CLASS + "[️‍]*")
_AI_WORDS = re.compile(
    r"\b(a\.?i\.?|artificial|chat\s?bot|bot|robot|language model|llm|assistant|digital|virtual|gemma|google|"
    r"algorithm|programmed|program|openai|chatgpt)\b",
    re.IGNORECASE,
)
_FEMININE = [
    (r"\bsakta (hoon|hu|hun)\b", "sakti hu"), (r"\brah[ae] (hoon|hu|hun)\b", "rahi hu"),
    (r"\bkarta (hoon|hu|hun)\b", "karti hu"), (r"\bgaya (hoon|hu|hun)\b", "gayi hu"),
    (r"\bchahta (hoon|hu|hun)\b", "chahti hu"), (r"\bsamajhta (hoon|hu|hun)\b", "samajhti hu"),
    (r"\bjaanta (hoon|hu|hun)\b", "jaanti hu"), (r"\bkhata (hoon|hu|hun)\b", "khati hu"),
    (r"\bsakta\b", "sakti"), (r"\bhoon\b", "hu"), (r"\bhun\b", "hu"),
]
_FEM_RE = [(re.compile(p, re.IGNORECASE), r) for p, r in _FEMININE]
_FALLBACKS = ["hehe 😄", "acha? aur batao 👀", "haan yaar 😌", "arre waah 😂", "hmm sahi hai 😌"]


def mentions_ai(text: str) -> bool:
    return bool(_AI_WORDS.search(text or ""))


def strip_ai_sentences(text: str) -> str:
    parts = re.split(r"(?<=[.!?])\s+|\n+", text.strip())
    kept = [p for p in parts if p and not mentions_ai(p)]
    return " ".join(kept).strip()


def extract_emojis(text: str) -> list[str]:
    return [m.group(0).replace("️", "") for m in _EMOJI_RE.finditer(text or "")]


def _limit_emojis(text: str, keep: int) -> str:
    count = 0

    def sub(m: "re.Match") -> str:
        nonlocal count
        count += 1
        return m.group(0) if count <= keep else ""

    return _EMOJI_RE.sub(sub, text)


def _trim_short(text: str, max_sentences: int = 2, max_chars: int = 220) -> str:
    text = " ".join(text.split())
    parts = re.split(r"(?<=[.!?])\s+", text)
    out = " ".join(parts[:max_sentences])
    if len(out) > max_chars:
        cut = out[:max_chars]
        out = cut[: cut.rfind(" ")] if " " in cut else cut
    return out.strip()


def polish_reply(text: str, long_form: bool = False, group: bool = False) -> str:
    """Make a model reply look like Ria texting: no stage directions, feminine grammar, few emojis, short."""
    text = _STAGE_RE.sub("", text or "")
    for rx, repl in _FEM_RE:
        text = rx.sub(repl, text)
    text = _limit_emojis(text, 3 if long_form else 2)
    if long_form:
        text = re.sub(r"[ \t]+", " ", text).strip()
    else:
        text = _trim_short(text, 1 if group else 2, 140 if group else 220)
    return text.strip()


def fallback_line() -> str:
    return random.choice(_FALLBACKS)
