"""Commands the user typed recently, for the home screen's "Recent" list."""

from __future__ import annotations

import logging

from winauto.core.context import Store
from winauto.core.timeparse import now_iso

log = logging.getLogger(__name__)


class CommandHistory:
    KEEP = 200

    def __init__(self, db: Store):
        self.db = db

    def record(self, text: str) -> None:
        text = text.strip()
        if not text:
            return
        try:
            self.db.execute("DELETE FROM history WHERE text = ?", (text,))
            self.db.execute("INSERT INTO history(text, created_at) VALUES(?, ?)", (text, now_iso()))
            self.db.execute(f"DELETE FROM history WHERE id NOT IN (SELECT id FROM history ORDER BY id DESC LIMIT {self.KEEP})")
        except Exception:
            log.debug("couldn't record history", exc_info=True)

    def recent(self, limit: int = 5) -> list[str]:
        try:
            rows = self.db.query("SELECT text FROM history ORDER BY id DESC LIMIT ?", (limit,))
        except Exception:
            log.debug("couldn't read history", exc_info=True)
            return []
        return [r["text"] for r in rows]
