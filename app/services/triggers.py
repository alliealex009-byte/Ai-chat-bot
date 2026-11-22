"""When should Ria answer in a group? (pure functions, no Telegram imports)."""
from __future__ import annotations

import re

# "ria", "Ria", "riaa", "ria!" … but not "material", "Riana" or "variable".
_NAME_RE = re.compile(r"(?<![a-z0-9_])ri+a+(?![a-z0-9_])|रिया", re.IGNORECASE)


def should_respond_in_group(text: str, bot_username: str, replied_to_bot: bool) -> bool:
    if not text:
        return False
    if replied_to_bot:
        return True
    if bot_username and f"@{bot_username}".lower() in text.lower():
        return True
    return bool(_NAME_RE.search(text))


def strip_mention(text: str, bot_username: str) -> str:
    if bot_username:
        text = re.sub(rf"@{re.escape(bot_username)}", "", text, flags=re.IGNORECASE)
    return " ".join(text.split())
