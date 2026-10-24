"""Calendar: your Google/Outlook calendar (via its private iCal link, read-only) plus local events."""

from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any, Callable

from winauto.core.skill import QuickRule, Risk, Skill, ToolResult, fail, ok, tool
from winauto.core.timeparse import describe, parse_when
from winauto.net import FetchError, fetch
from winauto.storage.db import now_iso

log = logging.getLogger(__name__)
WEEKDAY_CODES = ["MO", "TU", "WE", "TH", "FR", "SA", "SU"]


@dataclass
class Event:
    title: str
    start: datetime  # local, naive
    end: datetime
    all_day: bool = False
    location: str = ""
    source: str = "calendar"


# ---------------- iCal parsing ----------------

def _unfold(text: str) -> list[str]:
    lines: list[str] = []
    for raw in text.replace("\r\n", "\n").split("\n"):
        if raw.startswith((" ", "\t")) and lines:
            lines[-1] += raw[1:]
        else:
            lines.append(raw)
    return lines


def _unescape(value: str) -> str:
    return value.replace("\\n", "\n").replace("\\N", "\n").replace("\\,", ",").replace("\\;", ";").replace("\\\\", "\\")


def _parse_dt(params: dict[str, str], value: str) -> tuple[datetime, bool]:
    value = value.strip()
    if params.get("VALUE") == "DATE" or re.fullmatch(r"\d{8}", value):
        return datetime.strptime(value[:8], "%Y%m%d"), True
    dt = datetime.strptime(value[:15], "%Y%m%dT%H%M%S")
    if value.endswith("Z"):
        return dt.replace(tzinfo=timezone.utc).astimezone().replace(tzinfo=None), False
    tzid = params.get("TZID")
    if tzid:
        try:
            from zoneinfo import ZoneInfo

            return dt.replace(tzinfo=ZoneInfo(tzid)).astimezone().replace(tzinfo=None), False
        except Exception:
            pass
    return dt, False


def parse_ics(text: str, window_start: datetime, window_end: datetime) -> list[Event]:
    """Events overlapping [window_start, window_end), with simple repeating rules expanded."""
    events: list[Event] = []
    current: dict[str, Any] | None = None
    for line in _unfold(text):
        if line == "BEGIN:VEVENT":
            current = {"exdates": set()}
            continue
        if line == "END:VEVENT" and current is not None:
            events += _expand(current, window_start, window_end)
            current = None
            continue
        if current is None or ":" not in line:
            continue
        head, value = line.split(":", 1)
        name, *param_parts = head.split(";")
        params = dict(p.split("=", 1) for p in param_parts if "=" in p)
        name = name.upper()
        try:
            if name == "SUMMARY":
                current["title"] = _unescape(value)
            elif name == "LOCATION":
                current["location"] = _unescape(value)
            elif name == "DTSTART":
                current["start"], current["all_day"] = _parse_dt(params, value)
            elif name == "DTEND":
                current["end"], _ = _parse_dt(params, value)
            elif name == "DURATION":
                current["duration"] = _parse_duration(value)
            elif name == "RRULE":
                current["rrule"] = dict(p.split("=", 1) for p in value.split(";") if "=" in p)
            elif name == "EXDATE":
                for v in value.split(","):
                    current["exdates"].add(_parse_dt(params, v)[0])
            elif name == "STATUS" and value.upper() == "CANCELLED":
                current["cancelled"] = True
        except ValueError:
            log.debug("bad calendar line %r", line)
    events.sort(key=lambda e: e.start)
    return events


def _parse_duration(value: str) -> timedelta:
    m = re.fullmatch(r"P(?:(\d+)W)?(?:(\d+)D)?(?:T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?)?", value.strip())
    if not m:
        return timedelta(hours=1)
    w, d, h, mi, s = (int(x or 0) for x in m.groups())
    return timedelta(weeks=w, days=d, hours=h, minutes=mi, seconds=s)


