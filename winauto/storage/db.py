"""Local SQLite database for notes, todos, contacts, reminders..."""

from __future__ import annotations

import sqlite3
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

# Each entry upgrades the schema by one version. Never edit old entries;
# append new ones so existing databases upgrade in place.
MIGRATIONS: list[str] = [
    # 1: notes and todos
    """
    CREATE TABLE notes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT NOT NULL DEFAULT '',
        body TEXT NOT NULL,
        tags TEXT NOT NULL DEFAULT '',
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    );
    CREATE TABLE todos (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        text TEXT NOT NULL,
        due_at TEXT,
        due_has_time INTEGER NOT NULL DEFAULT 0,
        priority INTEGER NOT NULL DEFAULT 0,
        list TEXT NOT NULL DEFAULT 'inbox',
        done INTEGER NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL,
        done_at TEXT
    );
    CREATE TABLE kv (key TEXT PRIMARY KEY, value TEXT);
    """,
    # 2: contacts and reminders/timers
    """
    CREATE TABLE contacts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        nickname TEXT NOT NULL DEFAULT '',
        email TEXT NOT NULL DEFAULT '',
        phone TEXT NOT NULL DEFAULT '',
        discord TEXT NOT NULL DEFAULT '',
        notes TEXT NOT NULL DEFAULT '',
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    );
    CREATE TABLE reminders (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        text TEXT NOT NULL,
        kind TEXT NOT NULL DEFAULT 'reminder',
        due_at TEXT NOT NULL,
        repeat TEXT NOT NULL DEFAULT 'none',
        active INTEGER NOT NULL DEFAULT 1,
        created_at TEXT NOT NULL,
        fired_at TEXT
    );
    CREATE INDEX reminders_due ON reminders(active, due_at);
    """,
    # 3: routines
    """
    CREATE TABLE routines (
        name TEXT PRIMARY KEY COLLATE NOCASE,
        steps TEXT NOT NULL,
        created_at TEXT NOT NULL
    );
    """,
]


def now_iso() -> str:
    return datetime.now().replace(microsecond=0).isoformat(sep=" ")


class Database:
    def __init__(self, path: Path | str):
        self.path = str(path)
        self._lock = threading.RLock()
        self.conn = sqlite3.connect(self.path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        if self.path != ":memory:":
            self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA foreign_keys=ON")
        self._migrate()

    def _migrate(self) -> None:
        with self._lock:
            version = self.conn.execute("PRAGMA user_version").fetchone()[0]
            for i, script in enumerate(MIGRATIONS[version:], start=version + 1):
                self.conn.executescript("BEGIN;" + script + f"; PRAGMA user_version={i}; COMMIT;")

    @property
    def version(self) -> int:
        return self.conn.execute("PRAGMA user_version").fetchone()[0]

    def execute(self, sql: str, params: Iterable[Any] = ()) -> int:
        """Run a write. Returns lastrowid for inserts, rowcount otherwise."""
        with self._lock:
            cur = self.conn.execute(sql, tuple(params))
            self.conn.commit()
            if sql.lstrip().upper().startswith("INSERT"):
                return int(cur.lastrowid or 0)
            return cur.rowcount

    def query(self, sql: str, params: Iterable[Any] = ()) -> list[dict[str, Any]]:
        with self._lock:
            return [dict(r) for r in self.conn.execute(sql, tuple(params)).fetchall()]

    def one(self, sql: str, params: Iterable[Any] = ()) -> dict[str, Any] | None:
        rows = self.query(sql, params)
        return rows[0] if rows else None

    def get_value(self, key: str, default: str | None = None) -> str | None:
        row = self.one("SELECT value FROM kv WHERE key = ?", (key,))
        return row["value"] if row else default

    def set_value(self, key: str, value: str) -> None:
        self.execute(
            "INSERT INTO kv(key, value) VALUES(?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )

    def close(self) -> None:
        with self._lock:
            self.conn.close()
