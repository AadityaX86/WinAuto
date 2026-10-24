"""Big file downloads that resume after a break and are checked against a SHA-256."""

from __future__ import annotations

import hashlib
import logging
import shutil
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Callable

log = logging.getLogger(__name__)

CHUNK = 1024 * 1024
USER_AGENT = "WinAuto (https://github.com/AadityaX86/WinAuto)"

# progress(done_bytes, total_bytes)
Progress = Callable[[int, int], None]


class DownloadError(Exception):
    """The download failed; the message is written for the user."""


class Cancelled(DownloadError):
    def __init__(self) -> None:
        super().__init__("Download cancelled.")


def free_space(folder: Path) -> int:
    folder.mkdir(parents=True, exist_ok=True)
    return shutil.disk_usage(folder).free


def _gb(n: int) -> str:
    return f"{n / 1e9:.1f} GB"


def download(url: str, dest: Path, sha256: str, size: int, progress: Progress | None = None,
             cancel: threading.Event | None = None, opener: Callable = urllib.request.urlopen,
             retries: int = 4) -> Path:
    """Download `url` to `dest`, resuming a partial `.part` file, and verify it.

    Returns `dest`. Raises DownloadError (or Cancelled) on failure; a partial file
    is kept so the next attempt continues where this one stopped.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists() and dest.stat().st_size == size:
        return dest
    part = dest.with_name(dest.name + ".part")
    have = part.stat().st_size if part.exists() else 0
    if have > size:
        part.unlink()
        have = 0
    needed = size - have
    if free_space(dest.parent) < needed + 200_000_000:
        raise DownloadError(
            f"Not enough free disk space: {_gb(needed)} is needed on {dest.anchor or dest.parent}, "
            f"{_gb(free_space(dest.parent))} is free.")

    attempt = 0
    while True:
        try:
            _fetch(url, part, size, progress, cancel, opener)
            break
        except Cancelled:
            raise
        except (urllib.error.URLError, OSError, TimeoutError, DownloadError) as exc:
            attempt += 1
            if attempt > retries:
                raise DownloadError(f"Download failed: {exc}. Check your internet connection and try again.") from exc
            wait = min(2 ** attempt, 30)
            log.warning("Download of %s failed (%s); retrying in %ss", url, exc, wait)
            _sleep(wait, cancel)

    if progress:
        progress(size, size)
    if _sha256(part, cancel) != sha256.lower():
        part.unlink(missing_ok=True)
        raise DownloadError("The downloaded file was damaged (checksum mismatch). Please try again.")
    part.replace(dest)
    return dest


def _fetch(url: str, part: Path, size: int, progress: Progress | None,
           cancel: threading.Event | None, opener: Callable) -> None:
    have = part.stat().st_size if part.exists() else 0
    if have >= size:
        return
    headers = {"User-Agent": USER_AGENT}
    if have:
        headers["Range"] = f"bytes={have}-"
    req = urllib.request.Request(url, headers=headers)
    with opener(req, timeout=60) as resp:
        status = getattr(resp, "status", 200)
        if have and status != 206:
            have = 0  # the server ignored the range: start over
        with open(part, "ab" if have else "wb") as fh:
            last = 0.0
            while True:
                if cancel is not None and cancel.is_set():
                    raise Cancelled()
                chunk = resp.read(CHUNK)
                if not chunk:
                    break
                fh.write(chunk)
                have += len(chunk)
                now = time.monotonic()
                if progress and now - last > 0.25:
                    progress(min(have, size), size)
                    last = now
    if have < size:
        raise DownloadError(f"the connection closed early ({_gb(have)} of {_gb(size)})")


def _sha256(path: Path, cancel: threading.Event | None) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(8 * CHUNK), b""):
            if cancel is not None and cancel.is_set():
                raise Cancelled()
            h.update(block)
    return h.hexdigest()


def _sleep(seconds: float, cancel: threading.Event | None) -> None:
    if cancel is None:
        time.sleep(seconds)
    elif cancel.wait(seconds):
        raise Cancelled()
