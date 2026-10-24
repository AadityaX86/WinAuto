"""Understands everyday time phrases: "tomorrow 5pm", "in 10 minutes", "friday", "oct 25".

No dependencies; covers what people actually type to an assistant. Anything
it can't read returns None and the caller can ask again.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

WEEKDAYS = {
    "monday": 0, "tuesday": 1, "tues": 1, "wednesday": 2, "weds": 2, "thursday": 3,
    "thurs": 3, "friday": 4, "fri": 4, "saturday": 5, "sunday": 6,
}
MONTHS = {
    "january": 1, "jan": 1, "february": 2, "feb": 2, "march": 3, "mar": 3, "april": 4,
    "apr": 4, "may": 5, "june": 6, "jun": 6, "july": 7, "jul": 7, "august": 8, "aug": 8,
    "september": 9, "sept": 9, "sep": 9, "october": 10, "oct": 10, "november": 11,
    "nov": 11, "december": 12, "dec": 12,
}
NUMBER_WORDS = {
    "a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
    "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12,
    "fifteen": 15, "twenty": 20, "thirty": 30, "forty": 40, "forty-five": 45, "fifty": 50,
    "sixty": 60, "ninety": 90, "a couple of": 2, "a couple": 2, "couple of": 2,
    "a few": 3, "few": 3, "half a": 0.5, "half an": 0.5,
}
DAY_PARTS = {
    "noon": time(12, 0), "midday": time(12, 0), "midnight": time(0, 0),
    "morning": time(9, 0), "afternoon": time(15, 0), "evening": time(18, 0),
    "tonight": time(20, 0), "night": time(21, 0),
}
UNIT_SECONDS = {
    "s": 1, "sec": 1, "secs": 1, "second": 1, "seconds": 1,
    "m": 60, "min": 60, "mins": 60, "minute": 60, "minutes": 60,
    "h": 3600, "hr": 3600, "hrs": 3600, "hour": 3600, "hours": 3600,
    "d": 86400, "day": 86400, "days": 86400,
    "w": 604800, "wk": 604800, "wks": 604800, "week": 604800, "weeks": 604800,
}

_NUM = r"(\d+(?:\.\d+)?|half an?|a couple(?: of)?|couple of|a few|few|an?|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|fifteen|twenty|thirty|forty-five|forty|fifty|sixty|ninety)"
_UNIT = r"(seconds?|secs?|minutes?|mins?|hours?|hrs?|days?|weeks?|wks?|s|m|h|d|w)"
_MONTH = "|".join(sorted(MONTHS, key=len, reverse=True))
_WEEKDAY = "|".join(sorted(WEEKDAYS, key=len, reverse=True))

RE_ISO = re.compile(r"\b(?:on\s+|by\s+)?(\d{4})-(\d{1,2})-(\d{1,2})(?:[ t](\d{1,2}):(\d{2}))?\b")
RE_RELATIVE = re.compile(rf"\b(?:in|after)\s+{_NUM}\s*{_UNIT}\b(?:\s+and\s+a\s+half)?")
RE_HALF_HOUR = re.compile(r"\b(?:in|after)\s+(?:an?\s+)?half\s+(?:an\s+)?hour\b")
RE_REL_DAY = re.compile(r"\b(?:on\s+|by\s+)?(day after tomorrow|today|tonight|tomorrow|tomorow|tmrw|tmr)\b")
RE_WEEKDAY = re.compile(rf"\b(?:on\s+|by\s+)?(?:(next|this|coming)\s+)?({_WEEKDAY})\b")
RE_NEXT_WEEK = re.compile(r"\b(?:by\s+)?(next week|this weekend|the weekend|weekend)\b")
RE_DAY_MONTH = re.compile(rf"\b(?:on\s+|by\s+)?(\d{{1,2}})(?:st|nd|rd|th)?\s+(?:of\s+)?({_MONTH})\.?(?:,?\s+(\d{{4}}))?\b")
RE_MONTH_DAY = re.compile(rf"\b(?:on\s+|by\s+)?({_MONTH})\.?\s+(\d{{1,2}})(?:st|nd|rd|th)?(?:,?\s+(\d{{4}}))?\b")
RE_TIME_AMPM = re.compile(r"\b(?:at\s+|by\s+)?(\d{1,2})(?:[:.](\d{2}))?\s*(am|pm|a\.m\.|p\.m\.)(?=\W|$)")
RE_TIME_24 = re.compile(r"\b(?:at\s+|by\s+)?([01]?\d|2[0-3]):([0-5]\d)\b")
RE_TIME_AT = re.compile(r"\b(?:at|by)\s+(\d{1,2})\b(?!\s*(?:%|[:.]\d|minutes?|mins?|hours?|days?|percent))")
RE_DAY_PART = re.compile(r"\b(?:at\s+|in the\s+|this\s+|by\s+)?(noon|midday|midnight|morning|afternoon|evening|tonight|night)\b")


def now_iso() -> str:
    """Current local time as stored in the database: '2026-10-24 17:05:00'."""
    return datetime.now().replace(microsecond=0).isoformat(sep=" ")


@dataclass
class When:
    dt: datetime
    has_time: bool  # False when only a date was given ("tomorrow")

    def describe(self, now: datetime | None = None) -> str:
        return describe(self.dt, self.has_time, now)


def _num(text: str) -> float:
    text = text.strip()
    try:
        return float(text)
    except ValueError:
        return float(NUMBER_WORDS.get(text, 1))


def parse_duration(text: str) -> int | None:
    """'10 minutes', '1h30m', '90 sec', 'an hour and a half' -> seconds."""
    t = text.lower().strip()
    if re.fullmatch(r"half\s+an?\s+hour", t):
        return 1800
    total = 0.0
    found = False
    for m in re.finditer(rf"{_NUM}\s*{_UNIT}(?![a-z])(\s+and\s+a\s+half)?", t):
        n = _num(m.group(1))
        if m.group(3):
            n += 0.5
        total += n * UNIT_SECONDS[m.group(2)]
        found = True
    if not found:
        m = re.fullmatch(r"(\d+):(\d{2})", t)  # mm:ss
        if m:
            return int(m.group(1)) * 60 + int(m.group(2))
        if re.fullmatch(r"\d+", t):  # bare number = minutes
            return int(t) * 60
        return None
    return int(total) if total > 0 else None


def _next_weekday(today: date, weekday: int, force_next_week: bool) -> date:
    days = (weekday - today.weekday()) % 7
    if days == 0 and force_next_week:
        days = 7
    return today + timedelta(days=days)


def find_when(text: str, now: datetime | None = None, default_time: time = time(9, 0)) -> tuple[When | None, str]:
    """Find a time phrase inside `text`.

    Returns (When or None, text with the time phrase removed).
    """
    now = now or datetime.now()
    lowered = text.lower()
    spans: list[tuple[int, int]] = []
    today = now.date()

    def done(day: date | None, found: tuple[time, str] | None, implied: time | None = None) -> tuple[When | None, str]:
        rest = _remove(text, spans)
        if found is None and implied is not None:
            found = (implied, "exact")
        if found is None:
            if day is None:
                return None, text
            return When(datetime.combine(day, default_time), False), rest
        tm, kind = found
        if kind == "ambiguous":
            return When(_pick_ambiguous(day, tm, now), True), rest
        if day is None:
            dt = datetime.combine(today, tm)
            if dt <= now:
                dt += timedelta(days=1)
            return When(dt, True), rest
        return When(datetime.combine(day, tm), True), rest

    m = RE_ISO.search(lowered)
    if m:
        try:
            day = date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            day = None
        if day:
            spans.append(m.span())
            if m.group(4):
                return When(datetime.combine(day, time(int(m.group(4)) % 24, int(m.group(5)))), True), _remove(text, spans)
            return done(day, _find_time(lowered, spans))

    m = RE_HALF_HOUR.search(lowered)
    if m:
        spans.append(m.span())
        return When((now + timedelta(minutes=30)).replace(microsecond=0), True), _remove(text, spans)
    m = RE_RELATIVE.search(lowered)
    if m:
        spans.append(m.span())
        n = _num(m.group(1))
        if m.group(0).endswith("and a half"):
            n += 0.5
        seconds = n * UNIT_SECONDS[m.group(2)]
        dt = (now + timedelta(seconds=seconds)).replace(microsecond=0)
        if seconds >= 86400:
            found = _find_time(lowered, spans)
            if found:
                return done(dt.date(), found)
        return When(dt, True), _remove(text, spans)

    day: date | None = None
    implied: time | None = None
    m = RE_REL_DAY.search(lowered)
    if m:
        spans.append(m.span())
        word = m.group(1)
        if word == "day after tomorrow":
            day = today + timedelta(days=2)
        elif word == "today":
            day = today
        elif word == "tonight":
            day, implied = today, DAY_PARTS["tonight"]
        else:
            day = today + timedelta(days=1)
    if day is None:
        m = RE_NEXT_WEEK.search(lowered)
        if m:
            spans.append(m.span())
            day = _next_weekday(today, 0, True) if m.group(1) == "next week" else _next_weekday(today, 5, False)
    if day is None:
        m = RE_WEEKDAY.search(lowered)
        if m:
            spans.append(m.span())
            day = _next_weekday(today, WEEKDAYS[m.group(2)], m.group(1) != "this")
    if day is None:
        for rx, d_idx, m_idx in ((RE_DAY_MONTH, 1, 2), (RE_MONTH_DAY, 2, 1)):
            m = rx.search(lowered)
            if not m:
                continue
            year = int(m.group(3)) if m.group(3) else today.year
            try:
                candidate = date(year, MONTHS[m.group(m_idx)], int(m.group(d_idx)))
            except ValueError:
                continue
            if not m.group(3) and candidate < today:
                candidate = candidate.replace(year=year + 1)
            spans.append(m.span())
            day = candidate
            break
    return done(day, _find_time(lowered, spans), implied)


def _pick_ambiguous(day: date | None, tm: time, now: datetime) -> datetime:
    """'at 6' without am/pm."""
    if day is not None:
        hour = tm.hour + 12 if 1 <= tm.hour <= 6 else tm.hour
        return datetime.combine(day, time(hour, tm.minute))
    today = now.date()
    options = [datetime.combine(today, tm)]
    if tm.hour < 12:
        options.append(datetime.combine(today, time(tm.hour + 12, tm.minute)))
    options += [o + timedelta(days=1) for o in list(options)]
    return min(o for o in options if o > now)


def _find_time(lowered: str, spans: list[tuple[int, int]]) -> tuple[time, str] | None:
    def free(m: re.Match) -> bool:
        a, b = m.span()
        return all(b <= s or a >= e for s, e in spans)

    for m in RE_TIME_AMPM.finditer(lowered):
        if not free(m):
            continue
        hour, minute = int(m.group(1)), int(m.group(2) or 0)
        if not 1 <= hour <= 12 or minute > 59:
            continue
        pm = m.group(3).startswith("p")
        if hour == 12:
            hour = 12 if pm else 0
        elif pm:
            hour += 12
        spans.append(m.span())
        return time(hour, minute), "exact"
    for m in RE_TIME_24.finditer(lowered):
        if free(m):
            spans.append(m.span())
            return time(int(m.group(1)), int(m.group(2))), "exact"
    for m in RE_DAY_PART.finditer(lowered):
        if free(m):
            spans.append(m.span())
            return DAY_PARTS[m.group(1)], "exact"
    for m in RE_TIME_AT.finditer(lowered):
        if free(m) and int(m.group(1)) <= 23:
            spans.append(m.span())
            hour = int(m.group(1))
            return time(hour, 0), ("ambiguous" if hour <= 12 else "exact")
    return None


def _remove(text: str, spans: list[tuple[int, int]]) -> str:
    out = text
    for a, b in sorted(spans, reverse=True):
        out = out[:a] + " " + out[b:]
    out = " ".join(out.split())
    out = re.sub(r"\s+([,.!?])", r"\1", out)
    out = re.sub(r"(?:\s+|^)(?:at|on|by|in|for)$", "", out, flags=re.I).strip()
    return out.strip(" ,")


def parse_when(text: str, now: datetime | None = None, default_time: time = time(9, 0)) -> When | None:
    """Parse a phrase that is only a time ("tomorrow 5pm"). Also accepts ISO strings."""
    now = now or datetime.now()
    text = (text or "").strip()
    if not text:
        return None
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return find_when(text, now, default_time)[0]
    has_time = bool(re.search(r"\d[T ]\d", text))
    if not has_time:
        dt = datetime.combine(dt.date(), default_time)
    return When(dt.replace(tzinfo=None, microsecond=0), has_time)


def describe(dt: datetime, has_time: bool = True, now: datetime | None = None) -> str:
    """Friendly text: 'today 5:00 PM', 'tomorrow', 'Fri 25 Oct 9:00 AM'."""
    now = now or datetime.now()
    days = (dt.date() - now.date()).days
    if days == 0:
        day = "today"
    elif days == 1:
        day = "tomorrow"
    elif days == -1:
        day = "yesterday"
    elif 1 < days < 7:
        day = dt.strftime("%A")
    else:
        day = f"{dt.strftime('%a')} {dt.day} {dt.strftime('%b')}"
        if dt.year != now.year:
            day += f" {dt.year}"
    if not has_time:
        return day
    clock = dt.strftime("%I:%M %p").lstrip("0")
    return f"{day} {clock}"
