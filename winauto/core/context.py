"""Shared things every skill can use."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from winauto.config import Config
from winauto.storage.db import Database

log = logging.getLogger(__name__)


def _log_notify(title: str, message: str) -> None:
    log.info("NOTIFY %s: %s", title, message)


@dataclass
class Context:
    config: Config
    db: Database
    data_dir: Path
    # Shows a desktop notification (tray balloon / toast). The UI replaces this.
    notify: Callable[[str, str], None] = field(default=_log_notify)
    # Asks the UI to put text on the clipboard etc. Filled in by the app.
    services: dict[str, object] = field(default_factory=dict)
