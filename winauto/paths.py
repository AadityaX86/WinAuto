"""Where WinAuto keeps its files."""

from __future__ import annotations

import os
import sys
from pathlib import Path


def data_dir() -> Path:
    """Folder for config, database and logs.

    Windows: %APPDATA%\\WinAuto. Elsewhere (dev/tests): ~/.local/share/winauto.
    WINAUTO_HOME overrides both.
    """
    override = os.environ.get("WINAUTO_HOME")
    if override:
        path = Path(override)
    elif sys.platform == "win32":
        path = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming")) / "WinAuto"
    else:
        path = Path.home() / ".local" / "share" / "winauto"
    path.mkdir(parents=True, exist_ok=True)
    return path


def config_path() -> Path:
    return data_dir() / "config.json"


def db_path() -> Path:
    return data_dir() / "winauto.db"


def log_dir() -> Path:
    path = data_dir() / "logs"
    path.mkdir(parents=True, exist_ok=True)
    return path


def ai_dir() -> Path:
    """Folder for the built-in AI's engine and model files (several GB).

    Windows: %LOCALAPPDATA%\\WinAuto\\ai (big files don't belong in the roaming
    profile). Elsewhere: <data folder>/ai. WINAUTO_AI_DIR, then WINAUTO_HOME, override that
    (so test profiles can share one download).
    """
    override = os.environ.get("WINAUTO_HOME")
    if os.environ.get("WINAUTO_AI_DIR"):
        path = Path(os.environ["WINAUTO_AI_DIR"])
    elif override:
        path = Path(override) / "ai"
    elif sys.platform == "win32":
        path = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local")) / "WinAuto" / "ai"
    else:
        path = data_dir() / "ai"
    path.mkdir(parents=True, exist_ok=True)
    return path
