"""A box that records a keyboard shortcut: click it, press the keys, done."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import QLineEdit

K = Qt.Key
NAMED_KEYS = {
    K.Key_Space: "space", K.Key_Return: "enter", K.Key_Enter: "enter", K.Key_Insert: "insert",
    K.Key_Delete: "delete", K.Key_Home: "home", K.Key_End: "end", K.Key_PageUp: "pageup",
    K.Key_PageDown: "pagedown", K.Key_Up: "up", K.Key_Down: "down", K.Key_Left: "left", K.Key_Right: "right",
    K.Key_QuoteLeft: "`", K.Key_Semicolon: ";", K.Key_Slash: "/", K.Key_Period: ".", K.Key_Comma: ",",
    K.Key_Minus: "-", K.Key_Equal: "=", K.Key_BracketLeft: "[", K.Key_BracketRight: "]",
    K.Key_Backslash: "\\", K.Key_Apostrophe: "'", K.Key_Backspace: "backspace",
}
MODIFIER_KEYS = {K.Key_Control, K.Key_Alt, K.Key_Shift, K.Key_Meta, K.Key_AltGr}
M = Qt.KeyboardModifier
MODIFIERS = ((M.ControlModifier, "ctrl"), (M.AltModifier, "alt"), (M.ShiftModifier, "shift"), (M.MetaModifier, "win"))


def key_name(key: int) -> str | None:
    if K.Key_A <= key <= K.Key_Z or K.Key_0 <= key <= K.Key_9:
        return chr(key).lower()
    if K.Key_F1 <= key <= K.Key_F24:
        return f"f{key - K.Key_F1 + 1}"
    return NAMED_KEYS.get(K(key))


def combo_from(key: int, mods: Qt.KeyboardModifier) -> str | None:
    """Qt key + modifiers → 'ctrl+alt+space' (None for a key WinAuto can't use)."""
    name = key_name(key)
    if name is None:
        return None
    return "+".join([n for flag, n in MODIFIERS if mods & flag] + [name])


def pretty(combo: str) -> str:
    return " + ".join(p.capitalize() if len(p) > 1 else p.upper() for p in combo.split("+")) if combo else ""


class HotkeyEdit(QLineEdit):
    """Shows a shortcut like "Ctrl + Alt + Space"; click it and press new keys to change it.

    Backspace or Delete clears it (only when `can_clear`), Esc keeps the old one.
    """

    def __init__(self, combo: str, can_clear: bool = False):
        super().__init__()
        self._combo = combo
        self._can_clear = can_clear
        self.setPlaceholderText("Click, then press the keys" if not can_clear else "Off · click, then press the keys")
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.NoContextMenu)
        self.setAcceptDrops(False)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip("Click here, then press the shortcut you want, e.g. Ctrl + Alt + Space.")
        self._show()

    def combo(self) -> str:
        return self._combo

    def set_combo(self, combo: str) -> None:
        self._combo = combo
        self._show()

    def _show(self, partial: str = "") -> None:
        self.setText(partial or pretty(self._combo))

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802
        key, mods = event.key(), event.modifiers()
        plain = not (mods & (M.ControlModifier | M.AltModifier | M.ShiftModifier | M.MetaModifier))
        if plain and key in (K.Key_Tab, K.Key_Backtab):
            super().keyPressEvent(event)
            return
        if plain and key == K.Key_Escape:
            self._show()
            self.clearFocus()
            return
        if plain and key in (K.Key_Backspace, K.Key_Delete):
            if self._can_clear:
                self.set_combo("")
            return
        if key in MODIFIER_KEYS:
            held = [n for flag, n in MODIFIERS if mods & flag]
            self._show(pretty("+".join(held)) + " + …")
            return
        combo = combo_from(key, mods)
        if combo:
            self.set_combo(combo)
        event.accept()

    def keyReleaseEvent(self, event: QKeyEvent) -> None:  # noqa: N802
        if event.key() in MODIFIER_KEYS and not (event.modifiers() & ~M.KeypadModifier):
            self._show()  # let go without a main key: back to the saved shortcut
        event.accept()

    def focusOutEvent(self, event) -> None:  # noqa: N802
        self._show()
        super().focusOutEvent(event)
