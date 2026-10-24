"""Clipboard: read what you copied (to summarize, translate, rewrite...), copy text, history."""

from __future__ import annotations

import logging
import re
import threading
from collections import deque
from typing import Any

from winauto.core.skill import QuickRule, Skill, Suggestion, ToolResult, fail, ok, tool
from winauto.winos import NotOnWindows

log = logging.getLogger(__name__)
MAX_ITEMS = 25
MAX_CHARS = 8000


class ClipboardSkill(Skill):
    name = "clipboard"
    description = "Read and set the clipboard; clipboard history."
    keywords = (r"\b(clipboard|copied|copy|paste|this text|selected|summari[sz]e|translate|rewrite|rephrase|proofread|"
                r"fix (?:the )?grammar|explain this|shorten|make (?:it|this) (?:shorter|formal|polite))\b")
    prompt_hint = (
        "Clipboard: when the user says 'this', 'what I copied' or asks to summarize/translate/rewrite without "
        "giving the text, call get_clipboard first. Put finished text on the clipboard with set_clipboard so "
        "they can paste it."
    )

    def __init__(self, ctx: Any, backend: Any = None, watch: bool = True):
        super().__init__(ctx)
        if backend is None:
            from winauto.winos.clipboard import WindowsClipboard

            backend = WindowsClipboard()
        self.backend = backend
        self.history: deque[str] = deque(maxlen=MAX_ITEMS)
        self._watch = watch
        self._stop = threading.Event()
        self._last_seq = -1

    # History lives in memory only and is gone when WinAuto quits.
    def start(self) -> None:
        if self._watch:
            threading.Thread(target=self._poll, daemon=True, name="clipboard").start()

    def stop(self) -> None:
        self._stop.set()

    def _poll(self) -> None:
        while not self._stop.wait(1.0):
            try:
                self.capture()
            except NotOnWindows:
                return
            except Exception:
                log.debug("clipboard poll failed", exc_info=True)

    def capture(self) -> None:
        seq = self.backend.sequence()
        if seq == self._last_seq:
            return
        self._last_seq = seq
        text = self.backend.get_text()
        if text and text.strip():
            text = text[:MAX_CHARS]
            if text in self.history:
                self.history.remove(text)
            self.history.appendleft(text)

    @tool("Get the text currently on the clipboard (what the user copied).", final=False)
    def get_clipboard(self) -> ToolResult:
        try:
            text = self.backend.get_text()
        except (NotOnWindows, OSError) as exc:
            return fail(str(exc))
        if not text or not text.strip():
            return fail("The clipboard has no text. Copy something first (Ctrl+C).")
        clipped = text[:MAX_CHARS]
        preview = clipped if len(clipped) <= 600 else clipped[:600] + "…"
        return ok(f"Clipboard:\n{preview}", data={"text": clipped, "truncated": len(text) > MAX_CHARS})

    @tool("Put text on the clipboard so the user can paste it.", params={"text": "The text to copy"})
    def set_clipboard(self, text: str) -> ToolResult:
        try:
            self.backend.set_text(text)
        except (NotOnWindows, OSError) as exc:
            return fail(str(exc))
        return ok("Copied to the clipboard. Paste it with Ctrl+V.")

    @tool("Show recently copied text (this session).", params={"limit": "How many"})
    def clipboard_history(self, limit: int = 10) -> ToolResult:
        try:
            self.capture()
        except (NotOnWindows, OSError):
            pass
        items = list(self.history)[: max(1, min(limit, MAX_ITEMS))]
        if not items:
            return ok("Nothing copied yet since WinAuto started.")
        lines = []
        for i, t in enumerate(items, 1):
            one_line = " ".join(t.split())
            lines.append(f"{i}. {one_line[:90]}{'…' if len(one_line) > 90 else ''}")
        return ok("Recently copied (say 'copy item 2' to copy one again):\n" + "\n".join(lines))

    @tool("Copy an item from the clipboard history again.", params={"number": "Its number in the history list"})
    def copy_from_history(self, number: int) -> ToolResult:
        items = list(self.history)
        if not 1 <= number <= len(items):
            return fail(f"There's no item {number} in the clipboard history.")
        return self.set_clipboard(items[number - 1])

    def suggest(self, query: str) -> list[Suggestion]:
        q = query.strip().lower()
        m = re.match(r"^(?:clip(?:board)?(?:\s+history)?)\s*(.*)$", q)
        if not m:
            return []
        needle = m.group(1)
        out = []
        for i, text in enumerate(self.history, 1):
            one_line = " ".join(text.split())
            if needle and needle not in one_line.lower():
                continue
            out.append(Suggestion(title=one_line[:80] + ("…" if len(one_line) > 80 else ""), subtitle=f"Copied item {i}",
                                  tool="copy_from_history", args={"number": i}, kind="Copy", icon="clipboard",
                                  score=90 - i * 0.1))
        return out[:8]

    def quick_rules(self) -> list[QuickRule]:
        return [
            QuickRule(r"(?:what(?:'s| is)\s+(?:on|in)\s+(?:my\s+|the\s+)?clipboard|show\s+(?:my\s+|the\s+)?clipboard|read\s+(?:my\s+|the\s+)?clipboard)",
                      lambda m: ("get_clipboard", {})),
            QuickRule(r"(?:show\s+)?(?:my\s+)?clipboard\s+history|what\s+did\s+i\s+copy(?:\s+recently)?",
                      lambda m: ("clipboard_history", {})),
            QuickRule(r"copy\s+(?:item\s+|number\s+|#)?(?P<n>\d{1,2})(?:\s+(?:again|from\s+(?:the\s+)?(?:clipboard\s+)?history))?",
                      lambda m: ("copy_from_history", {"number": int(m["n"])})),
        ]
