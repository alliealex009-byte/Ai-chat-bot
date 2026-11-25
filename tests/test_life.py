from datetime import datetime

from app.humanize import IST
from app.life import MOMENTS, activity_line, closeness_hint, life_moment, topic_knowledge


def test_activity_follows_a_college_girls_day_and_is_stable_within_the_hour():
    mon_10 = datetime(2026, 11, 23, 10, 5, tzinfo=IST)
    mon_10b = datetime(2026, 11, 23, 10, 55, tzinfo=IST)
    assert activity_line(mon_10) == activity_line(mon_10b)                       # stable prefix = cacheable
    sat_noon = activity_line(datetime(2026, 11, 28, 12, 0, tzinfo=IST))
    assert any(w in sat_noon for w in ("Sarojini", "Hauz Khas", "laundry"))
    late = activity_line(datetime(2026, 11, 25, 2, 0, tzinfo=IST))
    assert any(w in late for w in ("sleep", "awake", "overthinking", "scrolling"))
    line = activity_line(mon_10)
    assert "WHAT YOU ARE DOING" in line and "never force" in line


def test_life_moments_vary_but_are_deterministic():
    assert life_moment(3) == life_moment(3)
    assert len({life_moment(i) for i in range(40)}) > 5 and len(MOMENTS) >= 20


def test_closeness_grows_with_chat_count():
    new, mid, close, best = (closeness_hint(n) for n in (2, 20, 80, 300))
    assert "just met" in new and "becoming friends" in mid and "close friends" in close and "best-friend" in best
    assert "look forward" in closeness_hint(300, streak=7) and "look forward" not in closeness_hint(300, streak=0)


def test_topic_knowledge_only_when_relevant_and_capped():
    assert topic_knowledge("aaj mausam mast hai") == []
    assert "Hauz Khas" in topic_knowledge("kahin ghumne chalein")[0]
    assert "Rajiv Chowk" in topic_knowledge("metro mein bheed")[0]
    assert "attendance" in topic_knowledge("DU mein attendance short hai")[0]
    assert len(topic_knowledge("metro DU momos kurti instagram", limit=2)) == 2
    assert "doctor" in topic_knowledge("pimples ho gaye hain skincare batao")[0]
