"""Desi context for Ria: festivals, seasons, college calendar and Hindi-belt regions.

Everything here only produces short *hints* for the prompt. Festival dates that follow the lunar calendar are
approximate (+/- 1 day); edit MOVING below once a year. Regional hints are deliberately light: a local food, place
or festival to mention warmly, never an imitated accent and never a stereotype.
"""
from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from typing import Optional

from app.humanize import IST

FIXED: dict[tuple[int, int], str] = {
    (1, 1): "New Year", (1, 13): "Lohri", (1, 26): "Republic Day", (2, 14): "Valentine's Day", (8, 15): "Independence Day",
    (9, 5): "Teachers' Day", (10, 2): "Gandhi Jayanti", (11, 14): "Children's Day", (12, 25): "Christmas",
    (12, 31): "New Year's Eve",
}
# (date, name, days of excitement before it)
MOVING: list[tuple[date, str, int]] = [
    (date(2026, 1, 14), "Makar Sankranti", 1), (date(2026, 1, 23), "Basant Panchami", 1),
    (date(2026, 2, 15), "Mahashivratri", 2), (date(2026, 3, 3), "Holi", 4), (date(2026, 3, 19), "Chaitra Navratri", 1),
    (date(2026, 3, 26), "Ram Navami", 1), (date(2026, 8, 27), "Raksha Bandhan", 5), (date(2026, 9, 4), "Janmashtami", 2),
    (date(2026, 9, 14), "Ganesh Chaturthi", 3), (date(2026, 10, 11), "Sharad Navratri", 1),
    (date(2026, 10, 20), "Dussehra", 3), (date(2026, 10, 28), "Karwa Chauth", 3), (date(2026, 11, 6), "Dhanteras", 2),
    (date(2026, 11, 8), "Diwali", 7), (date(2026, 11, 11), "Bhai Dooj", 2), (date(2026, 11, 15), "Chhath Puja", 3),
    (date(2027, 1, 15), "Makar Sankranti", 1), (date(2027, 3, 6), "Mahashivratri", 2), (date(2027, 3, 22), "Holi", 4),
    (date(2027, 4, 14), "Ram Navami", 1), (date(2027, 8, 24), "Janmashtami", 2), (date(2027, 9, 4), "Ganesh Chaturthi", 3),
    (date(2027, 9, 30), "Sharad Navratri", 1), (date(2027, 10, 9), "Dussehra", 3), (date(2027, 10, 29), "Diwali", 7),
]


def festival_line(today: date) -> Optional[str]:
    cands: list[tuple[int, str]] = []
    for (m, d), name in FIXED.items():
        for yr in (today.year, today.year + 1):
            dt = date(yr, m, d)
            cands.append(((dt - today).days, name))
    for dt, name, lead in MOVING:
        cands.append(((dt - today).days, name))
    best: Optional[tuple[int, str]] = None
    lead_of = {name: lead for _, name, lead in MOVING}
    for delta, name in cands:
        lead = lead_of.get(name, 1)
        if -2 <= delta <= lead and (best is None or abs(delta) < abs(best[0])):
            best = (delta, name)
    if not best:
        return None
    delta, name = best
    if delta == 0:
        return f"Today is {name}."
    if delta > 0:
        return f"{name} is {'tomorrow' if delta == 1 else f'in {delta} days'}."
    return f"{name} was {'yesterday' if delta == -1 else f'{-delta} days ago'}."


def season_line(today: date) -> str:
    m = today.month
    base = {
        12: "Delhi winter: cold mornings, kohra (fog), rajai, gajar ka halwa, chai.",
        1: "Delhi winter: very cold, kohra (fog), rajai, moongfali, chai.",
        2: "Late winter turning spring: pleasant, board-exam season for school kids.",
        3: "Spring and Holi season, IPL starting, warm days.",
        4: "Garmi starting, loo, aam panna, IPL on, sem exams near.",
        5: "Peak garmi (loo, 45 degrees), IPL finals, college semester exams, aam season.",
        6: "Brutal garmi, summer break, CUET/admission buzz, aam and lassi.",
        7: "Monsoon: barish, humid, chai-pakoda, waterlogging jokes, new college session.",
        8: "Monsoon: barish, Independence Day, Rakhi season.",
        9: "Humid end of monsoon, festival season starting.",
        10: "Festival season (Navratri, Dussehra, Karwa Chauth), mild mornings, Diwali shopping, pollution talk.",
        11: "Diwali/Chhath season, smog and pollution, getting colder, shaadi season starting.",
    }
    return base[m]


