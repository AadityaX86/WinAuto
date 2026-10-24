"""Snap, maximize, minimize and arrange windows; screenshots."""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any, Literal

from winauto.adapters.winos import NotOnWindows
from winauto.adapters.winos.folders import folder as known_folder
from winauto.adapters.winos.shell import open_app_uri
from winauto.core.context import Context
from winauto.core.skill import QuickRule, Skill, ToolResult, fail, ok, tool

log = logging.getLogger(__name__)

POSITIONS = ("left", "right", "top", "bottom", "top left", "top right", "bottom left", "bottom right",
             "center", "maximize", "minimize", "restore")


def layout_rect(position: str, area: tuple[int, int, int, int]) -> tuple[int, int, int, int]:
    """(x, y, w, h) for a snap position inside a work area."""
    left, top, right, bottom = area
    w, h = right - left, bottom - top
    half_w, half_h = w // 2, h // 2
    return {
        "left": (left, top, half_w, h),
        "right": (left + half_w, top, w - half_w, h),
        "top": (left, top, w, half_h),
        "bottom": (left, top + half_h, w, h - half_h),
        "top left": (left, top, half_w, half_h),
        "top right": (left + half_w, top, w - half_w, half_h),
        "bottom left": (left, top + half_h, half_w, h - half_h),
        "bottom right": (left + half_w, top + half_h, w - half_w, h - half_h),
        "center": (left + w // 6, top + h // 8, w * 2 // 3, h * 3 // 4),
    }[position]


class WindowLayoutSkill(Skill):
    name = "windows"
    icon = "layout"
    description = "Arrange windows and take screenshots."
    keywords = r"\b(snap|maximi[sz]e|minimi[sz]e|restore|side by side|window|windows|screenshot|screen ?shot|snip|desktop|half|corner)\b"
    prompt_hint = "Windows: leave 'app' empty to mean the window the user was using before opening WinAuto."

    def __init__(self, ctx: Context, backend: Any = None, apps: Any = None):
        super().__init__(ctx)
        if backend is None:
            from winauto.adapters.winos.windows import WindowsLayout

            backend = WindowsLayout()
        self.backend = backend
        self._apps = apps

    def _apps_skill(self):
        return self._apps or self.ctx.skill("apps")

    def _window(self, app: str) -> tuple[int | None, str]:
        """The window to act on: an app's, or the one in use before WinAuto opened."""
        if app.strip() and app.strip().lower() not in ("this", "this window", "it", "current", "the window", "window"):
            wins = self._apps_skill().find_windows(app)
            if not wins:
                return None, f"{app} isn't open."
            return wins[0].hwnd, wins[0].title
        hwnd = self.ctx.host.last_window
        return (hwnd, "the window") if hwnd else (None, "I don't know which window you mean. Name the app.")

    @tool(
        "Snap, maximize, minimize or restore a window.",
        params={"position": "left, right, top, bottom, top left, top right, bottom left, bottom right, center, maximize, minimize, restore",
                "app": "App name; empty = the window in use before WinAuto opened"},
    )
    def arrange_window(self, position: Literal["left", "right", "top", "bottom", "top left", "top right",
                                               "bottom left", "bottom right", "center", "maximize", "minimize",
                                               "restore"], app: str = "") -> ToolResult:
        try:
            hwnd, label = self._window(app)
            if not hwnd:
                return fail(label, fallback=True)
            if position in ("maximize", "minimize", "restore"):
                self.backend.show(hwnd, {"maximize": 3, "minimize": 6, "restore": 9}[position])
                verb = {"maximize": "Maximized", "minimize": "Minimized", "restore": "Restored"}[position]
                return ok(f"{verb} {app or 'it'}.")
            x, y, w, h = layout_rect(position, self.backend.work_area(hwnd))
            self.backend.place(hwnd, x, y, w, h)
            return ok(f"Moved {app or 'it'} to the {position}.")
        except NotOnWindows as exc:
            return fail(str(exc))

    @tool("Put two apps side by side (first on the left, second on the right).",
          params={"left_app": "App for the left half", "right_app": "App for the right half"})
    def side_by_side(self, left_app: str, right_app: str) -> ToolResult:
        first = self.arrange_window("left", left_app)
        if not first.ok:
            return first
        second = self.arrange_window("right", right_app)
        if not second.ok:
            return second
        return ok(f"{left_app} on the left, {right_app} on the right.")

    @tool("Minimize every window to show the desktop, or bring them back.",
          params={"restore": "true to bring the windows back"})
    def show_desktop(self, restore: bool = False) -> ToolResult:
        try:
            from winauto.adapters.winos.keyboard import press

            press("win+shift+m" if restore else "win+m")
        except NotOnWindows as exc:
            return fail(str(exc))
        return ok("Windows restored." if restore else "Minimized everything.")

    @tool("Take a screenshot and save it to Pictures\\Screenshots. 'snip' lets the user draw a box (copied to clipboard).",
          params={"what": "screen (all monitors), window (the window in use), or snip"})
    def take_screenshot(self, what: Literal["screen", "window", "snip"] = "screen") -> ToolResult:
        try:
            if what == "snip":
                if not open_app_uri("ms-screenclip:"):
                    return fail("Snipping needs the Windows Snipping Tool.")
                return ok("Draw a box around what you want. It'll be copied to your clipboard.")
            hwnd = None
            if what == "window":
                hwnd, label = self._window("")
                if not hwnd:
                    return fail(label)
            # Give the popup a moment to get out of the way.
            if self.ctx.host.hide():
                time.sleep(0.4)
            target = known_folder("screenshots") or Path.home() / "Pictures" / "Screenshots"
            path = self.backend.screenshot(target, hwnd)
        except NotOnWindows as exc:
            return fail(str(exc))
        except (OSError, AttributeError) as exc:
            return fail(f"Couldn't take the screenshot: {exc}")
        return ok(f"Saved screenshot: {path.name} (in {path.parent}).", data={"path": str(path)})

    def quick_rules(self) -> list[QuickRule]:
        pos = r"(?P<p>left|right|top|bottom|top left|top right|bottom left|bottom right|center|middle)"

        def snap(m):
            p = m["p"].lower().replace("middle", "center")
            return "arrange_window", {"position": p, "app": (m["app"] or "").strip()}

        def size(m):
            verb = m["v"].lower()
            position = ("maximize" if verb.startswith("maxim") or verb.startswith("full")
                        else "minimize" if verb.startswith("minim") else "restore")
            app = (m["app"] or "").strip()
            if app.lower() in ("all", "everything", "all windows"):
                return ("show_desktop", {}) if position == "minimize" else None
            return "arrange_window", {"position": position, "app": app}

        return [
            QuickRule(rf"(?:snap|move|put)\s+(?P<app>.+?)?\s*(?:to\s+)?(?:the\s+)?{pos}(?:\s+(?:half|side|corner))?",
                      snap, priority=40),
            QuickRule(r"(?P<v>maximi[sz]e|minimi[sz]e|restore|full ?screen)(?:\s+(?P<app>.+))?", size, priority=40),
            QuickRule(r"(?:put\s+)?(?P<a>[\w ]+?)\s+and\s+(?P<b>[\w ]+?)\s+side\s+by\s+side",
                      lambda m: ("side_by_side", {"left_app": m["a"].strip(), "right_app": m["b"].strip()}), priority=40),
            QuickRule(r"show\s+(?:the\s+)?desktop|minimi[sz]e\s+(?:all|everything)", lambda m: ("show_desktop", {}), priority=35),
            QuickRule(r"(?:bring\s+back|restore)\s+(?:all\s+)?(?:my\s+)?windows", lambda m: ("show_desktop", {"restore": True}), priority=35),
            QuickRule(r"(?:take\s+a\s+)?(?:screenshot|screen\s*shot|screen\s*grab)(?:\s+of\s+(?:the\s+|my\s+)?(?P<w>screen|window|this window))?",
                      lambda m: ("take_screenshot", {"what": "window" if m["w"] and "window" in m["w"] else "screen"})),
            QuickRule(r"(?:take\s+a\s+)?(?:screen\s+)?snip|snipping|screenshot\s+(?:a\s+)?(?:part|area|region)",
                      lambda m: ("take_screenshot", {"what": "snip"})),
        ]
