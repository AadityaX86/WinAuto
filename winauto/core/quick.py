"""Quick commands: common, clear requests handled instantly without the AI.

"open spotify", "volume 30", "todo buy milk" run in milliseconds and work
even when the model isn't running. Anything that doesn't clearly match goes
to the AI.
"""

from __future__ import annotations

import logging
import re

from winauto.core.llm import ToolCall
from winauto.core.registry import Registry

log = logging.getLogger(__name__)

_FILLER_START = re.compile(
    r"^(?:(?:hey|hi|ok|okay)\s+)?(?:win\s?auto[,:]?\s+)?"
    r"(?:(?:please|pls|plz|kindly)\s+)?"
    r"(?:(?:can|could|would|will)\s+(?:you|u)\s+(?:please\s+)?)?"
    r"(?:(?:please|pls|plz)\s+)?",
    re.I,
)
_FILLER_END = re.compile(r"(?:\s*,?\s*(?:please|pls|plz|for me|thanks|thank you))+$", re.I)


def clean_command(text: str) -> str:
    text = " ".join((text or "").split())
    text = _FILLER_START.sub("", text)
    text = text.rstrip(" .!?")
    text = _FILLER_END.sub("", text)
    return text.strip()


def is_simple(target: str, max_words: int = 5) -> bool:
    """True for short targets with no chaining ("spotify", not "spotify and play x")."""
    t = target.lower()
    if re.search(r"\b(and|then|after|before|but|also|while)\b|[,;]", t):
        return False
    return 0 < len(t.split()) <= max_words


class QuickMatcher:
    def __init__(self, registry: Registry):
        self.registry = registry

    def match(self, text: str) -> ToolCall | None:
        cleaned = clean_command(text)
        if not cleaned or len(cleaned) > 120:
            return None
        for skill in self.registry.skills:
            for rule in skill.quick_rules():
                m = re.fullmatch(rule.pattern, cleaned, re.I)
                if not m:
                    continue
                try:
                    found = rule.handler(m)
                except Exception:
                    log.exception("quick rule %s failed", rule.pattern)
                    continue
                if found:
                    name, args = found
                    if self.registry.get(name):
                        return ToolCall(name=name, arguments=args)
        return None
