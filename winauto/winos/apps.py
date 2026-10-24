"""Installed apps, launching, and top-level windows."""

from __future__ import annotations

import ctypes
import json
import logging
import os
import re
import subprocess
import time
from dataclasses import asdict, dataclass
from pathlib import Path

from winauto.winos import CREATE_NO_WINDOW, IS_WINDOWS, require_windows
from winauto.winos.powershell import run_powershell

log = logging.getLogger(__name__)


@dataclass
class AppEntry:
    name: str
    target: str
    kind: str  # "appid" (shell:AppsFolder), "path" (exe/lnk), "uri" (ms-settings: etc.)
    icon: str = ""  # a file whose icon represents the app (exe or shortcut), if known

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class WindowInfo:
    hwnd: int
    title: str
    pid: int
    exe: str  # lower-case file name without .exe, e.g. "chrome"


_SKIP_WORDS = ("uninstall", "readme", "read me", "help", "documentation", "release notes",
               "license", "website", "manual", "changelog", "what's new")


def _start_menu_dirs() -> list[Path]:
    dirs = []
    for env, sub in (("ProgramData", r"Microsoft\Windows\Start Menu\Programs"),
                     ("APPDATA", r"Microsoft\Windows\Start Menu\Programs")):
        base = os.environ.get(env)
        if base:
            dirs.append(Path(base) / sub)
    home = Path.home()
    dirs += [home / "Desktop", Path(os.environ.get("PUBLIC", r"C:\Users\Public")) / "Desktop"]
    return [d for d in dirs if d.exists()]


def scan_shortcuts() -> list[AppEntry]:
    found: list[AppEntry] = []
    for base in _start_menu_dirs():
        for path in base.rglob("*"):
            if path.suffix.lower() not in (".lnk", ".url", ".appref-ms"):
                continue
            name = path.stem
            if any(w in name.lower() for w in _SKIP_WORDS):
                continue
            found.append(AppEntry(name, str(path), "path"))
    return found


_START_APPS_SCRIPT = r"""
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
Get-StartApps | Select-Object Name, AppID | ConvertTo-Json -Compress
"""


def start_apps() -> list[AppEntry]:
    """Everything in the Start menu's 'All apps' list, including Store apps."""
    result = run_powershell(_START_APPS_SCRIPT, timeout=30)
    if result.returncode != 0 or not result.stdout.strip():
        log.warning("Get-StartApps failed: %s", result.stderr[:300])
        return []
    try:
        data = json.loads(result.stdout)
    except ValueError:
        log.warning("Get-StartApps returned non-JSON")
        return []
    if isinstance(data, dict):
        data = [data]
    apps = []
    for item in data:
        name, app_id = item.get("Name"), item.get("AppID")
        if name and app_id and not any(w in name.lower() for w in _SKIP_WORDS):
            apps.append(AppEntry(name, app_id, "appid"))
    return apps


def appid_path(app_id: str) -> str:
    """Desktop apps' AppIDs are often '{KnownFolderGUID}\\rest\\of\\path.exe'."""
    m = re.match(r"^\{([0-9A-Fa-f-]{36})\}\\(.+)$", app_id or "")
    if m:
        try:
            from winauto.winos.folders import _known_folder

            base = _known_folder(m.group(1))
        except (OSError, AttributeError):  # AttributeError: not on Windows
            base = None
        if base:
            path = base / m.group(2)
            return str(path) if path.exists() else ""
    if re.match(r"^[A-Za-z]:\\", app_id or "") and Path(app_id).exists():
        return app_id
    return ""


class WindowsApps:
    """The real Windows implementation used by the apps skill."""

    def installed(self) -> list[AppEntry]:
        require_windows("Finding apps")
        apps = start_apps()
        shortcuts = scan_shortcuts()
        by_name = {s.name.lower(): s.target for s in shortcuts}
        for a in apps:
            a.icon = by_name.get(a.name.lower()) or appid_path(a.target) or ""
        names = {a.name.lower() for a in apps}
        for entry in shortcuts:
            if entry.name.lower() not in names:
                entry.icon = entry.target
                apps.append(entry)
                names.add(entry.name.lower())
        return apps

    def launch(self, entry: AppEntry) -> None:
        require_windows("Opening apps")
        if entry.kind == "appid":
            subprocess.Popen(["explorer.exe", f"shell:AppsFolder\\{entry.target}"], creationflags=CREATE_NO_WINDOW)
        else:
            os.startfile(entry.target)  # type: ignore[attr-defined]

    def windows(self) -> list[WindowInfo]:
        require_windows("Listing windows")
        return list_windows()

    def close_window(self, hwnd: int) -> None:
        _user32().PostMessageW(hwnd, 0x0010, 0, 0)  # WM_CLOSE

    def window_exists(self, hwnd: int) -> bool:
        return bool(_user32().IsWindow(hwnd))

    def focus(self, hwnd: int) -> bool:
        return focus_window(hwnd)

    def kill(self, pid: int) -> None:
        import psutil

        proc = psutil.Process(pid)
        for child in proc.children(recursive=True):
            try:
                child.kill()
            except psutil.Error:
                pass
        proc.kill()

    def process_ids(self, exe_names: set[str]) -> list[int]:
        import psutil

        pids = []
        for proc in psutil.process_iter(["pid", "name"]):
            name = (proc.info.get("name") or "").lower()
            if name.endswith(".exe"):
                name = name[:-4]
            if name in exe_names:
                pids.append(proc.info["pid"])
        return pids


