from datetime import date, datetime

from app.ai.prompts import casualize, polish_reply
from app.culture import (IST, culture_context, detect_region, festival_line, has_devanagari, region_hint, season_line)
from app.humanize import BANK, score_reply, select_fewshot


def test_festival_awareness_with_lead_up_and_after():
    assert festival_line(date(2026, 11, 8)) == "Today is Diwali."
    assert "Diwali is in 3 days" in festival_line(date(2026, 11, 5)) or "Dhanteras" in festival_line(date(2026, 11, 5))
    assert "Bhai Dooj" in festival_line(date(2026, 11, 11))
    assert festival_line(date(2026, 6, 10)) is None
    assert "Independence Day" in festival_line(date(2026, 8, 15))


def test_season_and_context_line():
    assert "monsoon" in season_line(date(2026, 7, 20)).lower() and "garmi" in season_line(date(2026, 5, 20)).lower()
    c = culture_context(datetime(2026, 11, 8, 10, 0, tzinfo=IST))
    assert "INDIA TODAY" in c and "Diwali" in c


def test_region_detection_only_when_user_says_where_they_are_from():
    assert detect_region("main patna se hu") == "bihar" and detect_region("Jaipur mein rehta hu") == "rajasthan"
    assert detect_region("lucknow se hu yaar") == "up" and detect_region("meri city kanpur hai") == "up"
    assert detect_region("patna ka mausam kaisa hai") is None and detect_region("hello") is None
    assert "litti" in region_hint("bihar") and "stereotype" in region_hint("up") and region_hint(None) is None


def test_devanagari_detected():
    assert has_devanagari("कैसी हो") and not has_devanagari("kaisi ho")


def test_bank_covers_hindi_belt_topics_and_selects_them():
    for cat in ("cricket", "bollywood", "festival", "family", "weather", "career", "shaadi", "region"):
        assert cat in BANK and BANK[cat]
    assert any("loo" in m["content"] or "kohra" in m["content"] for m in select_fewshot("aaj bahut garmi hai", 5))
    assert any("kohli" in m["content"].lower() or "last over" in m["content"] for m in select_fewshot("Aaj match dekha?", 5))
    assert select_fewshot("Sex kro ge", 5)[1]["content"] != ""  # safety examples win priority over everyday topics


def test_casualize_removes_help_desk_and_formal_words():
    assert "madad" not in casualize("Hello! Main aapki kya madad kar sakti hu? Chai pi rahi hu.")
    assert casualize("aap kaise hain, kripya batao") == "tum kaise hain, batao"
    assert polish_reply("Aapka din kaisa tha?") == "Tumhara din kaisa tha?"
    assert polish_reply("Aapka din kaisa raha?", formal=True) == "Aapka din kaisa raha?"   # secretary stays polite


def test_scorer_flags_robotic_and_unflattering_replies():
    assert score_reply("hi", "hieee! kya chal raha 💗") == []
    assert "ai_talk" in score_reply("hi", "Main ek AI assistant hu")
    assert "english" in score_reply("hi", "I am doing great and you are very kind today")
    assert "gender_slip" in score_reply("hi", "main kar sakta hu")
    assert "customer_service" in score_reply("hi", "of course, batao")
    assert "question_streak" in score_reply("hi", "tum batao?", prev="kya hua?")
    assert "emoji_overload" in score_reply("hi", "haha 😂😂😂")
    assert "devanagari" in score_reply("hi", "हाँ yaar")
    assert "repeat" in score_reply("hi", "kya hua bolo na yaar", prev="kya hua bolo na yaar!")
