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
