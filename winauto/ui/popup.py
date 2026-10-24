"""The popup chat window you open with the hotkey."""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import QEvent, QObject, QPoint, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QCursor, QGuiApplication, QKeyEvent, QTextDocument
from PySide6.QtWidgets import (
    QFrame,
    QGraphicsDropShadowEffect,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from winauto.core.agent import AgentReply, ConfirmRequest, Decision
from winauto.ui.theme import Palette

WIDTH = 700
COMPACT_HEIGHT = 128
EXPANDED_HEIGHT = 580
MULTILINE_FIELDS = {"body", "message", "text", "content", "note"}


def _label(text: str, markdown: bool = False, object_name: str = "") -> QLabel:
    label = QLabel()
    label.setWordWrap(True)
    label.setTextFormat(Qt.TextFormat.MarkdownText if markdown else Qt.TextFormat.PlainText)
    label.setText(text)
    label.setTextInteractionFlags(
        Qt.TextInteractionFlag.TextSelectableByMouse | Qt.TextInteractionFlag.LinksAccessibleByMouse
    )
    label.setOpenExternalLinks(True)
    if object_name:
        label.setObjectName(object_name)
    return label


def _hard_breaks(text: str) -> str:
    """Keep single line breaks from the model (Markdown would merge the lines)."""
    out, in_code = [], False
    for line in text.split("\n"):
        if line.strip().startswith("```"):
            in_code = not in_code
        out.append(line if in_code or not line.strip() else line + "  ")
    return "\n".join(out)


def _fit_label(label: QLabel, max_width: int) -> None:
    """Word-wrapped labels otherwise wrap far too early; size them to their text."""
    label.ensurePolished()
    doc = QTextDocument()
    doc.setDefaultFont(label.font())
    if label.textFormat() == Qt.TextFormat.MarkdownText:
        doc.setMarkdown(label.text())
    else:
        doc.setPlainText(label.text())
    padding = 30  # bubble padding from the stylesheet plus a little slack
    label.setMinimumWidth(min(int(doc.idealWidth()) + padding, max_width))


class ConfirmCard(QFrame):
    """'Send email?' card with editable fields and Approve / Cancel."""

    decided = Signal(object)  # Decision

    def __init__(self, request: ConfirmRequest, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("Card")
        self.request = request
        self._fields: dict[str, Any] = {}
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(8)
        layout.addWidget(_label(request.title, object_name="CardTitle"))
        if request.preview:
            layout.addWidget(_label(request.preview))
        for name in request.editable:
            value = str(request.args.get(name, ""))
            layout.addWidget(_label(name.replace("_", " ").capitalize(), object_name="Muted"))
            if name in MULTILINE_FIELDS or "\n" in value or len(value) > 80:
                edit = QPlainTextEdit(value)
                edit.setMinimumHeight(110)
                edit.setTabChangesFocus(True)
            else:
                edit = QLineEdit(value)
            self._fields[name] = edit
            layout.addWidget(edit)
        row = QHBoxLayout()
        self.result_label = _label("", object_name="Muted")
        row.addWidget(self.result_label, 1)
        self.cancel_btn = QPushButton("Cancel")
        self.ok_btn = QPushButton(request.confirm_label)
        self.ok_btn.setObjectName("Primary")
        self.ok_btn.setDefault(True)
        row.addWidget(self.cancel_btn)
        row.addWidget(self.ok_btn)
        layout.addLayout(row)
        self.ok_btn.clicked.connect(self._approve)
        self.cancel_btn.clicked.connect(self._cancel)
        self._done = False

    def focus(self) -> None:
        first = next(iter(self._fields.values()), None)
        (first or self.ok_btn).setFocus()

    def _values(self) -> dict[str, str]:
        out = {}
        for name, edit in self._fields.items():
            out[name] = edit.toPlainText() if isinstance(edit, QPlainTextEdit) else edit.text()
        return out

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


class _HistoryFilter(QObject):
    """Up/Down in the input box recalls earlier commands."""

    def __init__(self, popup: "PopupWindow"):
        super().__init__(popup)
        self.popup = popup

    def eventFilter(self, obj, event) -> bool:  # noqa: N802 (Qt name)
        if event.type() == QEvent.Type.KeyPress and isinstance(event, QKeyEvent):
            if event.key() == Qt.Key.Key_Up:
                self.popup.recall(-1)
                return True
            if event.key() == Qt.Key.Key_Down:
                self.popup.recall(1)
                return True
        return False


class PopupWindow(QWidget):
    submitted = Signal(str)
    stop_requested = Signal()
    new_chat_requested = Signal()
    settings_requested = Signal()

    def __init__(self, palette: Palette):
        super().__init__(None)
        self.palette_ = palette
        self.setWindowTitle("WinAuto")
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self._busy = False
        self._history: list[str] = []
        self._history_pos = 0
        self._drag_from: QPoint | None = None

        outer = QVBoxLayout(self)
        outer.setContentsMargins(16, 16, 16, 16)
        self.panel = QFrame()
        self.panel.setObjectName("Panel")
        shadow = QGraphicsDropShadowEffect(self.panel)
        shadow.setBlurRadius(28)
        shadow.setOffset(0, 6)
        shadow.setColor(QColor(0, 0, 0, 120))
        self.panel.setGraphicsEffect(shadow)
        outer.addWidget(self.panel)

        layout = QVBoxLayout(self.panel)
        layout.setContentsMargins(14, 10, 14, 14)
        layout.setSpacing(8)

        # Header
        self.header = QWidget()
        header = QHBoxLayout(self.header)
        header.setContentsMargins(0, 0, 0, 0)
        title = QLabel("WinAuto")
        title.setObjectName("Title")
        self.status = QLabel("")
        self.status.setObjectName("Status")
        header.addWidget(title)
        header.addSpacing(8)
        header.addWidget(self.status, 1)
        for text, tip, signal in (
            ("＋", "New chat", self.new_chat_requested),
            ("⚙", "Settings", self.settings_requested),
        ):
            btn = QPushButton(text)
            btn.setObjectName("Icon")
            btn.setToolTip(tip)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.clicked.connect(signal.emit)
            header.addWidget(btn)
        close = QPushButton("✕")
        close.setObjectName("Icon")
        close.setToolTip("Hide (Esc)")
        close.clicked.connect(self.hide)
        header.addWidget(close)
        layout.addWidget(self.header)

        # Conversation
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.conversation = QWidget()
        self.conversation.setObjectName("Conversation")
        self.conv_layout = QVBoxLayout(self.conversation)
        self.conv_layout.setContentsMargins(0, 0, 4, 0)
        self.conv_layout.setSpacing(8)
        self.conv_layout.addStretch(1)
        self.scroll.setWidget(self.conversation)
        self.scroll.hide()
        layout.addWidget(self.scroll, 1)

        # Input
        row = QHBoxLayout()
        self.input = QLineEdit()
        self.input.setObjectName("Input")
        self.input.setPlaceholderText("Ask me anything, e.g. “open spotify” or “todo call mom tomorrow 6pm”")
        self.input.returnPressed.connect(self._submit)
        self.input.installEventFilter(_HistoryFilter(self))
        self.send_btn = QPushButton("Send")
        self.send_btn.setObjectName("Primary")
        self.send_btn.clicked.connect(self._send_or_stop)
        row.addWidget(self.input, 1)
        row.addWidget(self.send_btn)
        layout.addLayout(row)

        self.resize(WIDTH, COMPACT_HEIGHT)

    # ----- showing / hiding -----

    def show_popup(self) -> None:
        screen = QGuiApplication.screenAt(QCursor.pos()) or QGuiApplication.primaryScreen()
        geo = screen.availableGeometry()
        height = self.height()
        x = geo.x() + (geo.width() - self.width()) // 2
        y = geo.y() + max(int(geo.height() * 0.18), 0)
        if y + height > geo.bottom():
            y = max(geo.y(), geo.bottom() - height)
        self.move(x, y)
        self.show()
        self.raise_()
        self.activateWindow()
        self.input.setFocus()

    def toggle(self) -> None:
        if self.isVisible() and self.isActiveWindow():
            self.hide()
        else:
            self.show_popup()

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802
        if event.key() == Qt.Key.Key_Escape:
            self.hide()
            return
        super().keyPressEvent(event)

    # Drag the window by its header.
    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton and self.header.geometry().contains(
            self.panel.mapFrom(self, event.position().toPoint())
        ):
            self._drag_from = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        if self._drag_from is not None and event.buttons() & Qt.MouseButton.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_from)
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        self._drag_from = None
        super().mouseReleaseEvent(event)

    # ----- conversation -----

    def _expand(self) -> None:
        if not self.scroll.isVisible():
            self.scroll.show()
            top_left = self.pos()
            self.resize(WIDTH, EXPANDED_HEIGHT)
            screen = QGuiApplication.screenAt(top_left) or QGuiApplication.primaryScreen()
            geo = screen.availableGeometry()
            if top_left.y() + EXPANDED_HEIGHT > geo.bottom():
                self.move(top_left.x(), max(geo.y(), geo.bottom() - EXPANDED_HEIGHT))

    def _add_row(self, widget: QWidget, align_right: bool = False) -> None:
        self._expand()
        row = QWidget()
        h = QHBoxLayout(row)
        h.setContentsMargins(0, 0, 0, 0)
        if align_right:
            h.addStretch(1)
        h.addWidget(widget)
        if not align_right:
            h.addStretch(1)
        max_width = int(WIDTH * 0.8)
        widget.setMaximumWidth(max_width)
        widget.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum)
        if isinstance(widget, QLabel):
            _fit_label(widget, max_width)
        self.conv_layout.addWidget(row)
        QTimer.singleShot(30, self._scroll_to_end)

    def _scroll_to_end(self) -> None:
        bar = self.scroll.verticalScrollBar()
        bar.setValue(bar.maximum())

    def add_user(self, text: str) -> None:
        self._add_row(_label(text, object_name="UserBubble"), align_right=True)

    def add_bot(self, text: str, error: bool = False) -> None:
        self._add_row(_label(_hard_breaks(text), markdown=True, object_name="ErrorBubble" if error else "BotBubble"))

    def add_reply(self, reply: AgentReply) -> None:
        if reply.steps:
            marks = []
            for s in reply.steps:
                mark = "✓" if s.result.ok else ("⊘" if s.result.cancelled else "✗")
                marks.append(f"{mark} {s.tool.replace('_', ' ')}")
            self._add_row(_label("   ".join(marks), object_name="Muted"))
        if reply.text:
            self.add_bot(reply.text, error=bool(reply.error))

    def add_card(self, request: ConfirmRequest) -> ConfirmCard:
        card = ConfirmCard(request)
        self._add_row(card)
        card.setMinimumWidth(min(520, WIDTH - 80))
        card.setMaximumWidth(WIDTH - 60)
        if not self.isVisible():
            self.show_popup()
        QTimer.singleShot(50, card.focus)
        return card

    def clear(self) -> None:
        while self.conv_layout.count() > 1:
            item = self.conv_layout.takeAt(1)
            if item.widget():
                item.widget().deleteLater()
        self.scroll.hide()
        self.resize(WIDTH, COMPACT_HEIGHT)
        self.set_status("")

    # ----- input -----

    def set_busy(self, busy: bool) -> None:
        self._busy = busy
        self.send_btn.setText("Stop" if busy else "Send")
        self.send_btn.setObjectName("Danger" if busy else "Primary")
        self.send_btn.style().unpolish(self.send_btn)
        self.send_btn.style().polish(self.send_btn)
        if not busy:
            self.set_status("")
            self.input.setFocus()

    def set_status(self, text: str) -> None:
        self.status.setText(text)

    def _send_or_stop(self) -> None:
        if self._busy:
            self.stop_requested.emit()
        else:
            self._submit()

    def _submit(self) -> None:
        text = self.input.text().strip()
        if not text or self._busy:
            return
        self.input.clear()
        if not self._history or self._history[-1] != text:
            self._history.append(text)
        self._history_pos = len(self._history)
        self.add_user(text)
        self.submitted.emit(text)

    def recall(self, direction: int) -> None:
        if not self._history:
            return
        self._history_pos = max(0, min(len(self._history), self._history_pos + direction))
        self.input.setText(self._history[self._history_pos] if self._history_pos < len(self._history) else "")
