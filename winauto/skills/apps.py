"""Open, close, switch to and list apps."""

from __future__ import annotations

import json
import logging
import re
import shutil
import threading
import time
from typing import Any

from winauto.core.matching import normalize, rank, score
from winauto.core.quick import is_simple
from winauto.core.skill import QuickRule, Risk, Skill, ToolResult, fail, ok, tool
from winauto.winos import NotOnWindows
from winauto.winos.apps import AppEntry, WindowInfo

log = logging.getLogger(__name__)

# What people say -> the name Windows uses.
ALIASES = {
    "vs code": "Visual Studio Code", "vscode": "Visual Studio Code", "code": "Visual Studio Code",
    "chrome": "Google Chrome", "google chrome": "Google Chrome", "edge": "Microsoft Edge",
    "firefox": "Firefox", "brave": "Brave", "word": "Word", "ms word": "Word", "excel": "Excel",
    "powerpoint": "PowerPoint", "ppt": "PowerPoint", "outlook": "Outlook", "onenote": "OneNote",
    "teams": "Microsoft Teams", "ms teams": "Microsoft Teams", "whatsapp": "WhatsApp",
    "explorer": "File Explorer", "file explorer": "File Explorer", "files": "File Explorer",
    "my files": "File Explorer", "this pc": "File Explorer", "calc": "Calculator",
    "calculator": "Calculator", "cmd": "Command Prompt", "command prompt": "Command Prompt",
    "terminal": "Terminal", "windows terminal": "Terminal", "powershell": "Windows PowerShell",
    "store": "Microsoft Store", "microsoft store": "Microsoft Store", "app store": "Microsoft Store",
    "settings": "Settings", "control panel": "Control Panel", "task manager": "Task Manager",
    "paint": "Paint", "notepad": "Notepad", "snipping tool": "Snipping Tool", "camera": "Camera",
    "photos": "Photos", "clock": "Clock", "alarms": "Clock", "calendar": "Calendar", "mail": "Mail",
    "spotify": "Spotify", "discord": "Discord", "telegram": "Telegram", "zoom": "Zoom",
    "obs": "OBS Studio", "vlc": "VLC media player", "steam": "Steam", "slack": "Slack",
    "notion": "Notion", "figma": "Figma", "postman": "Postman", "pycharm": "PyCharm",
}

# Built into Windows; used when the Start menu list doesn't have them.
BUILTIN = {
    "Notepad": AppEntry("Notepad", "notepad.exe", "path"),
    "Calculator": AppEntry("Calculator", "calc.exe", "path"),
    "Paint": AppEntry("Paint", "mspaint.exe", "path"),
    "Command Prompt": AppEntry("Command Prompt", "cmd.exe", "path"),
    "Windows PowerShell": AppEntry("Windows PowerShell", "powershell.exe", "path"),
    "Terminal": AppEntry("Terminal", "wt.exe", "path"),
    "Task Manager": AppEntry("Task Manager", "taskmgr.exe", "path"),
    "Control Panel": AppEntry("Control Panel", "control.exe", "path"),
    "File Explorer": AppEntry("File Explorer", "explorer.exe", "path"),
    "Settings": AppEntry("Settings", "ms-settings:", "uri"),
    "Registry Editor": AppEntry("Registry Editor", "regedit.exe", "path"),
    "Microsoft Store": AppEntry("Microsoft Store", "ms-windows-store:", "uri"),
    "Snipping Tool": AppEntry("Snipping Tool", "ms-screenclip:", "uri"),
    "Camera": AppEntry("Camera", "microsoft.windows.camera:", "uri"),
}

# App name -> process names (no .exe), for closing.
PROCESSES = {
    "Google Chrome": ["chrome"], "Microsoft Edge": ["msedge"], "Firefox": ["firefox"],
    "Brave": ["brave"], "Opera": ["opera"], "Visual Studio Code": ["code"], "Word": ["winword"],
    "Excel": ["excel"], "PowerPoint": ["powerpnt"], "Outlook": ["outlook", "olk"],
    "OneNote": ["onenote"], "Microsoft Teams": ["ms-teams", "teams"], "Discord": ["discord"],
    "Spotify": ["spotify"], "WhatsApp": ["whatsapp", "whatsapp.root"], "Telegram": ["telegram"],
    "Zoom": ["zoom"], "Slack": ["slack"], "Steam": ["steam", "steamwebhelper"], "Notion": ["notion"],
    "OBS Studio": ["obs64"], "VLC media player": ["vlc"], "Notepad": ["notepad"],
    "Calculator": ["calculatorapp", "calculator"], "Paint": ["mspaint"], "Task Manager": ["taskmgr"],
    "File Explorer": ["explorer"], "Terminal": ["windowsterminal"], "Command Prompt": ["cmd"],
    "Windows PowerShell": ["powershell"], "Settings": ["systemsettings"], "Photos": ["photos"],
}

