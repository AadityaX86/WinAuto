"""Typing and key presses into the app in front (SendInput), and waiting for app windows."""

from __future__ import annotations

import ctypes
import logging
import time

from winauto.adapters.winos import require_windows
from winauto.adapters.winos.hotkey import KEYS, MODIFIERS

log = logging.getLogger(__name__)

INPUT_KEYBOARD, KEYEVENTF_KEYUP, KEYEVENTF_UNICODE = 1, 0x2, 0x4
MOD_VK = {1: 0x12, 2: 0x11, 4: 0x10, 8: 0x5B}  # alt, ctrl, shift, win


def _structs():
    from ctypes import wintypes

    ulong_ptr = ctypes.c_size_t

    class KEYBDINPUT(ctypes.Structure):
        _fields_ = [("wVk", wintypes.WORD), ("wScan", wintypes.WORD), ("dwFlags", wintypes.DWORD),
                    ("time", wintypes.DWORD), ("dwExtraInfo", ulong_ptr)]

    class MOUSEINPUT(ctypes.Structure):
        _fields_ = [("dx", wintypes.LONG), ("dy", wintypes.LONG), ("mouseData", wintypes.DWORD),
                    ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD), ("dwExtraInfo", ulong_ptr)]

    class HARDWAREINPUT(ctypes.Structure):
        _fields_ = [("uMsg", wintypes.DWORD), ("wParamL", wintypes.WORD), ("wParamH", wintypes.WORD)]

    class _U(ctypes.Union):
        _fields_ = [("ki", KEYBDINPUT), ("mi", MOUSEINPUT), ("hi", HARDWAREINPUT)]

    class INPUT(ctypes.Structure):
        _anonymous_ = ("u",)
        _fields_ = [("type", wintypes.DWORD), ("u", _U)]

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.SendInput.argtypes = [wintypes.UINT, ctypes.POINTER(INPUT), ctypes.c_int]
    user32.SendInput.restype = wintypes.UINT
    return INPUT, user32


_CACHE: tuple | None = None


def _send(events: list[tuple[int, int, int]]) -> None:
    """events: (virtual key, scan code / char, flags)."""
    global _CACHE
    if _CACHE is None:
        _CACHE = _structs()
    INPUT, user32 = _CACHE
    arr = (INPUT * len(events))()
    for i, (vk, scan, flags) in enumerate(events):
        arr[i].type = INPUT_KEYBOARD
        arr[i].ki.wVk = vk
        arr[i].ki.wScan = scan
        arr[i].ki.dwFlags = flags
    sent = user32.SendInput(len(events), arr, ctypes.sizeof(INPUT))
    if sent != len(events):
        raise OSError(f"Windows blocked the key presses (sent {sent}/{len(events)}).")


def press(combo: str) -> None:
    """Press a key or combination: 'enter', 'ctrl+k', 'shift+enter'."""
    require_windows("Pressing keys")
    parts = [p.strip().lower() for p in combo.split("+") if p.strip()]
    mods = [MOD_VK[MODIFIERS[p]] for p in parts if p in MODIFIERS]
    keys = [p for p in parts if p not in MODIFIERS]
    if len(keys) != 1:
        raise ValueError(f"Bad key combination '{combo}'")
    key = keys[0]
    vk = KEYS.get(key) or (ord(key.upper()) if len(key) == 1 and key.isalnum() else None)
    if vk is None:
        raise ValueError(f"Unknown key '{key}'")
    events = [(m, 0, 0) for m in mods] + [(vk, 0, 0), (vk, 0, KEYEVENTF_KEYUP)]
    events += [(m, 0, KEYEVENTF_KEYUP) for m in reversed(mods)]
    _send(events)


def type_text(text: str, newline: str = "shift+enter") -> None:
    """Type text into the focused box. Newlines use Shift+Enter so chat apps don't send early."""
    require_windows("Typing")
    lines = text.replace("\r\n", "\n").split("\n")
    for i, line in enumerate(lines):
        if line:
            events = []
            for unit in _utf16_units(line):
                events.append((0, unit, KEYEVENTF_UNICODE))
                events.append((0, unit, KEYEVENTF_UNICODE | KEYEVENTF_KEYUP))
            for start in range(0, len(events), 200):
                _send(events[start:start + 200])
                time.sleep(0.01)
        if i < len(lines) - 1:
            press(newline)


def _utf16_units(text: str) -> list[int]:
    data = text.encode("utf-16-le")
    return [int.from_bytes(data[i:i + 2], "little") for i in range(0, len(data), 2)]


def foreground_exe() -> str:
    require_windows("Checking the active window")
    from winauto.adapters.winos.apps import _exe_of, _pid_of, _user32

    hwnd = _user32().GetForegroundWindow()
    return _exe_of(_pid_of(hwnd)) if hwnd else ""


def wait_for_window(exe_names: set[str], timeout: float = 15.0, title_contains: str = "") -> int | None:
    """Wait until an app window from one of `exe_names` is open. Returns its handle."""
    require_windows("Waiting for an app")
    from winauto.adapters.winos.apps import list_windows

    deadline = time.time() + timeout
    while time.time() < deadline:
        for w in list_windows():
            if w.exe in exe_names and (not title_contains or title_contains.lower() in w.title.lower()):
                return w.hwnd
        time.sleep(0.3)
    return None


def bring_to_front(hwnd: int, exe_names: set[str], tries: int = 3) -> bool:
    from winauto.adapters.winos.apps import focus_window

    for _ in range(tries):
        focus_window(hwnd)
        time.sleep(0.25)
        if foreground_exe() in exe_names:
            return True
    return False
