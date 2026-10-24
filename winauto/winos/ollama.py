"""Start Ollama if it's installed but not running."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

from winauto.winos import CREATE_NO_WINDOW, IS_WINDOWS


def find_ollama() -> Path | None:
    """The Ollama tray app (preferred) or the ollama command."""
    candidates = []
    local = os.environ.get("LOCALAPPDATA")
    if local:
        candidates.append(Path(local) / "Programs" / "Ollama" / "ollama app.exe")
        candidates.append(Path(local) / "Programs" / "Ollama" / "ollama.exe")
    which = shutil.which("ollama")
    if which:
        candidates.append(Path(which))
    return next((c for c in candidates if c.exists()), None)


def start_ollama() -> bool:
    if not IS_WINDOWS:
        return False
    exe = find_ollama()
    if exe is None:
        return False
    args = [str(exe)] if exe.name.lower() == "ollama app.exe" else [str(exe), "serve"]
    subprocess.Popen(args, creationflags=CREATE_NO_WINDOW | 0x00000008)  # DETACHED_PROCESS
    return True
