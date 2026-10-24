"""`WinAuto.exe --selftest`: checks a packaged build works, without touching your data.

Runs a few quick commands against a throwaway data folder and writes the
results to selftest.txt there. Exit code 0 means everything passed.
"""

from __future__ import annotations

import os
import sys
import tempfile
import traceback
from pathlib import Path


def main() -> int:
    home = Path(tempfile.mkdtemp(prefix="winauto-selftest-"))
    os.environ["WINAUTO_HOME"] = str(home)
    lines: list[str] = []
    failures = 0

    def check(name: str, fn) -> None:
        nonlocal failures
        try:
            detail = fn()
            lines.append(f"PASS {name}: {detail}")
        except Exception:
            failures += 1
            lines.append(f"FAIL {name}:\n{traceback.format_exc()}")

    try:
        from winauto.core.agent import DenyAll
        from winauto.runtime import Runtime

        rt = Runtime(DenyAll())
    except Exception:
        report = "FAIL startup:\n" + traceback.format_exc()
        (home / "selftest.txt").write_text(report, encoding="utf-8")
        if sys.stdout is not None:
            print(report)
        return 1
    expected_skills = {"apps", "notes", "web", "utils", "system", "contacts", "reminders", "email", "whatsapp"}

    def skills():
        loaded = {s.name for s in rt.registry.skills}
        missing = expected_skills - loaded
        assert not missing, f"skills failed to load: {missing}"
        return f"{len(rt.registry.tools)} tools from {sorted(loaded)}"

    check("skills", skills)

    def quick(command: str, expect: str):
        def run():
            reply = rt.agent.handle(command)
            assert expect in reply.text, reply.text
            return reply.text.splitlines()[0]
        return run

    check("todo", quick("todo selftest item tomorrow 5pm", "Added todo #1"))
    check("list", quick("show my todos", "selftest item"))
    check("calc", quick("what is 12*7", "84"))
    check("convert", quick("convert 1 km to m", "1,000"))
    check("time", quick("time in tokyo", "Tokyo"))

    def windows_layer():
        if sys.platform != "win32":
            return "skipped (not Windows)"
        from winauto.winos.apps import list_windows
        from winauto.winos.powershell import run_powershell

        out = run_powershell("Write-Output ok").stdout.strip()
        assert out == "ok", out
        return f"powershell ok, {len(list_windows())} windows"

    check("windows", windows_layer)

    def secrets_store():
        if sys.platform != "win32":
            return "skipped (not Windows)"
        import keyring

        backend = type(keyring.get_keyring()).__module__
        assert "fail" not in backend and "null" not in backend, backend
        return backend

    check("credential manager", secrets_store)

    def ui():
        if sys.platform != "win32":
            os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PySide6.QtWidgets import QApplication

        from winauto.ui.popup import PopupWindow
        from winauto.ui.theme import DARK

        app = QApplication.instance() or QApplication([])
        popup = PopupWindow(DARK)
        popup.add_bot("hello")
        app.processEvents()
        return f"popup ok ({app.platformName()})"

    check("ui", ui)
    rt.stop()
    report = "\n".join(lines) + f"\n\n{'OK' if not failures else f'{failures} FAILED'}\n"
    (home / "selftest.txt").write_text(report, encoding="utf-8")
    if sys.stdout is not None:
        print(report)
        print(f"Report: {home / 'selftest.txt'}")
    return 1 if failures else 0
