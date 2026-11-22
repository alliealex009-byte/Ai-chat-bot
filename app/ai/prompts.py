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
