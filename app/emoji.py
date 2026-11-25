"""Understanding the user's emojis and stickers.

Emojis carry mood ("😭" can mean crying OR laughing hard, "💀" means "I'm dead (laughing)"). We translate the emojis
a user sent into a short Hinglish meaning for the model, and a sticker is understood through the emoji the sender
attached to it (Telegram stores one for every sticker) plus its pack name. The model then answers contextually.
"""
from __future__ import annotations

import re
from typing import Optional

from app.ai.prompts import extract_emojis

# base emoji (no variation selector) -> (meaning, mood)   mood in {happy, sad, angry, love, shy, tired, None}
M: dict[str, tuple[str, Optional[str]]] = {
    "😂": ("zor se hans raha/rahi", "happy"), "🤣": ("lot-pot hasi", "happy"), "😁": ("daant dikha ke khush", "happy"),
    "😄": ("khush", "happy"), "😊": ("pyari si smile, khush", "happy"), "😀": ("khush", "happy"), "😃": ("khush", "happy"),
    "😆": ("hans hans ke bura haal", "happy"), "😅": ("nervous hasi / chalo theek hai", None), "🙂": ("halki smile", None),
    "😉": ("wink, mazaak ya flirt", None), "😏": ("smirk, tease ya halka flirt", None), "😎": ("cool swag", "happy"),
    "🥰": ("pyaar aur khushi", "love"), "😍": ("fida ho gaya/gayi", "love"), "😘": ("flying kiss", "love"),
    "😗": ("halka kiss", "love"), "🥹": ("emotional, aankhein bhar aayi (pyaar se)", "sad"), "🥺": ("pleading, emotional, 'please'", "sad"),
    "😢": ("rona", "sad"), "😭": ("bahut rona YA hans hans ke ro dena (Gen-Z mein 'mar gaya/gayi')", None),
    "😞": ("udaas", "sad"), "😔": ("udaas, thoda hurt", "sad"), "😟": ("fikar, worried", "sad"), "😩": ("thak gaya/gayi, dukhi", "sad"),
    "😫": ("bahut thak gaya/gayi", "tired"), "🥱": ("neend aa rahi hai, bore", "tired"), "😴": ("so raha/rahi hai", "tired"),
    "😒": ("irritated, mood kharab, 'seriously?'", "angry"), "🙄": ("eye-roll, 'haan haan ok'", "angry"),
    "😤": ("gusse mein, chidh", "angry"), "😡": ("bahut gussa", "angry"), "🤬": ("bahut hi gussa", "angry"),
    "😠": ("gussa", "angry"), "🤡": ("mazaak udana / khud ko joker bolna", None), "💀": ("hans hans ke mar gaya/gayi (Gen-Z)", "happy"),
    "☠": ("hans hans ke mar gaya/gayi (Gen-Z)", "happy"), "🙈": ("sharma gaya/gayi ya embarrassed", "shy"), "🙊": ("chup, secret", "shy"),
    "🙉": ("sunna nahi chahta/chahti", None), "😳": ("shock ya sharam", "shy"), "😬": ("awkward, yikes", None),
    "🤭": ("chupke se hasi, gossip", "happy"), "🤫": ("shh, secret", None), "🤔": ("soch mein, doubt", None),
    "🧐": ("shak se dekhna", None), "🤨": ("ek bhaunh uthake, shak", None), "😐": ("expressionless, bore", None),
    "😑": ("bore, 'koi baat nahi'", None), "😶": ("chup, speechless", None), "🫠": ("pighal gaya/gayi, embarrassed", "shy"),
    "😱": ("shock, dar", None), "😨": ("dar gaya/gayi", None), "😰": ("ghabrahat, tension", "sad"), "🤯": ("dimaag udd gaya, shock", None),
    "🥳": ("party, celebration", "happy"), "🎉": ("celebration", "happy"), "🎂": ("birthday", "happy"), "🤩": ("star-struck, bahut excited", "happy"),
    "🔥": ("fire, bahut badhiya / hot", "happy"), "💯": ("100%, pakka", "happy"), "✨": ("sparkle, mast vibe", "happy"),
    "❤": ("pyaar", "love"), "💗": ("pyaar", "love"), "💖": ("pyaar", "love"), "💕": ("pyaar", "love"), "💘": ("pyaar (cupid)", "love"),
    "💞": ("pyaar", "love"), "🩷": ("pyaar", "love"), "🫶": ("pyaar bhara hug/heart hands", "love"), "💔": ("dil toota", "sad"),
    "🤗": ("hug", "love"), "🫂": ("hug, saath hu", "love"), "🤝": ("deal / dosti", None), "🙏": ("please / thank you / pranam", None),
    "👍": ("theek hai, ok", None), "👎": ("nahi, pasand nahi", None), "👌": ("perfect, ok", None), "👏": ("taali, shabaash", "happy"),
    "🙌": ("celebration, yay", "happy"), "🤌": ("kya baat hai / italian 'matlab kya'", None), "💪": ("strong, himmat", "happy"),
    "👀": ("dekh raha/rahi hu, interesting, gossip", None), "😈": ("shararat, naughty", None), "😇": ("masoom, angel", None),
    "🥵": ("garmi ya hot", None), "🥶": ("thand", None), "🤤": ("munh mein paani, bahut tempting", None), "🤢": ("ghin aayi", None),
    "🤒": ("bimar", "sad"), "🤕": ("chot lagi / dard", "sad"), "😷": ("bimar / mask", "sad"), "🫡": ("salute, 'roger that'", None),
    "🙃": ("ulti smile, sarcastic / thoda off", None), "😌": ("sukoon, relief, chill", None), "😋": ("yummy", "happy"),
    "😜": ("shararat, wink + jeebh", "happy"), "🤪": ("pagalpan, crazy fun", "happy"), "😝": ("chidhana, jeebh nikalna", "happy"),
    "🥲": ("muskurate hue aansu, bitter-sweet", "sad"), "😪": ("neend + udaasi", "tired"), "😓": ("thaka hua, pareshan", "sad"),
    "👋": ("hello / bye", None), "🫰": ("snap, 'bas kya'", None), "💅": ("slay, 'mujhe farak nahi padta'", None),
    "🍕": ("pizza", None), "☕": ("chai/coffee", None), "🍜": ("maggi/noodles", None), "🥟": ("momos", None), "🎧": ("music", None),
    "🌧": ("barish", None), "🌙": ("raat, good night", None), "☀": ("din/dhoop", None),
}
_MOOD_ORDER = ("sad", "angry", "love", "shy", "tired", "happy")


