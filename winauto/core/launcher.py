"""Live results while typing, collected from every skill (like Raycast / PowerToys Run)."""

from __future__ import annotations

import logging
import time
from typing import Any

from winauto.core.quick import QuickMatcher, clean_command
from winauto.core.registry import Registry
from winauto.core.skill import Suggestion

log = logging.getLogger(__name__)

ASK_TOOL = "__ask__"  # not a real tool: send the text to the assistant
MAX_RESULTS = 8

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
        if call is not None:
            tool = self.registry.get(call.name)
            owner = self.registry.skill(tool.skill) if tool else None
            label = call.name.replace("_", " ")
            results.append(Suggestion(
                title=clean_command(text, keep_punctuation=True)[:1].upper() + clean_command(text, keep_punctuation=True)[1:],
                subtitle=f"Run · {label}", tool=call.name, args=call.arguments, kind="Command",
                icon=owner.icon if owner else "zap", score=92,
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
