from __future__ import annotations

import sys

import pytest

from winauto.adapters.winos.apps import AppEntry, WindowInfo
from winauto.core.quick import QuickMatcher
from winauto.core.registry import Registry
from winauto.skills.apps import AppsSkill


class FakeWindowsApps:
    def __init__(self):
        self.apps = [
            AppEntry("Google Chrome", "Chrome", "appid"),
            AppEntry("Chrome Remote Desktop", "crd", "appid"),
            AppEntry("Spotify", "SpotifyAB.SpotifyMusic_zpdnekdrzrea0!Spotify", "appid"),
            AppEntry("Visual Studio Code", r"C:\\Users\\me\\AppData\\Local\\Programs\\Microsoft VS Code\\Code.exe", "appid"),
            AppEntry("Word", "Microsoft.Office.WINWORD.EXE.15", "appid"),
            AppEntry("Adobe Photoshop 2025", "photoshop", "appid"),
            AppEntry("GitHub Desktop", "gh", "appid"),
        ]
        self.wins = [
            WindowInfo(1, "Inbox - Gmail - Google Chrome", 100, "chrome"),
            WindowInfo(2, "Docs - Google Chrome", 100, "chrome"),
            WindowInfo(3, "Password manager", 300, "keepass"),
            WindowInfo(4, "Budget 2026.xlsx - Excel", 400, "excel"),
        ]
        self.launched, self.closed, self.focused, self.killed = [], [], [], []
        self.stubborn = set()
        self.bg = {"spotify": [555]}

    def installed(self):
        return list(self.apps)

    def launch(self, entry):
        self.launched.append(entry.name)

    def windows(self):
        return [w for w in self.wins if w.hwnd not in self.closed or w.hwnd in self.stubborn]

    def close_window(self, hwnd):
        self.closed.append(hwnd)

    def window_exists(self, hwnd):
        return hwnd in self.stubborn or hwnd not in self.closed

    def focus(self, hwnd):
        self.focused.append(hwnd)
        return True

    def kill(self, pid):
        self.killed.append(pid)

    def process_ids(self, names):
        out = []
        for n in names:
            out += self.bg.get(n, [])
        out += [w.pid for w in self.wins if w.exe in names]
        return sorted(set(out))


@pytest.fixture
def apps(ctx):
    backend = FakeWindowsApps()
    skill = AppsSkill(ctx, backend)
    skill.refresh()
    return skill, backend


def test_resolve_names(apps):
    skill, _ = apps
    assert skill.resolve("chrome").name == "Google Chrome"
    assert skill.resolve("vs code").name == "Visual Studio Code"
    assert skill.resolve("the spotify app").name == "Spotify"
    assert skill.resolve("photoshop").name == "Adobe Photoshop 2025"
    assert skill.resolve("notepad").target == "notepad.exe"  # built-in fallback
    assert skill.resolve("zzzz qqq") is None


def test_user_alias(apps, ctx):
    skill, _ = apps
    ctx.config.app_aliases = {"music": "spotify", "game": r"D:\\Games\\game.exe"}
    assert skill.resolve("music").name == "Spotify"
    assert skill.resolve("game").kind == "path"


def test_open_launches_or_switches(apps):
    skill, backend = apps
    r = skill.open_app("spotify")
    assert r.ok and backend.launched == ["Spotify"] and r.message == "Opened Spotify."
    r = skill.open_app("chrome")
    assert r.ok and r.message == "Switched to Google Chrome." and backend.focused == [1]
    r = skill.open_app("spotfiy")
    assert r.ok and backend.launched[-1] == "Spotify"
    assert skill.resolve("discrod") is None  # not installed in the fake
    assert skill.resolve("photo shop").name == "Adobe Photoshop 2025"
    r = skill.open_app("blender")
    assert not r.ok and "couldn't find" in r.message


def test_close_app(apps):
    skill, backend = apps
    r = skill.close_app("chrome")
    assert r.ok and sorted(backend.closed) == [1, 2] and "2 windows" in r.message
    # Title words, whole words only
    r = skill.close_app("budget")
    assert r.ok and 4 in backend.closed
    assert not skill.close_app("word").ok  # must not close "Password manager"
    assert 3 not in backend.closed


def test_close_background_and_stubborn(apps):
    skill, backend = apps
    r = skill.close_app("spotify")
    assert not r.ok and "background" in r.message
    backend.stubborn = {4}
    r = skill.close_app("excel")
    assert r.ok and "still open" in r.message


def test_force_close_protects_system(apps):
    skill, backend = apps
    assert skill.force_close_app("spotify").ok and backend.killed == [555]
    assert not skill.force_close_app("explorer").ok


def test_quick_rules(apps):
    skill, _ = apps
    reg = Registry()
    reg.add(skill)
    q = QuickMatcher(reg)
    assert q.match("open spotify").arguments == {"name": "spotify"}
    assert q.match("please launch vs code").name == "open_app"
    # 'google' only loosely matches 'Google Chrome', so the web skill's rule (priority 50) gets it first.
    assert 85 <= skill.confidence("google") < 95
    assert q.match("open spotify and play jazz") is None
    assert q.match("close chrome").name == "close_app"
    assert q.match("force close spotify").name == "force_close_app"
    assert q.match("shut down") is None
    assert q.match("switch to chrome").name == "switch_to_app"


def test_list_open_apps(apps):
    skill, _ = apps
    r = skill.list_open_apps()
    assert "**chrome**" in r.message and "(+1 more)" in r.message


@pytest.mark.skipif(sys.platform == "win32", reason="checks the non-Windows message")
def test_not_on_windows_message(ctx):
    skill = AppsSkill(ctx)  # real backend on Linux
    r = skill.open_app("spotify")
    assert not r.ok
