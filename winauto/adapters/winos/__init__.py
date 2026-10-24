"""Thin wrappers around Windows APIs.

Everything Windows-specific lives here so the rest of the app can be tested
on any OS. Functions raise NotOnWindows when called elsewhere.
"""

from __future__ import annotations

import subprocess
import sys

IS_WINDOWS = sys.platform == "win32"

# Hide console windows for child processes (powershell, shutdown...).
CREATE_NO_WINDOW = 0x08000000 if IS_WINDOWS else 0


class NotOnWindows(RuntimeError):
    def __init__(self, what: str = "This"):
        super().__init__(f"{what} only works on Windows.")


def require_windows(what: str = "This") -> None:
    if not IS_WINDOWS:
        raise NotOnWindows(what)


def run_hidden(args: list[str], timeout: float = 30, input_text: str | None = None) -> subprocess.CompletedProcess:
    """Run a command without flashing a console window."""
    return subprocess.run(
        args,
        input=input_text,
        # A windowed exe has no console stdin to inherit ("handle is invalid").
        stdin=None if input_text is not None else subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=timeout,
        creationflags=CREATE_NO_WINDOW,
        encoding="utf-8",
        errors="replace",
    )
