"""Reminders and timers, with Windows notifications."""

from __future__ import annotations

import calendar
import logging
import re
import sys
import threading
from datetime import datetime, timedelta
from typing import Any, Callable, Literal

from winauto.core.context import Context
from winauto.core.launcher import starts, template
from winauto.core.matching import rank
from winauto.core.skill import QuickRule, Skill, Suggestion, ToolResult, Widget, fail, ok, tool
from winauto.core.timeparse import (
    describe,
    find_when,
    now_iso,
    parse_duration,
    parse_when,
)

log = logging.getLogger(__name__)

REPEATS = ("none", "daily", "weekdays", "weekly", "monthly")


def next_occurrence(due: datetime, repeat: str, now: datetime) -> datetime | None:
    """The next time a repeating reminder should fire after `now`."""
    if repeat not in REPEATS or repeat == "none":
        return None
    nxt = due
    for _ in range(4000):  # plenty for years of missed repeats
        if repeat == "daily":
            nxt += timedelta(days=1)
        elif repeat == "weekly":
            nxt += timedelta(days=7)
        elif repeat == "weekdays":
            nxt += timedelta(days=1)
            while nxt.weekday() >= 5:
                nxt += timedelta(days=1)
        elif repeat == "monthly":
            month = nxt.month % 12 + 1
            year = nxt.year + (1 if month == 1 else 0)
            day = min(due.day, calendar.monthrange(year, month)[1])
            nxt = nxt.replace(year=year, month=month, day=day)
        if nxt > now:
            return nxt
    return None


def _play_sound(kind: str) -> None:
    if sys.platform != "win32":
        return
    try:
        import winsound

        alias = "SystemExclamation" if kind == "timer" else "SystemAsterisk"
        winsound.PlaySound(alias, winsound.SND_ALIAS | winsound.SND_ASYNC)
    except Exception:
        log.debug("sound failed", exc_info=True)


