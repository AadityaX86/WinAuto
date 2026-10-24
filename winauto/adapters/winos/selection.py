"""Grab the text selected in the app in front, without losing what was on the clipboard."""

from __future__ import annotations

import ctypes
import logging
import time

from winauto.adapters.winos import require_windows

log = logging.getLogger(__name__)

MODIFIER_KEYS = (0x10, 0x11, 0x12, 0x5B, 0x5C)  # shift, ctrl, alt, left/right win


def _wait_for_modifiers_released(timeout: float = 1.5) -> None:
    """The hotkey's Ctrl/Alt are still down; Ctrl+C would turn into Ctrl+Alt+C."""
    user32 = ctypes.windll.user32
    deadline = time.time() + timeout
    while time.time() < deadline:
        if not any(user32.GetAsyncKeyState(vk) & 0x8000 for vk in MODIFIER_KEYS):
            return
        time.sleep(0.02)


def capture_selection(timeout: float = 0.8) -> str:
    """Copy the current selection and return it ("" if nothing was selected)."""
    require_windows("Reading the selection")
    from winauto.adapters.winos.clipboard import WindowsClipboard
    from winauto.adapters.winos.keyboard import press

    clip = WindowsClipboard()
    try:
        previous = clip.get_text()
    except OSError:
        previous = None
    before = clip.sequence()
    _wait_for_modifiers_released()
    press("ctrl+c")
    deadline = time.time() + timeout
    while time.time() < deadline and clip.sequence() == before:
        time.sleep(0.03)
    if clip.sequence() == before:
        return ""  # nothing was selected (or the app ignored Ctrl+C)
    try:
        text = clip.get_text() or ""
    except OSError:
        text = ""
    # Put back what the user had copied before.
    if previous is not None:
        try:
            clip.set_text(previous)
        except OSError:
            log.debug("couldn't restore the clipboard", exc_info=True)
    return text
