"""Reading a pixel's colour under the mouse."""

from __future__ import annotations

import ctypes

from winauto.winos import require_windows


def color_under_cursor() -> tuple[int, int, int]:
    require_windows("The colour picker")
    from ctypes import wintypes

    user32, gdi32 = ctypes.windll.user32, ctypes.windll.gdi32
    point = wintypes.POINT()
    user32.GetCursorPos(ctypes.byref(point))
    user32.GetDC.restype = wintypes.HDC
    gdi32.GetPixel.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int]
    gdi32.GetPixel.restype = wintypes.DWORD
    user32.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]
    hdc = user32.GetDC(None)
    try:
        value = gdi32.GetPixel(hdc, point.x, point.y)
    finally:
        user32.ReleaseDC(None, hdc)
    if value == 0xFFFFFFFF:
        raise OSError("Couldn't read that pixel.")
    return value & 0xFF, (value >> 8) & 0xFF, (value >> 16) & 0xFF
