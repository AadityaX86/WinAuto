"""What every skill gets from the app, through typed ports instead of imports.

A skill never imports the UI, the runtime, an adapter's database class or
another skill. Everything it needs from outside its own module comes in
through its `Context`:

    ctx.config       the user's settings (winauto.config.Config)
    ctx.db           a Store: the SQLite database in the app, in-memory in tests
    ctx.data_dir     folder for the skill's own files
    ctx.notify       show a desktop notification
    ctx.host         the desktop shell: show/hide the popup, the window the user
                     was in, the text they had selected
    ctx.assistant    the engine: ask the model, run a tool, match a quick command
                     (None when there is no engine, e.g. in unit tests)
    ctx.skill(name)  another skill, for the few that build on each other

The composition roots (winauto/runtime.py and winauto/app.py) fill these in.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Iterable, Protocol

from winauto.config import Config

if TYPE_CHECKING:
    from winauto.core.llm import ToolCall
    from winauto.core.skill import Skill, ToolResult

log = logging.getLogger(__name__)


class Store(Protocol):
    """Storage the skills use. Implemented by winauto.adapters.storage.db.Database.

    Each skill owns its tables; add new tables as a migration at the end of
    winauto/adapters/storage/db.py:MIGRATIONS.
    """

    def execute(self, sql: str, params: Iterable[Any] = ()) -> int:
        """Run a write. Returns the new row id for INSERT, the changed row count otherwise."""
        ...

    def query(self, sql: str, params: Iterable[Any] = ()) -> list[dict[str, Any]]: ...

    def one(self, sql: str, params: Iterable[Any] = ()) -> dict[str, Any] | None: ...

    def get_value(self, key: str, default: str | None = None) -> str | None:
        """Small key/value settings and caches (the kv table)."""
        ...

    def set_value(self, key: str, value: str) -> None: ...


class Assistant(Protocol):
    """The engine, as seen by skills. Implemented by winauto.runtime.Runtime."""

    def complete(self, system: str, user: str, images: list[str] | None = None,
                 model: str | None = None, stream: bool = False) -> str:
        """One question to the model without tools. `stream` shows the answer in the popup as it's written.
        Raises winauto.core.llm.LLMError if the model can't be reached."""
        ...

    def run_tool(self, call: ToolCall) -> ToolResult:
        """Run any tool by name, with the same approval cards as when the AI calls it."""
        ...

    def match_command(self, text: str) -> ToolCall | None:
        """The quick command (no AI) that `text` means, if there is one."""
        ...


@dataclass
class Host:
    """The desktop shell around the skills. The app wires in the popup; tests and the CLI leave the defaults."""

    show_popup: Callable[[], None] | None = None
    hide_popup: Callable[[], None] | None = None
    # The window that was in front before WinAuto opened (for pasting, snapping, screenshots).
    last_window: int | None = None
    # Text the user had selected when they opened writing tools (Ctrl+Alt+T).
    selection: str = ""

    def hide(self) -> bool:
        """Hide the popup. Returns True if there was one to hide (callers may need to wait for it to go)."""
        if self.hide_popup is None:
            return False
        self.hide_popup()
        return True

    def show(self) -> None:
        if self.show_popup is not None:
            self.show_popup()


def _log_notify(title: str, message: str) -> None:
    log.info("NOTIFY %s: %s", title, message)


@dataclass
class Context:
    config: Config
    db: Store
    data_dir: Path
    notify: Callable[[str, str], None] = field(default=_log_notify)
    host: Host = field(default_factory=Host)
    assistant: Assistant | None = None
    skills: dict[str, Skill] = field(default_factory=dict)

    def skill(self, name: str) -> Any:
        """Another loaded skill by name (e.g. "calendar"), or None if it's turned off.

        Typed as Any on purpose: callers use that skill's public methods by duck typing,
        and must handle None.
        """
        return self.skills.get(name)
