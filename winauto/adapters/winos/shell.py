"""Opening files, folders, links and app URIs (whatsapp://, spotify:...) the way Explorer would."""

from __future__ import annotations

import os
import subprocess
import webbrowser

from winauto.adapters.winos import IS_WINDOWS


def open_target(target: str) -> None:
    """Open a path or URI with its default app. Raises OSError if nothing can open it."""
    if IS_WINDOWS:
        os.startfile(target)  # type: ignore[attr-defined]
    elif "://" in target or target.startswith(("http:", "https:", "mailto:")):
        webbrowser.open(target)
    else:
        subprocess.Popen(["xdg-open", target])


def open_app_uri(uri: str) -> bool:
    """Open an app URI like whatsapp://send?... Returns False if no app handles it (or not on Windows)."""
    if not IS_WINDOWS:
        return False
    try:
        os.startfile(uri)  # type: ignore[attr-defined]
    except OSError:
        return False
    return True


def open_url(url: str) -> None:
    webbrowser.open(url)


def move_to_trash(path: str) -> None:
    """Send a file or folder to the Recycle Bin."""
    from send2trash import send2trash

    send2trash(path)