def _expand(ev: dict[str, Any], window_start: datetime, window_end: datetime) -> list[Event]:
    if "start" not in ev or ev.get("cancelled"):
        return []
    start: datetime = ev["start"]
    length = (ev["end"] - start) if "end" in ev else ev.get("duration", timedelta(days=1) if ev.get("all_day") else timedelta(hours=1))
    make = lambda s: Event(ev.get("title", "(no title)"), s, s + length, ev.get("all_day", False), ev.get("location", ""))  # noqa: E731
    rule = ev.get("rrule")
    if not rule:
        return [make(start)] if start < window_end and start + length > window_start else []
    freq = rule.get("FREQ", "")
    interval = int(rule.get("INTERVAL", "1") or 1)
    count = int(rule["COUNT"]) if "COUNT" in rule else None
    until = _parse_dt({}, rule["UNTIL"])[0] if "UNTIL" in rule else None
    by_day = [d[-2:] for d in rule.get("BYDAY", "").split(",") if d] if freq == "WEEKLY" else []
    out, n, cursor = [], 0, start
    for _ in range(5000):
        candidates = [cursor]
        if by_day:
            week_start = cursor - timedelta(days=cursor.weekday())
            candidates = sorted(week_start + timedelta(days=WEEKDAY_CODES.index(d)) for d in by_day if d in WEEKDAY_CODES)
            candidates = [c.replace(hour=start.hour, minute=start.minute, second=start.second) for c in candidates if c >= start.replace(hour=0, minute=0, second=0)]
        for occ in candidates:
            if occ < start:
                continue
            if until and occ > until:
                return out
            n += 1
            if count is not None and n > count:
                return out
            if occ not in ev["exdates"] and occ < window_end and occ + length > window_start:
                out.append(make(occ))
        if cursor > window_end:
            break
        if freq == "DAILY":
            cursor += timedelta(days=interval)
        elif freq == "WEEKLY":
            cursor += timedelta(weeks=interval)
        elif freq == "MONTHLY":
            month = cursor.month - 1 + interval
            year = cursor.year + month // 12
            try:
                cursor = cursor.replace(year=year, month=month % 12 + 1)
            except ValueError:
                cursor = cursor.replace(year=year, month=month % 12 + 1, day=28)
        elif freq == "YEARLY":
            try:
                cursor = cursor.replace(year=cursor.year + interval)
            except ValueError:
                cursor = cursor.replace(year=cursor.year + interval, day=28)
        else:
            break
    return out


# ---------------- skill ----------------