# Never force-kill these: Windows itself depends on them.
PROTECTED = {"explorer", "winlogon", "csrss", "smss", "lsass", "services", "svchost", "dwm",
             "wininit", "system", "fontdrvhost", "sihost", "ctfmon", "python", "pythonw", "winauto"}

_STRIP_WORDS = re.compile(r"^(?:the|my|a)\s+|\s+(?:app|application|program|window|windows|browser)$", re.I)


class AppsSkill(Skill):
    name = "apps"
    description = "Open, close, switch between and list apps."
    prompt_hint = (
        "Apps: open_app/close_app take the app's everyday name (e.g. 'chrome', 'vs code'). "
        "For websites use open_website instead."
    )

    def __init__(self, ctx: Any, backend: Any = None):
        super().__init__(ctx)
        if backend is None:
            from winauto.winos.apps import WindowsApps

            backend = WindowsApps()
        self.backend = backend
        self._apps: dict[str, AppEntry] = {}
        self._lock = threading.Lock()
        self._loaded_at = 0.0
        self._refreshing = False

    # ----- app index -----

    def _cache_path(self):
        return self.ctx.data_dir / "apps_cache.json"

    def start(self) -> None:
        try:
            data = json.loads(self._cache_path().read_text(encoding="utf-8"))
            self._set_apps([AppEntry(**a) for a in data])
        except (OSError, ValueError, TypeError):
            pass
        threading.Thread(target=self.refresh, daemon=True, name="apps-refresh").start()

    def _set_apps(self, apps: list[AppEntry]) -> None:
        with self._lock:
            self._apps = {a.name: a for a in apps}

    def refresh(self) -> int:
        if self._refreshing:
            return len(self._apps)
        self._refreshing = True
        try:
            apps = self.backend.installed()
        except NotOnWindows:
            return 0
        except Exception:
            log.exception("Couldn't list installed apps")
            return len(self._apps)
        finally:
            self._refreshing = False
        if apps:
            self._set_apps(apps)
            self._loaded_at = time.time()
            try:
                self._cache_path().write_text(json.dumps([a.to_dict() for a in apps]), encoding="utf-8")
            except OSError:
                pass
        return len(apps)

    def _all_apps(self) -> dict[str, AppEntry]:
        with self._lock:
            apps = dict(self._apps)
        for name, entry in BUILTIN.items():
            apps.setdefault(name, entry)
        return apps

    @staticmethod
    def _clean(name: str) -> str:
        name = name.strip().strip("'\"")
        for _ in range(2):
            name = _STRIP_WORDS.sub("", name).strip()
        return name

    def resolve(self, name: str, cutoff: float = 80.0) -> AppEntry | None:
        """Find an installed app by what the user called it."""
        query = self._clean(name)
        if not query:
            return None
        user_aliases = {normalize(k): v for k, v in self.ctx.config.app_aliases.items()}
        target = user_aliases.get(normalize(query))
        if target:
            if re.match(r"^[a-z]:\\|^\\\\|.*\.(exe|lnk|bat|cmd)$", target, re.I):
                return AppEntry(query, target, "path")
            if re.match(r"^[a-z][a-z0-9+.-]*:", target, re.I):
                return AppEntry(query, target, "uri")
            query = target
        apps = self._all_apps()
        canonical = ALIASES.get(normalize(query), query)
        by_norm = {normalize(n): e for n, e in apps.items()}
        for candidate in (canonical, query):
            if normalize(candidate) in by_norm:
                return by_norm[normalize(candidate)]
        best = rank(canonical, apps.keys(), limit=1, cutoff=cutoff)
        if best:
            return apps[best[0][0]]
        exe = shutil.which(query) if " " not in query else None
        if exe:
            return AppEntry(query, exe, "path")
        # The app list may be stale (just installed something). Refresh at most once a minute.
        if time.time() - self._loaded_at > 60 and not self._refreshing:
            if self.refresh():
                apps = self._all_apps()
                best = rank(canonical, apps.keys(), limit=1, cutoff=cutoff)
                if best:
                    return apps[best[0][0]]
        return None

    def confidence(self, name: str) -> float:
        """How sure we are that `name` means an installed app (for quick commands)."""
        query = self._clean(name)
        canonical = ALIASES.get(normalize(query), query)
        apps = self._all_apps()
        if normalize(query) in {normalize(k) for k in self.ctx.config.app_aliases}:
            return 100.0
        return max((score(canonical, n) for n in apps), default=0.0)

    def suggestions(self, name: str) -> list[str]:
        return [n for n, _ in rank(self._clean(name), self._all_apps().keys(), limit=3, cutoff=60)]

    # ----- windows -----

    def _process_names(self, name: str, entry: AppEntry | None) -> set[str]:
        names: set[str] = set()
        query = self._clean(name)
        canonical = ALIASES.get(normalize(query), entry.name if entry else query)
        for key in {canonical, entry.name if entry else "", query}:
            for proc_key, procs in PROCESSES.items():
                if key and normalize(key) == normalize(proc_key):
                    names.update(procs)
        if entry and entry.kind == "path" and entry.target.lower().endswith(".exe"):
            names.add(re.split(r"[\\/]", entry.target)[-1][:-4].lower())
        if entry and entry.kind == "appid" and entry.target.lower().endswith(".exe"):
            names.add(re.split(r"[\\/]", entry.target)[-1][:-4].lower())
        compact = normalize(query).replace(" ", "")
        if compact and compact not in ("explorer",):
            names.add(compact)
        return names

    def find_windows(self, name: str) -> list[WindowInfo]:
        entry = self.resolve(name)
        procs = self._process_names(name, entry)
        query = normalize(self._clean(name))
        wins = self.backend.windows()
        matched = [w for w in wins if w.exe.lower() in procs]
        def title_has(words: str, title: str) -> bool:
            # Whole words only, so "word" doesn't match "Password manager".
            wanted = words.split()
            return bool(wanted) and set(wanted) <= set(normalize(title).split())

        if not matched and query:
            # Fall back to the window title ("close the budget spreadsheet").
            matched = [w for w in wins if title_has(query, w.title)]
        if not matched and entry:
            matched = [w for w in wins if title_has(normalize(entry.name), w.title)]
        return matched

    @staticmethod
    def _app_label(windows: list[WindowInfo], fallback: str) -> str:
        return fallback if fallback else (windows[0].exe if windows else "it")

    # ----- tools -----

    @tool(
        "Open (launch) an app on this PC, or bring it to the front if it's already open.",
        params={"name": "The app's everyday name, e.g. 'spotify', 'chrome', 'vs code', 'calculator'"},
        hides_popup=True,
    )
    def open_app(self, name: str) -> ToolResult:
        try:
            entry = self.resolve(name)
            if entry is None:
                tips = self.suggestions(name)
                hint = f" Did you mean: {', '.join(tips)}?" if tips else ""
                return fail(f"I couldn't find an app called '{name}'.{hint}", data={"suggestions": tips}, fallback=True)
            running = [] if entry.kind == "uri" else self.find_windows(entry.name)
            if running and self.backend.focus(running[0].hwnd):
                return ok(f"Switched to {entry.name}.")
            self.backend.launch(entry)
            return ok(f"Opened {entry.name}.")
        except NotOnWindows as exc:
            return fail(str(exc))
        except OSError as exc:
            return fail(f"Couldn't open {name}: {exc}")

    @tool(
        "Close an app's windows normally (the app can still ask to save).",
        params={"name": "The app's everyday name, or words from the window title"},
    )
    def close_app(self, name: str) -> ToolResult:
        try:
            windows = self.find_windows(name)
            entry = self.resolve(name)
            label = entry.name if entry else name
            if not windows:
                procs = self._process_names(name, entry)
                if procs and self.backend.process_ids(procs - PROTECTED):
                    return fail(
                        f"{label} is running in the background with no open window. "
                        f"Say 'force close {name}' to end it.",
                    )
                return fail(f"{label} doesn't seem to be open.", fallback=True)
            for w in windows:
                self.backend.close_window(w.hwnd)
            deadline = time.time() + 3
            remaining = windows
            while time.time() < deadline:
                remaining = [w for w in windows if self.backend.window_exists(w.hwnd)]
                if not remaining:
                    break
                time.sleep(0.2)
            count = len(windows)
            plural = f"{count} windows" if count > 1 else "it"
            if not remaining:
                return ok(f"Closed {label}." if count == 1 else f"Closed {label} ({plural}).")
            return ok(
                f"Asked {label} to close; {len(remaining)} window(s) are still open, "
                "probably asking you to save something."
            )
        except NotOnWindows as exc:
            return fail(str(exc))

    @tool(
        "Force an app to quit immediately. Unsaved work is lost. Only use when asked to force close or kill.",
        params={"name": "The app's everyday name"},
        risk=Risk.CONFIRM,
        confirm_label="Force close",
    )
    def force_close_app(self, name: str) -> ToolResult:
        try:
            entry = self.resolve(name)
            procs = self._process_names(name, entry) - PROTECTED
            pids = set(self.backend.process_ids(procs)) if procs else set()
            pids |= {w.pid for w in self.find_windows(name) if w.exe not in PROTECTED}
            if not pids:
                return fail(f"{entry.name if entry else name} isn't running.")
            killed = 0
            for pid in pids:
                try:
                    self.backend.kill(pid)
                    killed += 1
                except Exception as exc:  # already gone, or access denied
                    log.info("kill %s failed: %s", pid, exc)
            if not killed:
                return fail(f"Couldn't end {name}. It may need administrator rights.")
            return ok(f"Force closed {entry.name if entry else name}.")
        except NotOnWindows as exc:
            return fail(str(exc))

    def preview(self, tool_name: str, args: dict[str, Any]) -> str | None:
        if tool_name == "force_close_app":
            return f"Force close {args.get('name')}? Anything unsaved in it will be lost."
        return None

    @tool("Bring an open app's window to the front.", params={"name": "App name or window title words"},
          hides_popup=True)
    def switch_to_app(self, name: str) -> ToolResult:
        try:
            windows = self.find_windows(name)
            if not windows:
                return fail(f"{name} isn't open.", fallback=True)
            if self.backend.focus(windows[0].hwnd):
                return ok(f"Switched to {windows[0].title}.")
            return fail(f"Windows wouldn't let me switch to {name}.")
        except NotOnWindows as exc:
            return fail(str(exc))

    @tool("List the apps that currently have open windows.")
    def list_open_apps(self) -> ToolResult:
        try:
            windows = self.backend.windows()
        except NotOnWindows as exc:
            return fail(str(exc))
        if not windows:
            return ok("No app windows are open.")
        groups: dict[str, list[str]] = {}
        for w in windows:
            groups.setdefault(w.exe or w.title, []).append(w.title)
        lines = []
        for exe, titles in groups.items():
            first = titles[0] if len(titles[0]) < 60 else titles[0][:57] + "…"
            more = f" (+{len(titles) - 1} more)" if len(titles) > 1 else ""
            lines.append(f"- **{exe}**: {first}{more}")
        return ok("Open apps:\n" + "\n".join(lines), data={"windows": [w.title for w in windows][:40]})

    @tool("Check whether an app is installed, or list installed apps matching some words.",
          params={"query": "App name or words to look for"})
    def find_installed_app(self, query: str) -> ToolResult:
        found = rank(self._clean(query), self._all_apps().keys(), limit=8, cutoff=70)
        if not found:
            return ok(f"I don't see anything like '{query}' installed.")
        names = [n for n, _ in found]
        return ok("Installed: " + ", ".join(names), data={"apps": names})

    # ----- quick commands -----

    def quick_rules(self) -> list[QuickRule]:
        def open_strict(m):
            target = m["t"]
            if is_simple(target) and self.confidence(target) >= 95:
                return "open_app", {"name": target}
            return None

        def open_loose(m):
            target = m["t"]
            if is_simple(target) and self.confidence(target) >= 85:
                return "open_app", {"name": target}
            return None

        def close(m):
            target = m["t"]
            if not is_simple(target) or normalize(target) in ("down", "it", "this", "everything", "all"):
                return None
            return "close_app", {"name": target}

        def force(m):
            return ("force_close_app", {"name": m["t"]}) if is_simple(m["t"]) else None

        def switch(m):
            return ("switch_to_app", {"name": m["t"]}) if is_simple(m["t"]) else None

        verbs_open = r"(?:open|launch|start|run|fire up)"
        return [
            QuickRule(verbs_open + r"\s+(?:up\s+)?(?P<t>.+)", open_strict, priority=40),
            QuickRule(verbs_open + r"\s+(?:up\s+)?(?P<t>.+)", open_loose, priority=60),
            QuickRule(r"(?:force\s+(?:close|quit)|kill)\s+(?P<t>.+)", force, priority=40),
            QuickRule(r"(?:close|quit|exit)\s+(?P<t>.+)", close, priority=45),
            QuickRule(r"(?:switch|go)\s+(?:back\s+)?to\s+(?P<t>.+)", switch, priority=55),
            QuickRule(r"(?:what|which)\s+apps\s+are\s+(?:open|running)|list\s+(?:open\s+|running\s+)?apps|show\s+open\s+apps",
                      lambda m: ("list_open_apps", {})),
        ]
