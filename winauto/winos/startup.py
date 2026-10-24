"""Start WinAuto when you sign in to Windows (HKCU Run key)."""

from __future__ import annotations

import logging
import sys
from pathlib import Path

from winauto.winos import IS_WINDOWS

log = logging.getLogger(__name__)

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
VALUE = "WinAuto"


def launch_command() -> str:
    if getattr(sys, "frozen", False):  # PyInstaller exe
        return f'"{sys.executable}" --background'
    exe = Path(sys.executable)
    pythonw = exe.with_name("pythonw.exe")
    if pythonw.exists():
        exe = pythonw
    return f'"{exe}" -m winauto --background'


def set_start_with_windows(enabled: bool) -> None:
    if not IS_WINDOWS:
        return
    import winreg

    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
        if enabled:
            winreg.SetValueEx(key, VALUE, 0, winreg.REG_SZ, launch_command())
        else:
            try:
                winreg.DeleteValue(key, VALUE)
            except FileNotFoundError:
                pass


def starts_with_windows() -> bool:
    if not IS_WINDOWS:
        return False
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            winreg.QueryValueEx(key, VALUE)
            return True
    except OSError:
        return False
