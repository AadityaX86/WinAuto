"""Run Windows PowerShell scripts without a console window or quoting trouble."""

from __future__ import annotations

import base64
import subprocess

from winauto.winos import require_windows, run_hidden


def run_powershell(script: str, timeout: float = 30) -> subprocess.CompletedProcess:
    require_windows("PowerShell")
    encoded = base64.b64encode(script.encode("utf-16-le")).decode("ascii")
    return run_hidden(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-EncodedCommand", encoded],
        timeout=timeout,
    )