class RemindersSkill(Skill):
    name = "reminders"
    icon = "bell"
    description = "Reminders and timers."
    keywords = r"\b(remind|reminders?|timers?|alarms?|wake me|countdown|in \d+ (?:min|minutes?|hours?|seconds?))\b"
    prompt_hint = "Reminders: pass 'when' in the user's own words, e.g. 'tomorrow 9am' or 'in 20 minutes'."

    def __init__(self, ctx: Context, clock: Callable[[], datetime] = datetime.now, sound: Callable[[str], None] = _play_sound):
        super().__init__(ctx)
        self.clock = clock
        self.sound = sound
        self._stop = threading.Event()
        self._wake = threading.Event()
        self._thread: threading.Thread | None = None

    @property
    def db(self):
        return self.ctx.db

    # ----- background checking -----

    def start(self) -> None:
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True, name="reminders")
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._wake.set()
        if self._thread:
            self._thread.join(2)

    def _loop(self) -> None:
        first = True
        while not self._stop.is_set():
            try:
                self.check_due(missed_label=first)
            except Exception:
                log.exception("reminder check failed")
            first = False
            self._wake.wait(self._seconds_until_next())
            self._wake.clear()

    def _seconds_until_next(self) -> float:
        row = self.db.one("SELECT due_at FROM reminders WHERE active = 1 ORDER BY due_at LIMIT 1")
        if not row:
            return 30.0
        wait = (datetime.fromisoformat(row["due_at"]) - self.clock()).total_seconds()
        return max(0.5, min(wait, 30.0))

    def check_due(self, missed_label: bool = False) -> list[dict[str, Any]]:
        """Fire everything that's due. Returns the fired rows (for tests)."""
        now = self.clock()
        rows = self.db.query(
            "SELECT * FROM reminders WHERE active = 1 AND due_at <= ? ORDER BY due_at",
            (now.isoformat(sep=" "),),
        )
        for row in rows:
            due = datetime.fromisoformat(row["due_at"])
            late = (now - due) > timedelta(minutes=2)
            if row["kind"] == "timer":
                title, body = "⏰ Time's up", row["text"]
            else:
                title = "Missed reminder" if late and missed_label else "Reminder"
                body = row["text"] + (f" (was due {describe(due, True, now)})" if late else "")
            self.ctx.notify(title, body)
            self.sound(row["kind"])
            nxt = next_occurrence(due, row["repeat"], now)
            if nxt:
                self.db.execute("UPDATE reminders SET due_at = ?, fired_at = ? WHERE id = ?",
                                (nxt.isoformat(sep=" "), now_iso(), row["id"]))
            else:
                self.db.execute("UPDATE reminders SET active = 0, fired_at = ? WHERE id = ?", (now_iso(), row["id"]))
        return rows

    def _insert(self, text: str, kind: str, due: datetime, repeat: str = "none") -> int:
        rid = self.db.execute(
            "INSERT INTO reminders(text, kind, due_at, repeat, created_at) VALUES(?, ?, ?, ?, ?)",
            (text, kind, due.replace(microsecond=0).isoformat(sep=" "), repeat, now_iso()),
        )
        self._wake.set()  # re-plan the wait
        return rid

    # ----- tools -----

    @tool(
        "Set a reminder that pops up as a notification.",
        params={"text": "What to remind about", "when": "When, in plain words: 'in 20 minutes', 'tomorrow 9am', 'friday 5pm'",
                "repeat": "none, daily, weekdays, weekly or monthly"}, title="Remind me to {text} · {when}")
    def set_reminder(self, text: str, when: str, repeat: Literal["none", "daily", "weekdays", "weekly", "monthly"] = "none") -> ToolResult:
        now = self.clock()
        parsed = parse_when(when, now)
        if parsed is None:
            return fail(f"I didn't understand when '{when}' is. Try 'in 20 minutes' or 'tomorrow 9am'.")
        due = parsed.dt
        if due <= now:
            if repeat != "none":
                due = next_occurrence(due, repeat, now) or due
            else:
                return fail(f"{describe(due, parsed.has_time, now)} has already passed.")
        text = re.sub(r"^(?:to|that)\s+", "", text.strip(), flags=re.I).rstrip(".")
        rid = self._insert(text, "reminder", due, repeat)
        again = "" if repeat == "none" else f", repeating {repeat}"
        return ok(f"I'll remind you to {text} {describe(due, True, now)}{again}. (#{rid})")

    @tool("Start a countdown timer.", params={"duration": "e.g. '10 minutes', '1h30m', '90 seconds'",
                                               "label": "Optional name, e.g. 'pasta'"},
          title="Start a timer: {duration} · {label}")
    def set_timer(self, duration: str, label: str = "") -> ToolResult:
        seconds = parse_duration(duration)
        if not seconds:
            return fail(f"How long? I didn't understand '{duration}'.")
        if seconds > 7 * 86400:
            return fail("That's longer than a week; use a reminder instead.")
        now = self.clock()
        pretty = _pretty_duration(seconds)
        text = f"{label.strip().capitalize()} timer ({pretty}) is done." if label.strip() else f"Your {pretty} timer is done."
        rid = self._insert(text, "timer", now + timedelta(seconds=seconds))
        ends = (now + timedelta(seconds=seconds)).strftime("%I:%M %p").lstrip("0")
        return ok(f"Timer set for {pretty}{f' ({label.strip()})' if label.strip() else ''}. Ends at {ends}. (#{rid})")

    @tool("Show upcoming reminders and running timers.", title="Show reminders and timers")
    def list_reminders(self) -> ToolResult:
        now = self.clock()
        rows = self.db.query("SELECT * FROM reminders WHERE active = 1 ORDER BY due_at")
        if not rows:
            return ok("No reminders or timers set.")
        lines = []
        for r in rows:
            due = datetime.fromisoformat(r["due_at"])
            if r["kind"] == "timer":
                left = max(0, int((due - now).total_seconds()))
                lines.append(f"- #{r['id']} ⏱ {r['text'].replace(' is done.', '')}: {_pretty_duration(left)} left")
            else:
                again = f" (repeats {r['repeat']})" if r["repeat"] != "none" else ""
                lines.append(f"- #{r['id']} {r['text']} — {describe(due, True, now)}{again}")
        return ok("Coming up:\n" + "\n".join(lines))

    @tool("Cancel a reminder or timer.", params={"which": "Its number (e.g. 4) or some of its words, or 'timer' for the timer"},
          title=lambda a: "Cancel the timer" if a["which"] == "timer" else f"Cancel reminder: {a['which']}")
    def cancel_reminder(self, which: str) -> ToolResult:
        rows = self.db.query("SELECT * FROM reminders WHERE active = 1 ORDER BY due_at")
        if not rows:
            return fail("There's nothing to cancel.")
        ref = which.strip().lower()
        m = re.fullmatch(r"#?(\d+)", ref)
        target = None
        if m:
            target = next((r for r in rows if r["id"] == int(m.group(1))), None)
        elif ref in ("timer", "the timer", "my timer"):
            timers = [r for r in rows if r["kind"] == "timer"]
            target = timers[0] if len(timers) == 1 else None
            if len(timers) > 1:
                return fail("Which timer? " + ", ".join(f"#{t['id']}" for t in timers))
        else:
            texts = {r["text"]: r for r in rows}
            best = rank(which, texts.keys(), limit=1, cutoff=65)
            contains = [r for r in rows if ref in r["text"].lower()]
            target = contains[0] if len(contains) == 1 else (texts[best[0][0]] if best else None)
        if not target:
            return fail(f"I couldn't find a reminder matching '{which}'.", fallback=True)
        self.db.execute("UPDATE reminders SET active = 0 WHERE id = ?", (target["id"],))
        self._wake.set()
        return ok(f"Cancelled: {target['text']}")

    # ----- quick commands -----

    def widgets(self) -> list[Widget]:
        nxt = self.ctx.db.one("SELECT text, due_at FROM reminders WHERE active = 1 ORDER BY due_at LIMIT 1")
        if not nxt:
            return []
        when, now = datetime.fromisoformat(nxt["due_at"]), self.clock()
        stamp = when.strftime("%I:%M %p").lstrip("0") if when.date() == now.date() else when.strftime("%a %I:%M %p")
        return [Widget("bell", f"{nxt['text'][:28]} · {stamp}", order=20)]

    def suggest(self, query: str) -> list[Suggestion]:
        out: list[Suggestion] = []
        if starts(query, "remind me to", "reminder", "alarm"):
            out.append(template("Remind me to…", "remind me to ", "Type what and when, e.g. call mom at 6pm", "bell"))
        if starts(query, "timer", "set a timer", "countdown"):
            out.append(template("Set a timer…", "timer ", "Type how long, e.g. 10 minutes", "clock"))
        if starts(query, "reminders", "remind", "timers", "alarms", "reminder", "alarm"):
            out.append(Suggestion(title="Show my reminders", subtitle="Upcoming reminders and timers",
                                  tool="list_reminders", args={}, kind="Command", icon="bell", score=82))
        return out

    def quick_rules(self) -> list[QuickRule]:
        def remind(m):
            rest = m["rest"].strip()
            when, what = find_when(rest, self.clock())
            if not when or not what:
                return None  # the model will ask when / what
            repeat = "none"
            for word, value in (("every day", "daily"), ("daily", "daily"), ("every weekday", "weekdays"),
                                ("every week", "weekly"), ("weekly", "weekly"), ("every month", "monthly"), ("monthly", "monthly")):
                if word in what.lower():
                    repeat = value
                    what = re.sub(word, "", what, flags=re.I).strip()
            what = re.sub(r"^(?:to|that)\s+", "", what, flags=re.I)
            when_text = when.dt.isoformat(sep=" ", timespec="minutes")
            return "set_reminder", {"text": what, "when": when_text, "repeat": repeat}

        def timer(m):
            d = m["d"].strip()
            label = (m["label"] or "").strip()
            if label.lower() in ("a", "an", "the", "my", "new", "set"):
                label = ""
            return ("set_timer", {"duration": d, "label": label}) if parse_duration(d) else None

        return [
            QuickRule(r"remind\s+me\s+(?P<rest>.+)", remind),
            QuickRule(r"(?:set\s+(?:a\s+|an\s+)?)?(?:(?P<label>[a-z]+)\s+)?timer\s+(?:for\s+)?(?P<d>.+)", timer),
            QuickRule(r"(?:set\s+(?:a\s+)?)?(?P<d>[\d.]+\s*(?:s|sec|secs|seconds?|m|min|mins|minutes?|h|hr|hrs|hours?))\s+(?:(?P<label>[a-z]+)\s+)?timer", timer),
            QuickRule(r"(?:show|list|what are)\s+(?:my\s+)?(?:reminders|timers|alarms)", lambda m: ("list_reminders", {})),
            QuickRule(r"how\s+(?:much|long)\s+(?:time\s+)?(?:is\s+)?left(?:\s+on\s+(?:the|my)\s+timer)?", lambda m: ("list_reminders", {})),
            QuickRule(r"(?:cancel|stop|delete|remove)\s+(?:the\s+|my\s+)?(?:reminder|timer)(?:\s+(?:for\s+|about\s+|to\s+)?(?P<w>.+))?",
                      lambda m: ("cancel_reminder", {"which": m["w"] or "timer"})),
        ]


def _pretty_duration(seconds: int) -> str:
    seconds = int(seconds)
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    parts = []
    if h:
        parts.append(f"{h} hour{'s' if h != 1 else ''}")
    if m:
        parts.append(f"{m} minute{'s' if m != 1 else ''}")
    if s and not h:
        parts.append(f"{s} second{'s' if s != 1 else ''}")
    return " ".join(parts) or "0 seconds"
