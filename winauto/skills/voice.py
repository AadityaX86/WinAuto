"""Read text aloud with Windows' built-in voices (offline)."""

from __future__ import annotations

import logging
import re
from typing import Any

from winauto.core.skill import QuickRule, Skill, ToolResult, fail, ok, tool
from winauto.adapters.winos import NotOnWindows
from winauto.adapters.winos.speech import Speaker

log = logging.getLogger(__name__)


def speakable(text: str) -> str:
    """Strip markdown and links so the voice doesn't read symbols."""
    t = re.sub(r"```.*?```", " (code) ", text, flags=re.S)
    t = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", t)
    t = re.sub(r"https?://\S+", "", t)
    t = re.sub(r"[*_`#>~|]", "", t)
    t = re.sub(r"^\s*[-•]\s+", "", t, flags=re.M)
    return " ".join(t.split())[:4000]


class VoiceSkill(Skill):
    name = "voice"
    description = "Read text aloud."
    keywords = r"\b(read (?:it |this |that )?(?:aloud|out)|say it|speak|stop (?:talking|reading))\b"

    def __init__(self, ctx: Any, speaker: Any = None):
        super().__init__(ctx)
        self.speaker = speaker or Speaker()

    def say(self, text: str) -> None:
        """Used by the app to read replies aloud when that setting is on."""
        try:
            self.speaker.say(speakable(text))
        except Exception:
            log.debug("speaking failed", exc_info=True)

    @tool("Read text aloud. Leave text empty to read the selected or copied text.", params={"text": "What to read"})
    def read_aloud(self, text: str = "") -> ToolResult:
        if not text.strip():
            text = self.ctx.services.get("selection") or ""
        if not text.strip():
            clip = self.ctx.services.get("skills", {}).get("clipboard")
            if clip:
                try:
                    text = clip.backend.get_text() or ""
                except Exception:
                    text = ""
        if not text.strip():
            return fail("There's nothing to read. Select or copy some text first.")
        try:
            self.speaker.say(speakable(text))
        except (NotOnWindows, OSError) as exc:
            return fail(str(exc))
        return ok("🔊 Reading aloud. Say “stop reading” to stop.")

    @tool("Stop reading aloud.")
    def stop_speaking(self) -> ToolResult:
        return ok("Stopped.") if self.speaker.stop() else ok("I wasn't reading anything.")

    def quick_rules(self) -> list[QuickRule]:
        return [
            QuickRule(r"(?:read|say)\s+(?:this|that|it|what\s+i\s+(?:copied|selected))\s+(?:aloud|out(?:\s+loud)?)|read\s+aloud",
                      lambda m: ("read_aloud", {})),
            QuickRule(r"(?:stop|shut up|be quiet|quiet)(?:\s+(?:talking|reading|speaking))?", lambda m: ("stop_speaking", {}),
                      priority=45),
        ]
