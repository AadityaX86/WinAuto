"""What the home screen shows: suggestions, recent commands and today's cards."""

from __future__ import annotations

import logging

from winauto.core.context import Context
from winauto.core.launcher import ASK_TOOL
from winauto.core.registry import Registry
from winauto.core.skill import Suggestion, Widget
from winauto.services.history import CommandHistory

log = logging.getLogger(__name__)

WELCOMED_KEY = "welcomed"

# Shown when the search box is empty. Ones whose tool isn't loaded are left out.
HOME_SUGGESTIONS = [
    Suggestion("Daily briefing", "daily_briefing", {}, "Weather, calendar, todos and news", "Command", "sun"),
    Suggestion("What's on my screen?", "ask_about_screen", {"question": "What's on my screen? Give a short overview."},
               "The AI looks at your screen and explains it", "Command", "eye"),
    Suggestion("Show my todos", "list_todos", {}, "Open tasks", "Command", "check"),
    Suggestion("Start a 25-minute focus session", "start_focus", {"minutes": 25}, "Keeps distracting apps out of the way",
               "Command", "target"),
    Suggestion("Clipboard history", "clipboard_history", {}, "Recently copied text", "Command", "clipboard"),
    Suggestion("Check my email", "check_email", {}, "Unread in Gmail", "Command", "mail"),
]


class HomeService:
    def __init__(self, ctx: Context, registry: Registry):
        self.ctx = ctx
        self.registry = registry
        self.history = CommandHistory(ctx.db)

    @property
    def user_name(self) -> str:
        return self.ctx.config.user_name

    def suggestions(self) -> list[Suggestion]:
        available = {t.name for t in self.registry.tools}
        return [s for s in HOME_SUGGESTIONS if s.tool in available]

    def recent(self, limit: int = 5) -> list[Suggestion]:
        return [Suggestion(text, ASK_TOOL, {"text": text}, "", "", "history") for text in self.history.recent(limit)]

    def record(self, text: str) -> None:
        self.history.record(text)

    # ----- first run -----

    def welcome_due(self) -> bool:
        return self.ctx.db.get_value(WELCOMED_KEY) is None

    def dismiss_welcome(self) -> None:
        self.ctx.db.set_value(WELCOMED_KEY, "1")

    def widgets(self) -> list[Widget]:
        """Today's cards from every skill. May touch the network: call it off the UI thread."""
        found: list[Widget] = []
        for skill in self.registry.skills:
            try:
                found.extend(skill.widgets())
            except Exception:
                log.debug("home widgets from %s failed", skill.name, exc_info=True)
        return sorted(found, key=lambda w: w.order)

    def briefing_due(self) -> bool:
        briefing = self.ctx.skill("briefing")
        return bool(briefing and briefing.due_for_morning_briefing())
