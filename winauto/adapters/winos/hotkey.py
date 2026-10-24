"""System-wide hotkey (e.g. Ctrl+Alt+Space) using RegisterHotKey."""

from __future__ import annotations

import ctypes
import logging
import threading
from typing import Callable

from winauto.adapters.winos import IS_WINDOWS

log = logging.getLogger(__name__)

MOD_ALT, MOD_CONTROL, MOD_SHIFT, MOD_WIN, MOD_NOREPEAT = 0x1, 0x2, 0x4, 0x8, 0x4000
WM_HOTKEY, WM_QUIT = 0x0312, 0x0012

MODIFIERS = {
    "ctrl": MOD_CONTROL, "control": MOD_CONTROL, "alt": MOD_ALT, "shift": MOD_SHIFT,
    "win": MOD_WIN, "windows": MOD_WIN, "super": MOD_WIN, "meta": MOD_WIN,
}
KEYS = {
    "space": 0x20, "enter": 0x0D, "return": 0x0D, "tab": 0x09, "esc": 0x1B, "escape": 0x1B,
    "backspace": 0x08, "insert": 0x2D, "delete": 0x2E, "del": 0x2E, "home": 0x24, "end": 0x23,
    "pageup": 0x21, "pagedown": 0x22, "up": 0x26, "down": 0x28, "left": 0x25, "right": 0x27,
    "`": 0xC0, "backquote": 0xC0, "grave": 0xC0, ";": 0xBA, "/": 0xBF, ".": 0xBE, ",": 0xBC,
    "-": 0xBD, "=": 0xBB, "[": 0xDB, "]": 0xDD, "\\": 0xDC, "'": 0xDE,
}
KEYS.update({f"f{i}": 0x6F + i for i in range(1, 25)})


def parse_hotkey(text: str) -> tuple[int, int]:
    """'ctrl+alt+space' -> (modifier flags, virtual key code)."""
    parts = [p.strip().lower() for p in (text or "").replace(" ", "").split("+")]
    # "ctrl++" means the plus key
    if parts[-2:] == ["", ""]:
        parts = parts[:-2] + ["="]
    mods, key = 0, None
    for p in parts:
        if not p:
            continue
        if p in MODIFIERS:
            mods |= MODIFIERS[p]
        elif key is not None:
            raise ValueError(f"'{text}' has more than one main key")
        elif p in KEYS:
            key = KEYS[p]
        elif len(p) == 1 and p.isalnum():
            key = ord(p.upper())
        else:
            raise ValueError(f"Unknown key '{p}' in '{text}'")
    if key is None:
        raise ValueError(f"'{text}' needs a main key, like ctrl+alt+space")
    if mods == 0:
        raise ValueError(f"'{text}' needs at least one of ctrl, alt, shift or win")
    return mods, key


class HotkeyListener:
    """Calls `callback` (on a background thread) each time the hotkey is pressed."""

    def __init__(self, hotkey: str, callback: Callable[[], None]):
        self.hotkey = hotkey
        self.callback = callback
        self._thread: threading.Thread | None = None
        self._thread_id = 0
        self._ready = threading.Event()
        self.error: str | None = None

    def start(self) -> bool:
        if not IS_WINDOWS:
            self.error = "Global hotkeys only work on Windows."
            return False
        try:
            self._mods, self._vk = parse_hotkey(self.hotkey)
        except ValueError as exc:
            self.error = str(exc)
            return False
        self._ready.clear()
        self._thread = threading.Thread(target=self._run, name="hotkey", daemon=True)
        self._thread.start()
        self._ready.wait(5)
        return self.error is None

    def stop(self) -> None:
        if self._thread and self._thread.is_alive() and self._thread_id:
            ctypes.windll.user32.PostThreadMessageW(self._thread_id, WM_QUIT, 0, 0)
            self._thread.join(2)
        self._thread = None

    def _run(self) -> None:
        from ctypes import wintypes

        user32 = ctypes.WinDLL("user32", use_last_error=True)
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        user32.RegisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int, wintypes.UINT, wintypes.UINT]
        user32.RegisterHotKey.restype = wintypes.BOOL
        user32.UnregisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int]
        user32.GetMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT]
        user32.GetMessageW.restype = ctypes.c_int
        user32.PeekMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT, wintypes.UINT]

        self._thread_id = kernel32.GetCurrentThreadId()
        msg = wintypes.MSG()
        # Make sure this thread has a message queue before anyone posts WM_QUIT to it.
        user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, 0)
        if not user32.RegisterHotKey(None, 1, self._mods | MOD_NOREPEAT, self._vk):
            err = ctypes.get_last_error()
            self.error = (
                f"{self.hotkey} is already used by another app. Pick another hotkey in Settings."
                if err == 1409 else f"Couldn't register {self.hotkey} (error {err})."
            )
            self._ready.set()
            return
        self._ready.set()
        log.info("Hotkey %s registered", self.hotkey)
        try:
            while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
                if msg.message == WM_HOTKEY:
                    try:
                        self.callback()
                    except Exception:
                        log.exception("hotkey callback failed")
        finally:
            user32.UnregisterHotKey(None, 1)
