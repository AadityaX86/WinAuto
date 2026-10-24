"""Live results while typing, collected from every skill (like Raycast / PowerToys Run)."""

from __future__ import annotations

import logging
import re
import time
from dataclasses import replace
from datetime import datetime
from typing import Any

from winauto.core.quick import QuickMatcher
from winauto.core.registry import Registry
from winauto.core.skill import Risk, Suggestion, Tool
from winauto.core.timeparse import describe

log = logging.getLogger(__name__)

ASK_TOOL = "__ask__"  # not a real tool: send the text to the assistant
FILL_TOOL = "__fill__"  # not a real tool: put args["text"] in the search box so the user can finish it
MAX_RESULTS = 8


def template(title: str, fill: str, hint: str, icon: str = "", score: float = 84) -> Suggestion:
    """A result that starts a command for the user, e.g. "Remind me to …" → types "remind me to "."""
    return Suggestion(title=title, subtitle=hint, tool=FILL_TOOL, args={"text": fill}, kind="Fill in",
                      icon=icon, score=score)


def starts(query: str, *phrases: str) -> bool:
    """True when the user is typing the start of one of these phrases ("rem" → "remind me to")."""
    q = " ".join(query.lower().split())
    return any(p == q or (len(q) >= 3 and p.startswith(q)) for p in phrases)


def _shown(value: Any) -> str:
    if isinstance(value, bool):
        return "on" if value else "off"
    if isinstance(value, (int, float)):
        return f"{value:g}"
    if not isinstance(value, str) or value.strip().lower() in ("", "none", "default"):
        return ""
    text = value.strip()
    if re.match(r"\d{4}-\d{2}-\d{2}", text):
        try:
            return describe(datetime.fromisoformat(text), has_time=len(text) > 10)
        except ValueError:
            pass
    return text


class _Blank(dict):
    def __missing__(self, key: str) -> str:
        return ""


def command_title(tool_name: str, args: dict[str, Any], tool: Tool | None = None) -> str:
    """What will happen, not what was typed: 'open_app', {'name': 'notepad'} → 'Open notepad'.

    Uses the tool's own `title` when it has one, else 'Add todo: milk' from the tool's name.
    """
    defaults = {p.name: p.default for p in tool.params if not p.required} if tool else {}
    # "List todos", not "List todos: open"
    given = {k: v for k, v in args.items() if not (k in defaults and v == defaults[k])}
    spec = tool.title if tool else ""
    if callable(spec):
        try:
            title = spec({**defaults, **args})
        except Exception:  # a title must never break the launcher
            log.exception("title() failed for %s", tool_name)
            spec = ""
    elif spec:
        title = spec.format_map(_Blank({k: _shown(v) for k, v in given.items()}))
        title = re.sub(r"\s*“”", "", title)
    if not spec:
        title = tool_name.replace("_", " ").capitalize()
        bits = [b for b in map(_shown, given.values()) if b]
        if bits:
            title += ": " + ", ".join(bits[:2])
    title = re.sub(r"\s+", " ", title).strip().rstrip(":,·- ")
    return title if len(title) <= 70 else title[:69] + "…"


def ask_suggestion(text: str, score: float) -> Suggestion:
    return Suggestion(title=text, subtitle="Ask WinAuto", tool=ASK_TOOL, args={"text": text},
                      kind="Ask AI", icon="sparkles", score=score)


class Launcher:
    def __init__(self, registry: Registry, quick: QuickMatcher):
        self.registry = registry
        self.quick = quick

    def search(self, query: str, limit: int = MAX_RESULTS) -> list[Suggestion]:
        text = query.strip()
        if not text:
            return []
        results: list[Suggestion] = []
        for skill in self.registry.skills:
            started = time.perf_counter()
            try:
                found = skill.suggest(text)
            except Exception:
                log.exception("suggest() failed in %s", skill.name)
                continue
            took = (time.perf_counter() - started) * 1000
            if took > 50:
                log.debug("suggest() in %s took %.0f ms", skill.name, took)
            for s in found:
                if not s.icon:
                    s.icon = skill.icon
            results += found

        call = self.quick.match(text)
        covered = False
        if call is not None:
            # A result that does exactly the instant command moves up; others make the command row redundant.
            same = (call.name, _freeze(call.arguments))
            results = [replace(r, score=max(r.score, 92)) if (r.tool, _freeze(r.args)) == same else r for r in results]
            covered = any((r.tool, _freeze(r.args)) == same or (r.tool == call.name and r.score >= 80) or r.score >= 95
                          for r in results)
        if call is not None and not covered:
            tool = self.registry.get(call.name)
            owner = self.registry.skill(tool.skill) if tool else None
            asks = tool is not None and tool.risk is Risk.CONFIRM
            results.append(Suggestion(
                title=command_title(call.name, call.arguments, tool),
                subtitle="Asks you first" if asks else "Runs instantly", tool=call.name, args=call.arguments,
                kind="Command", icon=owner.icon if owner else "zap", score=92,
            ))

        # Longer sentences are probably meant for the assistant; short words for a launcher result.
        words = len(text.split())
        strong = any(r.score >= 90 for r in results)
        ask_score = 96 if (words >= 3 and not strong) else (60 if words >= 3 else 20)
        results.append(ask_suggestion(text, ask_score))

        # Keep the best of each (tool, args) pair.
        seen: dict[tuple, Suggestion] = {}
        for r in results:
            key = (r.tool, _freeze(r.args))
            if key not in seen or r.score > seen[key].score:
                seen[key] = r
        ordered = sorted(seen.values(), key=lambda r: -r.score)
        return ordered[:limit]


def _freeze(value: Any) -> Any:
    if isinstance(value, dict):
        return tuple(sorted((k, _freeze(v)) for k, v in value.items()))
    if isinstance(value, list):
        return tuple(_freeze(v) for v in value)
    return value
