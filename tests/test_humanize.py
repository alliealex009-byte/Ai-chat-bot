import random
from datetime import datetime

from app.humanize import (BANK, IST, day_part, detect_mood, humanize, mood_hint, now_context, select_fewshot,
                          split_bubbles, too_similar)
from app.personality import build_system_prompt


def test_time_context_knows_indian_time_of_day():
    late = now_context(datetime(2026, 11, 25, 2, 10, tzinfo=IST))
    assert "around 2 AM" in late and "Wednesday" in late and "late night" in late
    assert day_part(8) == "morning" and day_part(13) == "afternoon" and day_part(18) == "evening" and day_part(22) == "night"
    assert "RIGHT NOW" in build_system_prompt(now_line=late)


def test_mood_detection_and_hints():
    assert detect_mood("Mood off hai yaar") == "sad" and "No jokes" in mood_hint("bohot tension h")
    assert detect_mood("mera selection ho gaya") == "happy"
    assert detect_mood("Hmm") == "bored" and detect_mood("kuch nhi") == "bored"
    assert detect_mood("aaj weather mast hai") is None and mood_hint("hello") is None


def test_fewshot_selection_is_small_relevant_and_well_formed():
    out = select_fewshot("Kiss kro ge", 5, random.Random(1))
    assert 2 <= len(out) <= 10 and len(out) % 2 == 0
    assert [m["role"] for m in out] == ["user", "assistant"] * (len(out) // 2)
    assert any("pagal ho kya" in m["content"] or "dost toh ban" in m["content"] or "sharma" in m["content"] for m in out)
    assert any("Mood off" in m["content"] for m in select_fewshot("mood off hai", 5, random.Random(2)))
    assert len(select_fewshot("kuch bhi random baat", 4)) <= 8


def test_bank_is_clean_and_in_character():
    for pairs in BANK.values():
        for u, a in pairs:
            txt = a["content"].lower()
            assert u["role"] == "user" and a["role"] == "assistant"
            assert not any(w in txt for w in ("assistant", " ai ", "bot ", "karta hu", "raha hu", "sakta"))


def test_humanize_drops_back_to_back_questions_and_repeated_openers():
    assert humanize("haha sahi hai. tum batao?", "kya hua? bolo na?") == "haha sahi hai."
    assert humanize("tum batao?", "kya hua?") == "tum batao?"                     # single sentence kept
    assert humanize("arre waah, mast hai", "arre kya hua?") == "waah, mast hai"
    assert humanize("haha sahi", None) == "haha sahi"


def test_similarity_detection():
    assert too_similar("kya hua? bolo na", "kya hua? bolo na!") and not too_similar("kya hua", "mast hu yaar, chai pi rahi hu")


def test_two_bubbles_only_for_two_real_sentences():
    r = random.Random(0)
    assert split_bubbles("haha sahi hai yaar. ab tum batao kya plan hai", r, chance=1.0) == ["haha sahi hai yaar.", "ab tum batao kya plan hai"]
    assert split_bubbles("hi", r, chance=1.0) == ["hi"]
    assert split_bubbles("ek sentence hi hai ye", r, chance=1.0) == ["ek sentence hi hai ye"]
    assert split_bubbles("haha sahi hai yaar. ab tum batao kya plan hai", r, chance=0.0)[0].endswith("hai yaar. ab tum batao kya plan hai")


def test_reactions_are_rare_valid_and_mood_based():
    from app.humanize import ALLOWED_REACTIONS, pick_reaction
    r = random.Random(0)
    outs = [pick_reaction("mood off hai", r) for _ in range(50)]
    assert set(outs) <= {"🤗", "❤"} and all(o in ALLOWED_REACTIONS for o in outs)
    assert all(pick_reaction("aaj kya khaya", random.Random(i)) in (None, "👀") for i in range(100))
    assert sum(1 for i in range(200) if pick_reaction("haha lol", random.Random(i))) > 20
    assert all(e in ALLOWED_REACTIONS for e in ("🎉", "🔥", "😍", "🥰", "😘", "🤣", "😁"))


def test_new_everyday_topics_are_selected():
    assert any("Hauz Khas" in m["content"] for m in select_fewshot("Delhi mein kahan ghumne chalein", 5, random.Random(1)))
    assert any("attendance" in m["content"].lower() for m in select_fewshot("attendance short hai", 5, random.Random(1)))
    assert any("birthday" in m["content"].lower() for m in select_fewshot("aaj mera birthday hai", 5, random.Random(1)))
