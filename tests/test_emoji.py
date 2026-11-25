from app.emoji import HINT_STICKER, describe, emoji_hint, emoji_mood, is_emoji_only, meaning, sticker_text
from app.humanize import detect_mood, select_fewshot


def test_meanings_include_genz_and_variation_selectors():
    assert "hans" in meaning("😂") and "Gen-Z" in meaning("💀") and "hans" in meaning("😭")
    assert meaning("❤️") == meaning("❤") and meaning("🧿") is None


def test_describe_dedupes_and_caps():
    d = describe("😂😂😂 🥺 🔥 💯 ✨ 🎉 😍")
    assert d.count("😂") == 1 and len(d.split(";")) == 5


def test_emoji_only_and_hint():
    assert is_emoji_only("😂😂") and is_emoji_only("🥺") and not is_emoji_only("hi 😂") and not is_emoji_only("")
    h = emoji_hint("🥺")
    assert "ONLY emojis" in h and "pleading" in h
    assert "ONLY" not in emoji_hint("acha 😂") and emoji_hint("koi emoji nahi") is None


def test_emoji_drives_mood_when_text_has_none():
    assert emoji_mood("😢") == "sad" and emoji_mood("😡") == "angry" and emoji_mood("😂") == "happy" and emoji_mood("hi") is None
    assert detect_mood("💔") == "sad" and detect_mood("🎉🥳") == "happy"
    assert detect_mood("hmm") == "bored"                                   # text rules still win


def test_sticker_text_uses_emoji_and_pack():
    assert sticker_text("😂", "CatMemes") == "[sticker bheja: 😂 = zor se hans raha/rahi, pack: CatMemes]"
    assert sticker_text("", "") == "[sticker bheja: koi emoji nahi]"
    assert "never say you can't" in HINT_STICKER.lower().replace("never say you can't see", "never say you can't")


def test_fewshot_for_stickers_and_emoji_only_messages():
    st = select_fewshot("[sticker bheja: 😂 = zor se hans raha/rahi]", 5)
    assert st[0]["content"].startswith("[sticker bheja")
    em = select_fewshot("🥺", 5)
    assert em[0]["content"] in ("🥺", "😂😂", "🙄")
