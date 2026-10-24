"""Walk through WinAuto like a new user, on a real Windows PC, and print what happens.

    python scripts/user_journey.py            # instant commands and launcher only
    python scripts/user_journey.py --ai       # also the built-in AI (downloads Qwen3-VL 4B, ~3 GB, once)

Uses a throwaway profile (WINAUTO_HOME), denies every approval card, and skips
anything that would lock, sleep or shut down the PC. Used by the "User journey"
workflow on GitHub's Windows machines; safe to run on your own PC too.
"""

from __future__ import annotations

import os
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("WINAUTO_HOME", tempfile.mkdtemp(prefix="winauto-journey-"))

failures: list[str] = []


def line(text: str = "") -> None:
    print(text.encode("ascii", "replace").decode("ascii"), flush=True)


class Deny:
    """Approval cards: record what would be sent, then press Cancel."""

    def __init__(self) -> None:
        self.cards: list = []

    def confirm(self, request):
        from winauto.core.agent import Decision

        self.cards.append(request)
        line(f"    [card] {request.title} | {request.preview[:160]!r} | args={str(request.args)[:200]}")
        return Decision(False)


def run(rt, text: str, expect: str | None = None, expect_tool: str | None = None) -> None:
    started = time.monotonic()
    try:
        reply = rt.agent.handle(text)
    except Exception as exc:  # noqa: BLE001 - report every crash
        failures.append(f"{text}: crashed: {exc!r}")
        line(f"!!  {text!r} crashed: {exc!r}")
        return
    took = time.monotonic() - started
    steps = ", ".join(f"{s.tool}{'' if s.result.ok else ' (failed)'}" for s in reply.steps) or "-"
    model = " +AI" if reply.used_model else ""
    line(f">>  {text!r}  [{took:.1f}s{model}] tools: {steps}")
    for row in (reply.text or "(no text)").splitlines()[:12]:
        line(f"      {row}")
    if expect and expect.lower() not in (reply.text or "").lower():
        failures.append(f"{text}: expected {expect!r} in reply")
    if expect_tool and expect_tool not in [s.tool for s in reply.steps]:
        failures.append(f"{text}: expected tool {expect_tool}")


def launcher(rt, queries: list[str]) -> None:
    line("\n=== Launcher results while typing")
    for q in queries:
        started = time.monotonic()
        results = rt.launcher.search(q)[:4]
        took = (time.monotonic() - started) * 1000
        shown = " | ".join(f"{r.title} [{r.kind}]" for r in results)
        line(f"  {q!r:24} {took:5.0f} ms  {shown}")


def instant(rt) -> None:
    from winauto.adapters.winos.apps import list_windows

    line("\n=== Instant commands (no AI)")
    apps = rt.ctx.skill("apps")
    apps.refresh()
    line(f"  installed apps found: {len(apps.backend.installed())}")
    run(rt, "open notepad", expect_tool="open_app")
    time.sleep(2)
    line(f"  windows now: {[w.title for w in list_windows()][:8]}")
    run(rt, "what apps are open", expect_tool="list_open_apps")
    run(rt, "close notepad", expect_tool="close_app")
    run(rt, "open calculator", expect_tool="open_app")
    time.sleep(2)
    run(rt, "close calculator", expect_tool="close_app")
    for text in ["todo buy milk tomorrow", "show my todos", "note the wifi password is on the router",
                 "remind me to stretch in 30 minutes", "show my reminders", "12*7", "10 km to miles",
                 "time in tokyo", "volume 30", "mute", "unmute", "dark mode on", "dark mode off",
                 "battery", "why is my laptop so slow", "what's my ip", "take a screenshot",
                 "open downloads", "find my resume pdf", "organize my downloads", "generate a password",
                 "what's on my clipboard", "clipboard history", "100 usd to npr", "define serendipity",
                 "wiki kathmandu", "news about cricket", "what's the weather in kathmandu",
                 "help", "what can you do"]:
        run(rt, text)


def ai(rt) -> None:
    line("\n=== Built-in AI")
    ai = rt.local_ai
    ai.set_model("qwen3-vl-4b")
    started = time.monotonic()
    ai.install()
    line(f"  download/verify: {time.monotonic() - started:.0f}s")
    started = time.monotonic()
    ai.ensure_running()
    line(f"  engine loaded: {time.monotonic() - started:.0f}s")
    rt.ctx.host.selection = ""
    for text in ["what is the capital of france?",
                 "add buy eggs and call the bank to my todo list",
                 "what do I need to do?",
                 "email ram@example.com that the meeting moved to 3pm",
                 "who won the football world cup in 2022?",
                 "what's on my screen?",
                 "open notepad and set the volume to 40",
                 "close it"]:
        run(rt, text)
    rt.ctx.host.selection = "i has went to the shop yesterday and buyed three apple"
    run(rt, "fix the grammar")
    run(rt, "translate this to nepali")
    ai.stop()


def main() -> int:
    from winauto.config import Config
    from winauto.runtime import Runtime

    cfg = Config()
    cfg.user_name = "Journey Tester"
    deny = Deny()
    rt = Runtime(deny, config=cfg)
    rt.start()
    line(f"WinAuto journey on {sys.platform}, profile {os.environ['WINAUTO_HOME']}")
    line(f"AI setup: {rt.ai_setup.status().state}; this PC: {rt.ai_setup.hardware()}; "
         f"model picked: {rt.ai_setup.recommended().name}")
    launcher(rt, ["note", "notepad", "calc", "paint", "settings", "control panel", "task manager", "cmd",
                  "powershell", "edge", "explorer", "word", "blue", "wifi", "display", "volume", "vol 50",
                  "remind", "todo", "help", "12*7", "shutdown", ":smile", "/report"])
    instant(rt)
    if "--ai" in sys.argv:
        ai(rt)
    rt.stop()
    line("\n=== Result")
    for f in failures:
        line(f"FAIL {f}")
    line("OK" if not failures else f"{len(failures)} problem(s)")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
