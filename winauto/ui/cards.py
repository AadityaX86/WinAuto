"""Approval cards: what a risky tool is about to do, with editable fields and Approve/Cancel."""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import (
    Qt,
    Signal,
)
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from winauto.core.agent import ConfirmRequest, Decision
from winauto.ui.icons import pixmap
from winauto.ui.parts import (
    make_label,
)
from winauto.ui.theme import Palette

MULTILINE_FIELDS = {"body", "message", "text", "content", "note", "command"}


def editor_lines(text: str, minimum: int = 3, maximum: int = 8, width_chars: int = 72) -> int:
    """About how many lines `text` needs in the card's editor (wrapped at `width_chars`)."""
    needed = sum(max(1, -(-len(line) // width_chars)) for line in (text.splitlines() or [""]))
    return max(minimum, min(maximum, needed))


# ---------------- approval card ----------------

class ConfirmCard(QFrame):
    """'Send email?' card with editable fields and Approve / Cancel."""

    decided = Signal(object)  # Decision

    def __init__(self, request: ConfirmRequest, palette: Palette, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("Card")
        self.request = request
        self._fields: dict[str, Any] = {}
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(8)
        head = QHBoxLayout()
        badge = QLabel()
        badge.setPixmap(pixmap("alert" if request.confirm_label.lower() in ("delete", "force close", "yes, do it", "empty it")
                               else "check-circle", palette.accent, 18))
        head.addWidget(badge)
        head.addWidget(make_label(request.title, object_name="CardTitle"), 1)
        layout.addLayout(head)
        if request.preview:
            layout.addWidget(make_label(request.preview, object_name="Muted"))
        for name in request.editable:
            value = str(request.args.get(name, ""))
            layout.addWidget(make_label(name.replace("_", " ").capitalize(), object_name="Muted"))
            if name in MULTILINE_FIELDS or "\n" in value or len(value) > 80:
                edit = QPlainTextEdit(value)
                # Tall enough for the text (3 to 8 lines), so the buttons stay in view.
                lines = editor_lines(value, minimum=2 if name == "command" else 3)
                edit.setFixedHeight(edit.fontMetrics().lineSpacing() * lines + 30)
                edit.setTabChangesFocus(True)
            else:
                edit = QLineEdit(value)
            self._fields[name] = edit
            layout.addWidget(edit)
        row = QHBoxLayout()
        self.result_label = make_label("", object_name="Muted")
        row.addWidget(self.result_label, 1)
        self.cancel_btn = QPushButton("Cancel")
        self.ok_btn = QPushButton(request.confirm_label)
        self.ok_btn.setObjectName("Primary")
        self.ok_btn.setDefault(True)
        self.ok_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.cancel_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        row.addWidget(self.cancel_btn)
        row.addWidget(self.ok_btn)
        layout.addLayout(row)
        self.ok_btn.clicked.connect(self._approve)
        self.cancel_btn.clicked.connect(self._cancel)
        self._done = False

    @property
    def done(self) -> bool:
        return self._done

    def focus(self) -> None:
        first = next(iter(self._fields.values()), None)
        (first or self.ok_btn).setFocus()

    def _values(self) -> dict[str, str]:
        return {n: (e.toPlainText() if isinstance(e, QPlainTextEdit) else e.text()) for n, e in self._fields.items()}

    def _finish(self, decision: Decision, note: str) -> None:
        if self._done:
            return
        self._done = True
        for w in [self.ok_btn, self.cancel_btn, *self._fields.values()]:
            w.setEnabled(False)
        self.result_label.setText(note)
        self.decided.emit(decision)

    def _approve(self) -> None:
        values = self._values()
        changed = {k: v for k, v in values.items() if v != str(self.request.args.get(k, ""))}
        self._finish(Decision(True, changed or None), "✓ " + self.request.confirm_label)

    def _cancel(self) -> None:
        self._finish(Decision(False), "Cancelled")

    def expire(self) -> None:
        self._finish(Decision(False), "Cancelled")