def _base(e: str) -> str:
    return e.replace("️", "").replace("‍", "")


def meaning(e: str) -> Optional[str]:
    m = M.get(_base(e))
    return m[0] if m else None


def emoji_mood(text: str) -> Optional[str]:
    """Dominant mood of the emojis in a message (None if none or ambiguous)."""
    moods = [M[b][1] for b in (_base(e) for e in extract_emojis(text)) if b in M and M[b][1]]
    for mood in _MOOD_ORDER:
        if mood in moods:
            return mood
    return None


def describe(text: str, limit: int = 5) -> str:
    seen, out = set(), []
    for e in extract_emojis(text):
        b = _base(e)
        if b in seen or b not in M:
            continue
        seen.add(b)
        out.append(f"{e} = {M[b][0]}")
        if len(out) >= limit:
            break
    return "; ".join(out)


def is_emoji_only(text: str) -> bool:
    t = (text or "").strip()
    return bool(t) and not re.sub(r"[\s‍️]", "", re.sub(r"[\U0001F000-\U0001FAFF←-⯿☀-➿]", "", t))


def emoji_hint(text: str) -> Optional[str]:
    d = describe(text)
    if not d:
        return None
    lead = "The user sent ONLY emojis, so answer the feeling behind them. " if is_emoji_only(text) else ""
    return (f"EMOJI MEANINGS in the user's message ({d}). {lead}Read their mood from these like a friend would "
            "(Gen-Z: 😭 and 💀 often mean laughing). Never explain the emojis back to them.")


def sticker_text(emoji: str, set_name: str = "") -> str:
    """What the model 'sees' when the user sends a sticker (stored in history instead of the image)."""
    d = describe(emoji or "", 2)
    pack = f", pack: {set_name[:30]}" if set_name else ""
    return f"[sticker bheja: {d or emoji or 'koi emoji nahi'}{pack}]"


HINT_STICKER = ("The user sent a STICKER (shown in brackets with the emoji it carries). React to its mood the way you would to a friend's "
                "sticker: one short natural line, maybe a tease or a question. Never say you can't see or read stickers and never "
                "describe the sticker back.")
