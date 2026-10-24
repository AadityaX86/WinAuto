"""Spoken replies and voice typing."""

from __future__ import annotations

import logging

from winauto.adapters.winos import IS_WINDOWS
from winauto.core.context import Context

log = logging.getLogger(__name__)


class VoiceService:
    def __init__(self, ctx: Context):
        self.ctx = ctx

    def speak_reply(self, text: str) -> None:
        """Read a reply aloud if the user turned that on. Blocks while starting the voice: call it off the UI thread."""
        if not text or not self.ctx.config.speak_replies:
            return
        voice = self.ctx.skill("voice")
        if voice:
            voice.say(text)

    @property
    def can_dictate(self) -> bool:
        return IS_WINDOWS

    def dictate(self) -> None:
        """Start Windows voice typing (Win+H); it types into whatever has focus."""
        try:
            from winauto.adapters.winos.keyboard import press

            press("win+h")
        except Exception:
            log.debug("voice typing failed", exc_info=True)
