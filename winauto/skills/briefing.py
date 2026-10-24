"""Daily briefing: weather, calendar, todos, reminders, unread email and headlines in one go."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Callable

from winauto.core.context import Context
from winauto.core.skill import QuickRule, Skill, ToolResult, ok, tool

log = logging.getLogger(__name__)


class BriefingSkill(Skill):
    name = "briefing"
    icon = "sun"
    description = "Daily briefing."
    keywords = r"\b(briefing|brief me|good morning|my day|today look|morning)\b"

    def __init__(self, ctx: Context, clock: Callable[[], datetime] = datetime.now):
        super().__init__(ctx)
        self.clock = clock

    def _skill(self, name: str):
        return self.ctx.skill(name)

    def _section(self, title: str, fn: Callable[[], Any]) -> str | None:
        try:
            result = fn()
        except Exception:
            log.exception("briefing section %s failed", title)
            return None
        if result is None or not getattr(result, "ok", False):
            return None
        body = result.message.split("\n", 1)
        text = body[1] if len(body) > 1 and body[0].endswith(":") else result.message
        return f"**{title}**\n{text}"

    @tool("A briefing for today: weather, calendar, todos, reminders, unread email and top news.",
          params={"include_news": "Add top headlines (default true)"})
    def daily_briefing(self, include_news: bool = True) -> ToolResult:
        now = self.clock()
        part = "morning" if now.hour < 12 else "afternoon" if now.hour < 17 else "evening"
        name = self.ctx.config.user_name.split()[0] if self.ctx.config.user_name else ""
        lines = [f"### Good {part}{', ' + name if name else ''}!", now.strftime("%A, %d %B")]

        web = self._skill("web")
        if web:
            weather = self._section("Weather", lambda: web.get_weather(""))
            if weather:
                lines.append(weather)
        calendar = self._skill("calendar")
        if calendar:
            agenda = self._section("Calendar", lambda: calendar.get_agenda("today"))
            if agenda:
                lines.append(agenda)
        notes = self._skill("notes")
        if notes:
            todos = self._section("Due today", lambda: notes.list_todos("today"))
            if todos and "Nothing due today" not in todos:
                lines.append(todos)
            overdue = self._section("Overdue", lambda: notes.list_todos("overdue"))
            if overdue and "Nothing overdue" not in overdue:
                lines.append(overdue)
        reminders = self._skill("reminders")
        if reminders:
            end = datetime.combine(now.date(), datetime.max.time())
            rows = self.ctx.db.query("SELECT * FROM reminders WHERE active = 1 AND kind = 'reminder' AND due_at <= ? ORDER BY due_at",
                                     (end.isoformat(sep=" "),))
            if rows:
                items = "\n".join(f"- {datetime.fromisoformat(r['due_at']).strftime('%I:%M %p').lstrip('0')} {r['text']}" for r in rows)
                lines.append(f"**Reminders today**\n{items}")
        email = self._skill("email")
        if email and self.ctx.config.email.address:
            try:
                r = email.check_email(unread_only=True, limit=5)
                if r.ok and r.data and r.data.get("emails"):
                    n = len(r.data["emails"])
                    lines.append(f"**Email**\n{n}{'+' if n == 5 else ''} unread. Say “check my email” to see them.")
            except Exception:
                log.debug("briefing email failed", exc_info=True)
        info = self._skill("info")
        if include_news and info:
            news = self._section("Headlines", lambda: info.get_news("", 3))
            if news:
                lines.append(news)
        if len(lines) == 2:
            lines.append("Nothing scheduled and nothing due. Enjoy your day!")
        self.ctx.db.set_value("last_briefing", now.date().isoformat())
        return ok("\n\n".join(lines))

    def due_for_morning_briefing(self) -> bool:
        """True the first time WinAuto opens after 5am each day (if enabled)."""
        now = self.clock()
        if not self.ctx.config.morning_briefing or now.hour < 5 or now.hour >= 12:
            return False
        return self.ctx.db.get_value("last_briefing") != now.date().isoformat()

    def quick_rules(self) -> list[QuickRule]:
        return [
            QuickRule(r"(?:good\s+morning|(?:give\s+me\s+)?(?:my\s+|the\s+)?(?:daily\s+|morning\s+)?briefing|brief\s+me|"
                      r"what(?:'s| does)\s+my\s+day\s+look\s+like|how\s+does\s+my\s+day\s+look|plan\s+my\s+day)",
                      lambda m: ("daily_briefing", {})),
        ]