# ---------------- Win32 helpers ----------------

_U32 = None


def _user32():
    global _U32
    if _U32 is None:
        from ctypes import wintypes

        u = ctypes.WinDLL("user32", use_last_error=True)
        u.IsWindowVisible.argtypes = [wintypes.HWND]
        u.IsWindow.argtypes = [wintypes.HWND]
        u.IsIconic.argtypes = [wintypes.HWND]
        u.GetWindowTextLengthW.argtypes = [wintypes.HWND]
        u.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
        u.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
        u.GetWindowThreadProcessId.restype = wintypes.DWORD
        u.GetWindow.argtypes = [wintypes.HWND, wintypes.UINT]
        u.GetWindow.restype = wintypes.HWND
        u.GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]
        u.GetWindowLongW.restype = ctypes.c_long
        u.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
        u.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
        u.SetForegroundWindow.argtypes = [wintypes.HWND]
        u.BringWindowToTop.argtypes = [wintypes.HWND]
        u.GetForegroundWindow.restype = wintypes.HWND
        u.keybd_event.argtypes = [wintypes.BYTE, wintypes.BYTE, wintypes.DWORD, ctypes.c_size_t]
        _U32 = u
    return _U32


def _pid_of(hwnd: int) -> int:
    from ctypes import wintypes

    pid = wintypes.DWORD()
    _user32().GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return int(pid.value)


def _exe_of(pid: int) -> str:
    try:
        import psutil

        name = psutil.Process(pid).name().lower()
    except Exception:
        return ""
    return name[:-4] if name.endswith(".exe") else name


def _is_cloaked(hwnd: int) -> bool:
    """Hidden UWP windows report as visible but are 'cloaked'."""
    try:
        from ctypes import wintypes

        dwm = ctypes.WinDLL("dwmapi")
        cloaked = ctypes.c_int(0)
        dwm.DwmGetWindowAttribute(wintypes.HWND(hwnd), 14, ctypes.byref(cloaked), ctypes.sizeof(cloaked))
        return cloaked.value != 0
    except OSError:
        return False


def _uwp_real_pid(hwnd: int, frame_pid: int) -> int:
    """Store apps live inside ApplicationFrameHost; find the app's own process."""
    from ctypes import wintypes

    u = _user32()
    found = [frame_pid]
    proc_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    def cb(child, _):
        pid = _pid_of(child)
        if pid != frame_pid:
            found[0] = pid
            return False
        return True

    u.EnumChildWindows(wintypes.HWND(hwnd), proc_type(cb), 0)
    return found[0]


def list_windows() -> list[WindowInfo]:
    """Visible top-level app windows (what you'd see in Alt+Tab)."""
    from ctypes import wintypes

    u = _user32()
    out: list[WindowInfo] = []
    proc_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    own_pid = os.getpid()

    def cb(hwnd, _):
        try:
            if not u.IsWindowVisible(hwnd) or u.GetWindow(hwnd, 4):  # GW_OWNER: skip dialogs
                return True
            ex_style = u.GetWindowLongW(hwnd, -20)  # GWL_EXSTYLE
            if ex_style & 0x80:  # WS_EX_TOOLWINDOW
                return True
            length = u.GetWindowTextLengthW(hwnd)
            if length == 0:
                return True
            buf = ctypes.create_unicode_buffer(length + 1)
            u.GetWindowTextW(hwnd, buf, length + 1)
            if _is_cloaked(hwnd):
                return True
            pid = _pid_of(hwnd)
            if pid == own_pid:
                return True
            exe = _exe_of(pid)
            if exe == "applicationframehost":
                pid = _uwp_real_pid(hwnd, pid)
                exe = _exe_of(pid) or exe
            if exe == "explorer" and buf.value in ("Program Manager", ""):
                return True
            out.append(WindowInfo(int(hwnd), buf.value, pid, exe))
        except Exception:
            log.debug("skipping window", exc_info=True)
        return True

    u.EnumWindows(proc_type(cb), 0)
    return out


def focus_window(hwnd: int) -> bool:
    u = _user32()
    if u.IsIconic(hwnd):
        u.ShowWindow(hwnd, 9)  # SW_RESTORE
    # Tapping Alt lets us take the foreground from another app.
    u.keybd_event(0x12, 0, 0, 0)
    u.keybd_event(0x12, 0, 2, 0)
    u.BringWindowToTop(hwnd)
    ok = bool(u.SetForegroundWindow(hwnd))
    time.sleep(0.05)
    return ok or u.GetForegroundWindow() == hwnd
