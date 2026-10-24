"""Focus mode / Pomodoro: timed work sessions that keep distracting apps out of the way."""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Callable

from winauto.core.skill import QuickRule, Skill, ToolResult, ok, tool
from winauto.adapters.winos import NotOnWindows

log = logging.getLogger(__name__)


@dataclass
class FocusState:
    phase: str  # "work" or "break"
    round: int
    rounds: int
    work_minutes: int
    break_minutes: int
    ends_at: datetime
    blocked: list[str] = field(default_factory=list)


class FocusSkill(Skill):
    name = "focus"
    description = "Focus sessions (Pomodoro) that minimise distracting apps."
    keywords = r"\b(focus|pomodoro|concentrate|deep work|distract|study session|work session)\b"

    def __init__(self, ctx: Any, clock: Callable[[], datetime] = datetime.now, apps: Any = None):
        super().__init__(ctx)
        self.clock = clock
        self._apps = apps
        self.state: FocusState | None = None
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._last_nag: dict[str, float] = {}

    def apps(self):
        return self._apps or self.ctx.services.get("skills", {}).get("apps")

    # ----- background loop -----

    def start(self) -> None:
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True, name="focus")
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _loop(self) -> None:
        while not self._stop.wait(3.0):
            try:
                self.tick()
            except Exception:
                log.exception("focus tick failed")

    def tick(self) -> None:
        with self._lock:
            st = self.state
            if st is None:
                return
            now = self.clock()
            if now >= st.ends_at:
                self._advance(st, now)
                return
        if st.phase == "work":
            self._keep_blocked_apps_away(st)

    def _advance(self, st: FocusState, now: datetime) -> None:
        if st.phase == "work":
            if st.round >= st.rounds:
                self.state = None
                self.ctx.notify("🎯 Focus session done", f"Great work! {st.rounds} round(s) of {st.work_minutes} min.")
                return
            st.phase, st.ends_at = "break", now + timedelta(minutes=st.break_minutes)
            self.ctx.notify("☕ Break time", f"Take {st.break_minutes} minutes. Round {st.round + 1} starts after.")
        else:
            st.round += 1
            st.phase, st.ends_at = "work", now + timedelta(minutes=st.work_minutes)
            self.ctx.notify("🎯 Back to focus", f"Round {st.round} of {st.rounds}: {st.work_minutes} minutes.")

    def _keep_blocked_apps_away(self, st: FocusState) -> None:
        apps = self.apps()
        if not apps or not st.blocked:
            return
        for name in st.blocked:
            try:
                windows = apps.find_windows(name)
            except NotOnWindows:
                return
            except Exception:
                continue
            for w in windows:
                try:
                    from winauto.adapters.winos.windows import WindowsLayout

                    WindowsLayout().show(w.hwnd, 6)  # minimise
                except Exception:
                    continue
                if time.time() - self._last_nag.get(name, 0) > 120:
                    self._last_nag[name] = time.time()
                    left = max(1, int((st.ends_at - self.clock()).total_seconds() // 60))
                    self.ctx.notify("Focus mode", f"{name.title()} is paused for {left} more min.")

    # ----- tools -----

    @tool(
        "Start a focus session (Pomodoro). Distracting apps get minimised until it ends.",
        params={"minutes": "Work length (default 25)", "rounds": "How many work rounds (default 1)",
                "break_minutes": "Break between rounds (default 5)",
                "block_apps": "Apps to keep away (default: your list in Settings)"},
    )
    def start_focus(self, minutes: int = 25, rounds: int = 1, break_minutes: int = 5,
                    block_apps: list[str] | None = None) -> ToolResult:
        minutes = max(1, min(minutes, 240))
        rounds = max(1, min(rounds, 8))
        blocked = [a.strip() for a in (block_apps or self.ctx.config.focus_block_apps) if a.strip()]
        now = self.clock()
        with self._lock:
            self.state = FocusState("work", 1, rounds, minutes, max(1, break_minutes), now + timedelta(minutes=minutes), blocked)
        ends = (now + timedelta(minutes=minutes)).strftime("%I:%M %p").lstrip("0")
        what = f"{rounds} × {minutes} min with {break_minutes} min breaks" if rounds > 1 else f"{minutes} minutes"
        keep = f" Keeping {', '.join(blocked)} out of the way." if blocked else ""
        return ok(f"🎯 Focus on: {what}. This round ends at {ends}.{keep}")

    @tool("Stop the focus session.")
    def stop_focus(self) -> ToolResult:
        with self._lock:
            was = self.state
            self.state = None
        return ok("Focus session stopped.") if was else ok("No focus session is running.")

    @tool("How much time is left in the focus session.")
    def focus_status(self) -> ToolResult:
        st = self.state
        if st is None:
            return ok("No focus session is running. Say “focus for 25 minutes” to start one.")
        left = max(0, int((st.ends_at - self.clock()).total_seconds()))
        phase = "Focus" if st.phase == "work" else "Break"
        return ok(f"{phase}: {left // 60}:{left % 60:02d} left (round {st.round} of {st.rounds}).")

    def quick_rules(self) -> list[QuickRule]:
        def start(m):
            args: dict[str, Any] = {}
            minutes = m["n"] or m["n2"]
            if minutes:
                args["minutes"] = int(minutes)
            if m["r"]:
                args["rounds"] = int(m["r"])
            return "start_focus", args

        return [
            QuickRule(r"(?:start\s+(?:a\s+)?)?(?:focus(?:\s+mode)?|pomodoro|deep\s+work)(?:\s+(?:session|timer))?"
                      r"(?:\s+for\s+(?P<n>\d+)\s*(?:min|mins|minutes))?(?:\s+(?:x|times)\s*(?P<r>\d+))?"
                      r"|focus\s+for\s+(?P<n2>\d+)\s*(?:min|mins|minutes)", start),
            QuickRule(r"(?:stop|end|cancel|quit)\s+(?:the\s+)?(?:focus(?:\s+mode)?|pomodoro|focus\s+session)", lambda m: ("stop_focus", {})),
            QuickRule(r"(?:how\s+(?:much|long)\s+(?:time\s+)?(?:is\s+)?left\s+(?:in|on)\s+(?:my\s+)?(?:focus|pomodoro)|focus\s+status)",
                      lambda m: ("focus_status", {})),
        ]