class CalendarSkill(Skill):
    name = "calendar"
    description = "Your agenda: synced calendars (read-only) and local events."
    keywords = r"\b(calendar|agenda|schedule|meetings?|events?|appointments?|busy|free time|what's on|plans)\b"
    prompt_hint = "Calendar: get_agenda shows events for a day; add_event saves a local event (with a reminder)."

    def __init__(self, ctx: Any, fetcher: Callable[..., tuple[str, str]] | None = None,
                 clock: Callable[[], datetime] = datetime.now):
        super().__init__(ctx)
        self._fetch = fetcher or fetch
        self.clock = clock
        self._cache: dict[str, tuple[float, str]] = {}

    def _feeds(self) -> list[str]:
        out = []
        for url in self.ctx.config.calendar_urls:
            url = url.strip()
            if url.startswith("webcal://"):
                url = "https://" + url[len("webcal://"):]
            if url:
                out.append(url)
        return out

    def events_between(self, start: datetime, end: datetime) -> tuple[list[Event], list[str]]:
        events: list[Event] = []
        problems: list[str] = []
        for url in self._feeds():
            cached = self._cache.get(url)
            if cached and time.time() - cached[0] < 600:
                text = cached[1]
            else:
                try:
                    text, _ = self._fetch(url, timeout=15, max_bytes=8_000_000)
                    self._cache[url] = (time.time(), text)
                except FetchError as exc:
                    problems.append(str(exc))
                    continue
            events += parse_ics(text, start, end)
        for row in self.ctx.db.query("SELECT * FROM events WHERE start_at < ? AND end_at > ? ORDER BY start_at",
                                     (end.isoformat(sep=" "), start.isoformat(sep=" "))):
            events.append(Event(row["title"], datetime.fromisoformat(row["start_at"]), datetime.fromisoformat(row["end_at"]),
                                bool(row["all_day"]), row["location"], "local"))
        events.sort(key=lambda e: (not e.all_day, e.start))
        return events, problems

    def _day(self, day: str) -> date | None:
        now = self.clock()
        d = day.strip().lower()
        if d in ("", "today", "now"):
            return now.date()
        if d == "tomorrow":
            return now.date() + timedelta(days=1)
        when = parse_when(d, now)
        return when.dt.date() if when else None

    @staticmethod
    def format_event(e: Event) -> str:
        if e.all_day:
            when = "All day"
        else:
            when = f"{e.start.strftime('%I:%M %p').lstrip('0')}–{e.end.strftime('%I:%M %p').lstrip('0')}"
        where = f" · {e.location}" if e.location else ""
        return f"- **{when}** {e.title}{where}"

    @tool("Show events for a day.", params={"day": "today, tomorrow, a weekday or a date (default today)"})
    def get_agenda(self, day: str = "today") -> ToolResult:
        target = self._day(day)
        if target is None:
            return fail(f"I didn't understand the day “{day}”.")
        start = datetime.combine(target, datetime.min.time())
        events, problems = self.events_between(start, start + timedelta(days=1))
        label = describe(start, False, self.clock()).capitalize()
        note = f"\n(Couldn't load a calendar: {problems[0]})" if problems else ""
        if not self._feeds() and not events:
            return ok(f"Nothing on {label.lower()}. To see your Google or Outlook calendar, paste its private iCal link "
                      "in Settings → Accounts." + note)
        if not events:
            return ok(f"{label}: nothing scheduled. 🎉{note}")
        return ok(f"{label}:\n" + "\n".join(self.format_event(e) for e in events) + note,
                  data={"events": [e.title for e in events]})

    @tool("What's the next event coming up.")
    def next_event(self) -> ToolResult:
        now = self.clock()
        events, _ = self.events_between(now, now + timedelta(days=14))
        upcoming = [e for e in events if e.start >= now and not e.all_day] or [e for e in events if e.start >= now]
        if not upcoming:
            return ok("Nothing in the next two weeks.")
        e = upcoming[0]
        mins = int((e.start - now).total_seconds() // 60)
        soon = f" (in {mins} min)" if mins < 120 else ""
        return ok(f"Next: **{e.title}** {describe(e.start, not e.all_day, now)}{soon}" + (f" · {e.location}" if e.location else ""))

    @tool("Add an event to the local calendar, with a reminder 10 minutes before.",
          params={"title": "What it is", "when": "Start, e.g. 'friday 3pm'", "duration_minutes": "Length (default 60)",
                  "remind": "Add a reminder (default true)"})
    def add_event(self, title: str, when: str, duration_minutes: int = 60, remind: bool = True) -> ToolResult:
        parsed = parse_when(when, self.clock())
        if parsed is None:
            return fail(f"I didn't understand when “{when}” is.")
        start = parsed.dt
        all_day = not parsed.has_time
        end = start + (timedelta(days=1) if all_day else timedelta(minutes=max(5, duration_minutes)))
        if all_day:
            start = datetime.combine(start.date(), datetime.min.time())
            end = start + timedelta(days=1)
        eid = self.ctx.db.execute(
            "INSERT INTO events(title, start_at, end_at, all_day, created_at) VALUES(?, ?, ?, ?, ?)",
            (title.strip(), start.isoformat(sep=" "), end.isoformat(sep=" "), int(all_day), now_iso()))
        reminder = ""
        reminders = self.ctx.services.get("skills", {}).get("reminders")
        if remind and not all_day and reminders and start - timedelta(minutes=10) > self.clock():
            reminders.set_reminder(f"{title.strip()} in 10 minutes", (start - timedelta(minutes=10)).isoformat(sep=" "))
            reminder = " I'll remind you 10 minutes before."
        return ok(f"Added **{title.strip()}** {describe(start, not all_day, self.clock())}.{reminder}", data={"id": eid})

    @tool("Delete a local calendar event.", params={"title": "Words from the event's title"},
          risk=Risk.CONFIRM, confirm_label="Delete")
    def delete_event(self, title: str) -> ToolResult:
        rows = self.ctx.db.query("SELECT * FROM events WHERE lower(title) LIKE ? ORDER BY start_at", (f"%{title.lower()}%",))
        if not rows:
            return fail(f"No local event matching “{title}”. (Synced calendars can only be changed in their own app.)")
        self.ctx.db.execute("DELETE FROM events WHERE id = ?", (rows[0]["id"],))
        return ok(f"Deleted {rows[0]['title']}.")

    def quick_rules(self) -> list[QuickRule]:
        day = r"(?:\s+(?:for\s+|on\s+)?(?P<d>today|tomorrow|monday|tuesday|wednesday|thursday|friday|saturday|sunday))?"
        return [
            QuickRule(r"(?:what(?:'s| is)\s+on\s+)?(?:my\s+)?(?:calendar|agenda|schedule)" + day,
                      lambda m: ("get_agenda", {"day": m["d"] or "today"})),
            QuickRule(r"what(?:'s| is)\s+on\s+(?:for\s+)?(?P<d>today|tomorrow)|(?:do\s+i\s+have\s+)?(?:any\s+)?(?:meetings|events)" + day.replace("?P<d>", "?P<d2>"),
                      lambda m: ("get_agenda", {"day": m["d"] or m["d2"] or "today"})),
            QuickRule(r"(?:what(?:'s| is)\s+)?(?:my\s+)?next\s+(?:meeting|event|appointment)", lambda m: ("next_event", {})),
            QuickRule(r"(?:add|schedule|create|put)\s+(?:an?\s+)?(?:event|meeting|appointment)?\s*(?P<t>.+?)\s+"
                      r"(?P<w>(?:on|at|tomorrow|today|next|this)\b.+)\s+(?:to|in|on)\s+(?:my\s+)?calendar",
                      lambda m: ("add_event", {"title": m["t"], "when": m["w"]})),
        ]
