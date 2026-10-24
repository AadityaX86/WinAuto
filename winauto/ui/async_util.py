"""Run slow work on a background thread and get the result back on the UI thread."""

from __future__ import annotations

import logging
import threading
from typing import Any, Callable

from PySide6.QtCore import QObject, Signal

log = logging.getLogger(__name__)
_alive: set["_Bridge"] = set()


class _Bridge(QObject):
    done = Signal(object, object)  # result, error


def run_async(fn: Callable[[], Any], on_done: Callable[[Any, BaseException | None], None]) -> None:
    """Must be called from the UI thread. `on_done(result, error)` runs on the UI thread."""
    bridge = _Bridge()
    _alive.add(bridge)

    def finish(result: Any, error: BaseException | None) -> None:
        _alive.discard(bridge)
        try:
            on_done(result, error)
        finally:
            bridge.deleteLater()

    bridge.done.connect(finish)

    def work() -> None:
        try:
            result = fn()
        except BaseException as exc:  # reported to on_done
            log.debug("background task failed", exc_info=True)
            bridge.done.emit(None, exc)
        else:
            bridge.done.emit(result, None)

    threading.Thread(target=work, daemon=True).start()
