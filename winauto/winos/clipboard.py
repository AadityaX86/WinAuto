"""Text clipboard via the Win32 API (works from any thread, unlike Qt's clipboard)."""

from __future__ import annotations

import ctypes
import time

from winauto.winos import require_windows

CF_UNICODETEXT = 13
GMEM_MOVEABLE = 0x0002

_API = None


def _api():
    global _API
    if _API is None:
        from ctypes import wintypes

        u = ctypes.WinDLL("user32", use_last_error=True)
        k = ctypes.WinDLL("kernel32", use_last_error=True)
        u.OpenClipboard.argtypes = [wintypes.HWND]
        u.OpenClipboard.restype = wintypes.BOOL
        u.GetClipboardData.argtypes = [wintypes.UINT]
        u.GetClipboardData.restype = wintypes.HANDLE
        u.SetClipboardData.argtypes = [wintypes.UINT, wintypes.HANDLE]
        u.SetClipboardData.restype = wintypes.HANDLE
        u.IsClipboardFormatAvailable.argtypes = [wintypes.UINT]
        u.GetClipboardSequenceNumber.restype = wintypes.DWORD
        k.GlobalLock.argtypes = [wintypes.HGLOBAL]
        k.GlobalLock.restype = wintypes.LPVOID
        k.GlobalUnlock.argtypes = [wintypes.HGLOBAL]
        k.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]
        k.GlobalAlloc.restype = wintypes.HGLOBAL
        _API = (u, k)
    return _API


def _open() -> None:
    u, _ = _api()
    for _ in range(20):  # another app may be holding it for a moment
        if u.OpenClipboard(None):
            return
        time.sleep(0.05)
    raise OSError("The clipboard is busy (another app is using it).")


class WindowsClipboard:
    def sequence(self) -> int:
        require_windows("The clipboard")
        return int(_api()[0].GetClipboardSequenceNumber())

    def get_text(self) -> str | None:
        require_windows("The clipboard")
        u, k = _api()
        if not u.IsClipboardFormatAvailable(CF_UNICODETEXT):
            return None
        _open()
        try:
            handle = u.GetClipboardData(CF_UNICODETEXT)
            if not handle:
                return None
            ptr = k.GlobalLock(handle)
            if not ptr:
                return None
            try:
                return ctypes.wstring_at(ptr)
            finally:
                k.GlobalUnlock(handle)
        finally:
            u.CloseClipboard()

    def set_text(self, text: str) -> None:
        require_windows("The clipboard")
        u, k = _api()
        data = text.encode("utf-16-le") + b"\x00\x00"
        _open()
        try:
            u.EmptyClipboard()
            handle = k.GlobalAlloc(GMEM_MOVEABLE, len(data))
            if not handle:
                raise OSError("Out of memory for the clipboard.")
            ptr = k.GlobalLock(handle)
            ctypes.memmove(ptr, data, len(data))
            k.GlobalUnlock(handle)
            if not u.SetClipboardData(CF_UNICODETEXT, handle):
                raise OSError("Windows refused the clipboard text.")
        finally:
            u.CloseClipboard()
