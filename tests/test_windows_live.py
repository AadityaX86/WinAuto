"""Exercise the real Windows calls (read-only ones) on a Windows machine / CI runner."""

from __future__ import annotations

import sys

import pytest

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="Windows only")


def test_powershell_runs():
    from winauto.adapters.winos.powershell import run_powershell

    r = run_powershell("Write-Output ('a' + 'b')")
    assert r.returncode == 0 and r.stdout.strip() == "ab"


def test_list_windows_does_not_crash():
    from winauto.adapters.winos.apps import list_windows

    for w in list_windows():
        assert isinstance(w.hwnd, int) and isinstance(w.title, str)


def test_installed_apps():
    from winauto.adapters.winos.apps import WindowsApps

    apps = WindowsApps().installed()
    assert isinstance(apps, list)
    names = {a.name for a in apps}
    # Server images may lack Start menu apps, so only check the shape.
    assert all(isinstance(n, str) and n for n in names)


def test_registry_reads():
    from winauto.adapters.winos.system import WindowsSystem

    assert isinstance(WindowsSystem().is_dark_mode(), bool)
    count, size = WindowsSystem().recycle_bin()
    assert count >= 0 and size >= 0


def test_hotkey_register_and_stop():
    from winauto.adapters.winos.hotkey import HotkeyListener

    listener = HotkeyListener("ctrl+alt+shift+f12", lambda: None)
    started = listener.start()
    listener.stop()
    # Runners without a desktop may refuse; either way it must not hang or crash.
    assert started or listener.error


def test_start_with_windows_roundtrip():
    from winauto.adapters.winos.startup import (
        set_start_with_windows,
        starts_with_windows,
    )

    before = starts_with_windows()
    try:
        set_start_with_windows(True)
        assert starts_with_windows()
        set_start_with_windows(False)
        assert not starts_with_windows()
    finally:
        set_start_with_windows(before)
