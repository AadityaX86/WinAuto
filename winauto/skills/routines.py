"""Routines: one command that runs several ("work mode" -> open apps, set volume...)."""

from __future__ import annotations

import json
import logging
import re
import time
from typing import Any

from winauto.core.matching import normalize, rank
from winauto.core.skill import QuickRule, Risk, Skill, Suggestion, ToolResult, fail, ok, tool
from winauto.core.timeparse import parse_duration
from winauto.adapters.storage.db import now_iso

log = logging.getLogger(__name__)
WAIT_RE = re.compile(r"(?:wait|pause|sleep)\s+(?:for\s+)?(?P<d>.+)", re.I)


class RoutinesSkill(Skill):
    name = "routines"
    description = "Saved routines that run several commands."
    keywords = r"\b(routines?|mode|morning|evening|night|work|study|focus|gaming|start my day|shortcut|macro)\b"
    prompt_hint = (
        "Routines: create_routine saves a list of simple commands like 'open vs code', 'volume 20', "
        "'dark mode on', 'wait 2 seconds'. Each step must be a simple command WinAuto understands instantly."
    )

    @property
    def db(self):
        return self.ctx.db

    def _get(self, name: str) -> dict[str, Any] | None:
        rows = self.db.query("SELECT * FROM routines")
        exact = [r for r in rows if normalize(r["name"]) == normalize(name)]
        if exact:
            return exact[0]
        best = rank(name, [r["name"] for r in rows], limit=1, cutoff=85)
        return next((r for r in rows if best and r["name"] == best[0][0]), None)

    def _understood(self, step: str) -> bool:
        if WAIT_RE.fullmatch(step.strip()):
            return bool(parse_duration(WAIT_RE.fullmatch(step.strip())["d"]))
        match = self.ctx.services.get("quick_match")
        return bool(match and match(step))

    @tool(
        "Save a routine: a name and the simple commands it runs, in order.",
        params={"name": "e.g. 'work mode'", "steps": "Commands, e.g. ['open vs code', 'open slack', 'volume 20']"},
    )
    def create_routine(self, name: str, steps: list[str]) -> ToolResult:
        name = name.strip()
        steps = [s.strip() for s in steps if s and s.strip()]
        if not name or not steps:
            return fail("A routine needs a name and at least one step.")
        unknown = [s for s in steps if not self._understood(s)]
        if unknown:
            return fail("I can't run these steps on their own: " + "; ".join(f"“{s}”" for s in unknown)
                        + ". Use simple commands like 'open spotify', 'volume 30', 'dark mode on', 'wait 2 seconds'.")
        self.db.execute(
            "INSERT INTO routines(name, steps, created_at) VALUES(?, ?, ?) "
            "ON CONFLICT(name) DO UPDATE SET steps = excluded.steps",
            (name, json.dumps(steps), now_iso()),
        )
        return ok(f"Saved routine “{name}” ({len(steps)} steps). Say “{name}” to run it.")

    @tool("Run a saved routine.", params={"name": "The routine's name"})
    def run_routine(self, name: str) -> ToolResult:
        routine = self._get(name)
        if not routine:
            return fail(f"There's no routine called “{name}”.", fallback=True)
        match = self.ctx.services.get("quick_match")
        run = self.ctx.services.get("run_tool")
        if not (match and run):
            return fail("Routines aren't available right now.")
        done, problems = [], []
        for step in json.loads(routine["steps"]):
            wait = WAIT_RE.fullmatch(step)
            if wait:
                time.sleep(min(parse_duration(wait["d"]) or 0, 60))
                continue
            call = match(step)
            if call is None:
                problems.append(f"“{step}” (not understood)")
                continue
            if call.name == "run_routine":
                problems.append(f"“{step}” (routines can't run routines)")
                continue
            result = run(call)
            (done if result.ok else problems).append(step if result.ok else f"“{step}”: {result.message}")
        if problems:
            return ok(f"Ran “{routine['name']}”: {len(done)} step(s) worked. Problems: " + "; ".join(problems))
        return ok(f"Ran “{routine['name']}” ({len(done)} steps). ✓")

    @tool("List saved routines.")
    def list_routines(self) -> ToolResult:
        rows = self.db.query("SELECT * FROM routines ORDER BY name")
        if not rows:
            return ok("No routines yet. Try: create a routine called work mode that opens vs code, opens chrome and sets volume to 20")
        lines = [f"- **{r['name']}**: " + " → ".join(json.loads(r["steps"])) for r in rows]
        return ok("Routines:\n" + "\n".join(lines))

    @tool("Delete a routine.", params={"name": "The routine's name"}, risk=Risk.CONFIRM, confirm_label="Delete")
    def delete_routine(self, name: str) -> ToolResult:
        routine = self._get(name)
        if not routine:
            return fail(f"There's no routine called “{name}”.")
        self.db.execute("DELETE FROM routines WHERE name = ?", (routine["name"],))
        return ok(f"Deleted routine “{routine['name']}”.")

    def suggest(self, query: str) -> list[Suggestion]:
        q = normalize(re.sub(r"^(?:run|start)\s+", "", query.strip(), flags=re.I))
        if len(q) < 2:
            return []
        out = []
        for r in self.db.query("SELECT name, steps FROM routines"):
            n = normalize(r["name"])
            if n.startswith(q) or q in n:
                steps = json.loads(r["steps"])
                out.append(Suggestion(title=r["name"], subtitle=" → ".join(steps)[:90], tool="run_routine",
                                      args={"name": r["name"]}, kind="Routine", icon="zap", score=94 if n == q else 84))
        return out

    def quick_rules(self) -> list[QuickRule]:
        def by_name(m):
            for text in (m.string, m["n"]):
                routine = self._get(text.strip())
                if routine and normalize(routine["name"]) == normalize(text):
                    return "run_routine", {"name": routine["name"]}
            return None

        def run_named(m):
            routine = self._get(m["n"])
            return ("run_routine", {"name": routine["name"]}) if routine else None

        return [
            # A routine's own name runs it: "work mode", "start my day".
            QuickRule(r"(?:start\s+|activate\s+|enable\s+|go\s+)?(?P<n>.+)", by_name, priority=20),
            QuickRule(r"(?:run|start|do|launch)\s+(?:the\s+|my\s+)?(?P<n>.+?)(?:\s+routine)?", run_named, priority=25),
            QuickRule(r"(?:show|list)\s+(?:my\s+)?routines", lambda m: ("list_routines", {})),
        ]
