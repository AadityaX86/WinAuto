"""Moving, sizing and capturing windows."""

from __future__ import annotations

import ctypes
from datetime import datetime
from pathlib import Path

from winauto.winos import require_windows

SW_MAXIMIZE, SW_MINIMIZE, SW_RESTORE = 3, 6, 9
SWP_NOZORDER, SWP_NOACTIVATE = 0x0004, 0x0010


def _rect_type():
    from ctypes import wintypes

    return wintypes.RECT


class WindowsLayout:
    def _user32(self):
        from winauto.winos.apps import _user32

        u = _user32()
        from ctypes import wintypes

        u.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
        u.MonitorFromWindow.argtypes = [wintypes.HWND, wintypes.DWORD]
        u.MonitorFromWindow.restype = wintypes.HMONITOR
        u.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.UINT]
        u.IsZoomed.argtypes = [wintypes.HWND]
        return u

    def foreground(self) -> int:
        require_windows("Window control")
        return int(self._user32().GetForegroundWindow() or 0)

    def work_area(self, hwnd: int) -> tuple[int, int, int, int]:
        """Usable screen area (minus taskbar) of the monitor the window is on."""
        from ctypes import wintypes

        class MONITORINFO(ctypes.Structure):
            _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", wintypes.RECT), ("rcWork", wintypes.RECT),
                        ("dwFlags", wintypes.DWORD)]

        u = self._user32()
        mon = u.MonitorFromWindow(hwnd, 2)  # MONITOR_DEFAULTTONEAREST
        info = MONITORINFO()
        info.cbSize = ctypes.sizeof(info)
        u.GetMonitorInfoW(mon, ctypes.byref(info))
        r = info.rcWork
        return r.left, r.top, r.right, r.bottom

    def _invisible_border(self, hwnd: int) -> tuple[int, int, int, int]:
        """Windows 10/11 windows have invisible resize borders; we compensate so snapped windows touch."""
        RECT = _rect_type()
        outer = RECT()
        self._user32().GetWindowRect(hwnd, ctypes.byref(outer))
        frame = RECT()
        try:
            ctypes.windll.dwmapi.DwmGetWindowAttribute(ctypes.c_void_p(hwnd), 9, ctypes.byref(frame), ctypes.sizeof(frame))
        except OSError:
            return 0, 0, 0, 0
        return frame.left - outer.left, frame.top - outer.top, outer.right - frame.right, outer.bottom - frame.bottom

    def place(self, hwnd: int, x: int, y: int, w: int, h: int) -> None:
        require_windows("Window control")
        u = self._user32()
        if u.IsZoomed(hwnd) or u.IsIconic(hwnd):
            u.ShowWindow(hwnd, SW_RESTORE)
        left, top, right, bottom = self._invisible_border(hwnd)
        u.SetWindowPos(hwnd, None, x - left, y - top, w + left + right, h + top + bottom, SWP_NOZORDER | SWP_NOACTIVATE)

    def show(self, hwnd: int, command: int) -> None:
        require_windows("Window control")
        self._user32().ShowWindow(hwnd, command)

    def screenshot(self, folder: Path, hwnd: int | None = None) -> Path:
        require_windows("Screenshots")
        from PIL import ImageGrab

        if hwnd:
            RECT = _rect_type()
            r = RECT()
            self._user32().GetWindowRect(hwnd, ctypes.byref(r))
            left, top, right, bottom = self._invisible_border(hwnd)
            image = ImageGrab.grab(bbox=(r.left + left, r.top + top, r.right - right, r.bottom - bottom), all_screens=True)
        else:
            image = ImageGrab.grab(all_screens=True)
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"WinAuto {datetime.now().strftime('%Y-%m-%d %H-%M-%S')}.png"
        image.save(path)
        return path
