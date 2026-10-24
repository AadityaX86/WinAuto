"""Example skill from docs/adding-a-skill.md: count glasses of water.

tests/test_docs.py runs this file, so the guide's code always works.
To try it in the app, copy it to winauto/skills/water.py and add
("water", "WaterSkill") to BUILTIN in winauto/skills/__init__.py.
"""

from __future__ import annotations

from datetime import date
from typing import Callable

from winauto.core.context import Context
from winauto.core.skill import QuickRule, Risk, Skill, Suggestion, ToolResult, Widget, fail, ok, tool


class WaterSkill(Skill):
    name = "water"
    icon = "target"
    description = "Count glasses of water drunk today."
    # Requests matching this are offered this skill's tools.
    keywords = r"\b(water|glass(?:es)?|hydrat\w*|drink)\b"
    prompt_hint = "Water: log_water adds glasses; water_today says how many so far."

    GOAL = 8

    def __init__(self, ctx: Context, today: Callable[[], date] = date.today):
        super().__init__(ctx)
        self.today = today  # injected so tests can pick the day

    def _key(self) -> str:
        return f"water:{self.today().isoformat()}"

    def count(self) -> int:
        return int(self.ctx.db.get_value(self._key()) or 0)

    # ----- tools: the model sees the name, docstring-like description and parameters -----

    @tool("Log glasses of water the user drank.", params={"glasses": "How many (default 1)"})
    def log_water(self, glasses: int = 1) -> ToolResult:
        if not 1 <= glasses <= 10:
            return fail("Log between 1 and 10 glasses at a time.")
        total = self.count() + glasses
        self.ctx.db.set_value(self._key(), str(total))
        return ok(f"💧 {total} of {self.GOAL} glasses today.", data={"today": total})

    @tool("How many glasses of water the user has had today.")
    def water_today(self) -> ToolResult:
        n = self.count()
        left = max(self.GOAL - n, 0)
        return ok(f"💧 {n} glasses today" + (f", {left} to go." if left else ". Goal reached!"))

    @tool("Reset today's water count to zero.", risk=Risk.CONFIRM, confirm_label="Reset")
    def reset_water(self) -> ToolResult:
        self.ctx.db.set_value(self._key(), "0")
        return ok("Water count reset.")

    # ----- optional hooks -----

    def quick_rules(self) -> list[QuickRule]:
        """Instant commands that skip the AI. The pattern must match the whole command."""
        return [
            QuickRule(r"(?:drank|had|log)\s+(?P<n>\d+)?\s*(?:glass(?:es)?\s+of\s+)?water",
                      lambda m: ("log_water", {"glasses": int(m["n"] or 1)})),
            QuickRule(r"how\s+much\s+water(?:\s+today)?", lambda m: ("water_today", {})),
        ]

    def suggest(self, query: str) -> list[Suggestion]:
        """Launcher results while typing. Must be fast: no network, no slow disk work."""
        if "water".startswith(query.strip().lower()) and len(query.strip()) >= 2:
            return [Suggestion("Log a glass of water", "log_water", {"glasses": 1},
                               subtitle=f"{self.count()} so far today", kind="Command", score=80)]
        return []

    def widgets(self) -> list[Widget]:
        """A card on the home screen."""
        n = self.count()
        return [Widget(self.icon, f"{n}/{self.GOAL} glasses", order=60)] if n else []