def culture_context(now: Optional[datetime] = None) -> str:
    today = (now or datetime.now(IST)).astimezone(IST).date()
    f = festival_line(today)
    parts = [f"INDIA TODAY: {season_line(today)}"]
    if f:
        parts.append(f)
    parts.append("Mention such things only when natural, like a friend would; never list them.")
    return " ".join(parts)


# ------------------------------------------------------------------ regions
REGIONS: dict[str, tuple[re.Pattern, str]] = {
    "delhi": (re.compile(r"\b(delhi|dilli|noida|gurgaon|gurugram|ghaziabad|faridabad|ncr|dwarka|rohini|saket)\b", re.I),
              "The user is from Delhi-NCR, same as you: bond over metro, momos, chole bhature, Sarojini, Connaught Place, CP ke parathe."),
    "up": (re.compile(r"\b(lucknow|kanpur|varanasi|banaras|benaras|prayagraj|allahabad|agra|mathura|meerut|gorakhpur|bareilly|"
                      r"aligarh|jhansi|uttar pradesh|up se|u\.p)\b", re.I),
           "The user is from Uttar Pradesh: warmly mention chaat, kebab/tunday (Lucknow), banarasi paan, Ganga ghat, petha (Agra), chai-samosa."),
    "bihar": (re.compile(r"\b(bihar|patna|gaya|muzaffarpur|darbhanga|bhagalpur|ranchi|jharkhand|jamshedpur|dhanbad)\b", re.I),
              "The user is from Bihar/Jharkhand: warmly mention litti-chokha, sattu, Chhath, Patna, and how hard people there work for UPSC/exams."),
    "mp": (re.compile(r"\b(bhopal|indore|gwalior|jabalpur|ujjain|madhya pradesh|mp se|raipur|chhattisgarh|bilaspur)\b", re.I),
           "The user is from Madhya Pradesh/Chhattisgarh: warmly mention poha-jalebi, Indore's sarafa and street food, Bhopal's lakes, Mahakal."),
    "rajasthan": (re.compile(r"\b(rajasthan|jaipur|jodhpur|udaipur|kota|ajmer|bikaner|pushkar)\b", re.I),
                  "The user is from Rajasthan: warmly mention dal-baati-churma, pyaaz kachori, forts, 'padharo', Kota's coaching life."),
    "haryana_punjab": (re.compile(r"\b(haryana|rohtak|panipat|karnal|hisar|sonipat|ambala|punjab|chandigarh|ludhiana|amritsar|"
                                  r"jalandhar|patiala|mohali)\b", re.I),
                       "The user is from Haryana/Punjab: warmly mention parathe with lassi, Amritsari kulcha, Chandigarh, Punjabi music, bhangra."),
    "pahadi": (re.compile(r"\b(uttarakhand|dehradun|haridwar|rishikesh|nainital|almora|himachal|shimla|manali|dharamshala|kullu)\b", re.I),
               "The user is from the hills (Uttarakhand/Himachal): warmly mention mountains, maggi at a dhaba, Maggi-chai, snow, pahadi life."),
}
_FROM = re.compile(r"(\bse hu\b|\bse hoon\b|\bse hun\b|\brehta\b|\brehti\b|\brahta\b|\brahti\b|\bfrom\b|\bmera ghar\b|\bmeri city\b|\bmera sheher\b)", re.I)


def detect_region(text: str) -> Optional[str]:
    """Region the user says they live in / come from (only when they phrase it that way)."""
    t = text or ""
    if not _FROM.search(t):
        return None
    for key, (rx, _) in REGIONS.items():
        if rx.search(t):
            return key
    return None


def region_hint(region: Optional[str]) -> Optional[str]:
    if region in REGIONS:
        return REGIONS[region][1] + " Light touch: one local thing, no accent mimicry, no stereotypes."
    return None


_DEVANAGARI = re.compile(r"[ऀ-ॿ]")
HINT_DEVANAGARI = ("The user wrote in Devanagari Hindi script. Understand it fully, but reply in Roman Hinglish (English letters), "
                   "never in Devanagari.")


def has_devanagari(text: str) -> bool:
    return len(_DEVANAGARI.findall(text or "")) >= 2
