"""The popup: a launcher (search apps, settings, commands as you type) with an AI chat."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from PySide6.QtCore import QEasingCurve, QEvent, QObject, QPoint, QPropertyAnimation, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QCursor, QGuiApplication, QKeyEvent, QPainter, QPainterPath, QTextDocument
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from winauto.core.agent import AgentReply, ConfirmRequest, Decision
from winauto.core.skill import Suggestion
from winauto.ui.icons import icon, pixmap
from winauto.ui.theme import Palette, base_font
from winauto.ui.widgets import ResultList, Spinner, icon_button, kbd

WIDTH = 780
HEIGHT = 560
SHADOW = 18
MULTILINE_FIELDS = {"body", "message", "text", "content", "note", "command"}


# ---------------- helpers ----------------

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
    label.setMinimumWidth(min(int(doc.idealWidth()) + 32, max_width))


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


def _dispose(widget: QWidget | None) -> None:
    """Hide now, delete later: otherwise the old widget is still drawn until Qt gets to it."""
    if widget is not None:
        widget.hide()
        widget.deleteLater()


def _clear_layout(layout) -> None:
    while layout.count():
        item = layout.takeAt(0)
        if item.widget():
            _dispose(item.widget())


def _divider() -> QFrame:
    line = QFrame()
    line.setObjectName("Divider")
    line.setFrameShape(QFrame.Shape.NoFrame)
    return line


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
        head.addWidget(_label(request.title, object_name="CardTitle"), 1)
        layout.addLayout(head)
        if request.preview:
            layout.addWidget(_label(request.preview, object_name="Muted"))
        for name in request.editable:
            value = str(request.args.get(name, ""))
            layout.addWidget(_label(name.replace("_", " ").capitalize(), object_name="Muted"))
            if name in MULTILINE_FIELDS or "\n" in value or len(value) > 80:
                edit = QPlainTextEdit(value)
                edit.setMinimumHeight(120 if name != "command" else 60)
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
        self.ok_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.cancel_btn.setCursor(Qt.CursorShape.PointingHandCursor)
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


# ---------------- chat ----------------

class TypingDots(QLabel):
    def __init__(self, palette: Palette):
        super().__init__()
        self.p = palette
        self.setObjectName("BotBubble")
        self._n = 0
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(320)
        self._tick()

    def _tick(self) -> None:
        self._n = (self._n + 1) % 4
        dots = ["<span style='color:%s'>●</span>" % (self.p.accent if i < self._n else self.p.faint) for i in range(3)]
        self.setText(" ".join(dots))


class ChatView(QScrollArea):
    action_requested = Signal(object)  # {"label","tool","args"}

    def __init__(self, palette: Palette):
        super().__init__()
        self.p = palette
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.conversation = QWidget()
        self.conversation.setObjectName("Conversation")
        self.layout_ = QVBoxLayout(self.conversation)
        self.layout_.setContentsMargins(18, 14, 18, 14)
        self.layout_.setSpacing(10)
        self.layout_.addStretch(1)
        self.setWidget(self.conversation)
        self._typing: QWidget | None = None
        self._stream_label: QLabel | None = None
        self._stream_row: QWidget | None = None
        self._stream_text = ""

    @property
    def max_bubble(self) -> int:
        return int((WIDTH - 2 * SHADOW) * 0.78)

    def _row(self, widget: QWidget, align_right: bool = False, avatar: bool = False) -> QWidget:
        row = QWidget()
        h = QHBoxLayout(row)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(8)
        if align_right:
            h.addStretch(1)
        if avatar:
            av = QLabel()
            av.setFixedSize(26, 26)
            av.setAlignment(Qt.AlignmentFlag.AlignCenter)
            av.setStyleSheet(f"background: qlineargradient(x1:0,y1:0,x2:1,y2:1, stop:0 {self.p.accent}, stop:1 {self.p.accent_2});"
                             "border-radius: 13px;")
            av.setPixmap(pixmap("sparkles", "#ffffff", 14))
            h.addWidget(av, 0, Qt.AlignmentFlag.AlignTop)
        h.addWidget(widget)
        if not align_right:
            h.addStretch(1)
        widget.setMaximumWidth(self.max_bubble)
        widget.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum)
        if isinstance(widget, TypingDots):
            widget.setFixedWidth(64)
        elif isinstance(widget, QLabel):
            _fit_label(widget, self.max_bubble)
        self.layout_.addWidget(row)
        QTimer.singleShot(30, self.scroll_to_end)
        return row

    def scroll_to_end(self) -> None:
        bar = self.verticalScrollBar()
        bar.setValue(bar.maximum())

    def add_user(self, text: str) -> None:
        self._row(_label(text, object_name="UserBubble"), align_right=True)

    def add_bot(self, text: str, error: bool = False) -> QLabel:
        label = _label(_hard_breaks(text), markdown=True, object_name="ErrorBubble" if error else "BotBubble")
        self._row(label, avatar=True)
        return label

    def add_reply(self, reply: AgentReply) -> None:
        self.end_typing()
        self.end_stream()
        if reply.steps:
            marks = []
            for s in reply.steps:
                mark = "✓" if s.result.ok else ("⊘" if s.result.cancelled else "✗")
                marks.append(f"{mark} {s.tool.replace('_', ' ')}")
            steps = _label("   ".join(marks), object_name="Steps")
            row = self._row(steps)
            row.layout().setContentsMargins(34, 0, 0, 0)
        if reply.text:
            self.add_bot(reply.text, error=bool(reply.error))
        actions = []
        for s in reply.steps:
            data = s.result.data if isinstance(s.result.data, dict) else {}
            actions += data.get("actions", []) if s.result.ok else []
        if actions:
            self.add_actions(actions)

    def add_actions(self, actions: list[dict]) -> None:
        row = QWidget()
        h = QHBoxLayout(row)
        h.setContentsMargins(34, 0, 0, 0)
        h.setSpacing(8)
        for a in actions:
            btn = QPushButton(a.get("label", "Do it"))
            btn.setObjectName("Chip")
            btn.setIcon(icon(a.get("icon", "chevron-right"), self.p.text, 14))
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.clicked.connect(lambda _=False, act=a: self.action_requested.emit(act))
            h.addWidget(btn)
        h.addStretch(1)
        self.layout_.addWidget(row)
        QTimer.singleShot(30, self.scroll_to_end)

    def add_card(self, request: ConfirmRequest) -> ConfirmCard:
        self.end_typing()
        card = ConfirmCard(request, self.p)
        row = self._row(card)
        row.layout().setContentsMargins(34, 0, 0, 0)
        card.setMinimumWidth(min(560, self.max_bubble))
        card.setMaximumWidth(WIDTH - 2 * SHADOW - 80)
        QTimer.singleShot(50, card.focus)
        return card

    def start_typing(self) -> None:
        if self._typing is None and self._stream_label is None:
            dots = TypingDots(self.p)
            self._typing = self._row(dots, avatar=True)

    def end_typing(self) -> None:
        if self._typing is not None:
            self.layout_.removeWidget(self._typing)
            _dispose(self._typing)
            self._typing = None

    def stream_token(self, delta: str) -> None:
        if delta == "":
            # A new answer starts: drop the previous partial one.
            self.end_stream()
            return
        self.end_typing()
        if self._stream_label is None:
            self._stream_text = ""
            self._stream_label = _label("", markdown=True, object_name="BotBubble")
            self._stream_label.setMinimumWidth(min(240, self.max_bubble))
            self._stream_row = self._row(self._stream_label, avatar=True)
        self._stream_text += delta
        self._stream_label.setText(_hard_breaks(self._stream_text))
        _fit_label(self._stream_label, self.max_bubble)
        QTimer.singleShot(10, self.scroll_to_end)

    def end_stream(self) -> None:
        if self._stream_row is not None:
            self.layout_.removeWidget(self._stream_row)
            _dispose(self._stream_row)
        self._stream_row = None
        self._stream_label = None
        self._stream_text = ""

    def clear(self) -> None:
        self.end_typing()
        self.end_stream()
        while self.layout_.count() > 1:
            item = self.layout_.takeAt(1)
            if item.widget():
                _dispose(item.widget())

    def is_empty(self) -> bool:
        return self.layout_.count() <= 1


# ---------------- home ----------------

class HomeView(QWidget):
    def __init__(self, palette: Palette):
        super().__init__()
        self.p = palette
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 14, 0, 6)
        v.setSpacing(6)
        head = QVBoxLayout()
        head.setContentsMargins(22, 0, 22, 0)
        head.setSpacing(2)
        self.greeting = QLabel("")
        self.greeting.setObjectName("Greeting")
        self.sub = QLabel("")
        self.sub.setObjectName("SubGreeting")
        head.addWidget(self.greeting)
        head.addWidget(self.sub)
        v.addLayout(head)
        self.widgets_row = QHBoxLayout()
        self.widgets_row.setContentsMargins(22, 8, 22, 2)
        self.widgets_row.setSpacing(8)
        v.addLayout(self.widgets_row)
        self.list = ResultList(palette)
        v.addWidget(self.list, 1)
        self.refresh_greeting("")

    def refresh_greeting(self, name: str) -> None:
        now = datetime.now()
        part = "Good morning" if 5 <= now.hour < 12 else "Good afternoon" if now.hour < 17 else "Good evening"
        self.greeting.setText(f"{part}{', ' + name.split()[0] if name else ''}")
        self.sub.setText(now.strftime("%A, %d %B"))

    def set_widgets(self, items: list[tuple[str, str]]) -> None:
        _clear_layout(self.widgets_row)
        for icon_name, text in items:
            box = QFrame()
            box.setObjectName("Widget")
            h = QHBoxLayout(box)
            h.setContentsMargins(10, 7, 12, 7)
            h.setSpacing(8)
            ic = QLabel()
            ic.setPixmap(pixmap(icon_name, self.p.accent, 16))
            h.addWidget(ic)
            lab = QLabel(text)
            lab.setObjectName("WidgetText")
            h.addWidget(lab)
            self.widgets_row.addWidget(box)
        self.widgets_row.addStretch(1)

    def set_lists(self, suggestions: list[Suggestion], recent: list[Suggestion]) -> None:
        self.list.set_items([("Suggestions", suggestions), ("Recent", recent)])


# ---------------- writing tools ----------------

class TextModeView(QWidget):
    action_chosen = Signal(str)

    def __init__(self, palette: Palette):
        super().__init__()
        self.p = palette
        v = QVBoxLayout(self)
        v.setContentsMargins(22, 16, 22, 12)
        v.setSpacing(10)
        title = QLabel("Writing tools")
        title.setObjectName("Greeting")
        v.addWidget(title)
        self.quote = _label("", object_name="Quote")
        self.quote.setMaximumHeight(110)
        v.addWidget(self.quote)
        sec = QLabel("What should I do with it?")
        sec.setObjectName("SectionTitle")
        v.addWidget(sec)
        self.grid = QGridLayout()
        self.grid.setSpacing(8)
        v.addLayout(self.grid)
        hint = QLabel("…or type your own instruction above and press Enter.")
        hint.setObjectName("Muted")
        v.addWidget(hint)
        v.addStretch(1)

    def set_content(self, text: str, actions: list[tuple[str, str, str]]) -> None:
        one = " ".join(text.split())
        self.quote.setText(one[:400] + ("…" if len(one) > 400 else ""))
        _clear_layout(self.grid)
        for i, (key, label, icon_name) in enumerate(actions):
            btn = QPushButton(label)
            btn.setObjectName("Chip")
            btn.setIcon(icon(icon_name, self.p.text, 15))
            btn.setIconSize(QSize(15, 15))
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.clicked.connect(lambda _=False, k=key: self.action_chosen.emit(k))
            self.grid.addWidget(btn, i // 3, i % 3)


# ---------------- window ----------------

class _KeyFilter(QObject):
    def __init__(self, popup: "PopupWindow"):
        super().__init__(popup)
        self.popup = popup

    def eventFilter(self, obj, event) -> bool:  # noqa: N802
        if event.type() == QEvent.Type.KeyPress and isinstance(event, QKeyEvent):
            return self.popup.handle_key(event)
        return False


class PopupWindow(QWidget):
    submitted = Signal(str)  # text for the assistant
    suggestion_chosen = Signal(object)  # Suggestion
    query_changed = Signal(str)
    action_requested = Signal(object)  # reply action button
    text_action = Signal(str)  # writing tools: action key, or "custom:<instruction>"
    stop_requested = Signal()
    new_chat_requested = Signal()
    settings_requested = Signal()
    mic_requested = Signal()

    def __init__(self, palette: Palette):
        super().__init__(None)
        self.palette_ = self.p = palette
        self.setWindowTitle("WinAuto")
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.Tool)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFixedSize(WIDTH, HEIGHT)
        self._busy = False
        self._history: list[str] = []
        self._history_pos = 0
        self._drag_from: QPoint | None = None
        self.mode = "home"
        self.has_chat = False

        outer = QVBoxLayout(self)
        outer.setContentsMargins(SHADOW, SHADOW - 6, SHADOW, SHADOW + 6)
        self.panel = QFrame()
        self.panel.setObjectName("Panel")
        outer.addWidget(self.panel)
        v = QVBoxLayout(self.panel)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)

        # Search bar
        self.header = QWidget()
        h = QHBoxLayout(self.header)
        h.setContentsMargins(18, 12, 12, 12)
        h.setSpacing(10)
        self.lead = QLabel()
        self.lead.setPixmap(pixmap("search", palette.muted, 20))
        h.addWidget(self.lead)
        self.input = QLineEdit()
        self.input.setObjectName("SearchInput")
        self.input.setFont(base_font(14))
        self.input.setPlaceholderText("Search apps and commands, or ask anything…")
        self.input.installEventFilter(_KeyFilter(self))
        self.input.textChanged.connect(self._text_changed)
        h.addWidget(self.input, 1)
        self.spinner = Spinner(palette)
        h.addWidget(self.spinner)
        self.stop_btn = icon_button("stop", "Stop", palette)
        self.stop_btn.clicked.connect(self.stop_requested.emit)
        self.stop_btn.hide()
        h.addWidget(self.stop_btn)
        self.mic_btn = icon_button("mic", "Dictate (Windows voice typing)", palette)
        self.mic_btn.clicked.connect(self.mic_requested.emit)
        h.addWidget(self.mic_btn)
        self.new_btn = icon_button("plus", "New chat", palette)
        self.new_btn.clicked.connect(self.new_chat_requested.emit)
        h.addWidget(self.new_btn)
        self.settings_btn = icon_button("settings", "Settings", palette)
        self.settings_btn.clicked.connect(self.settings_requested.emit)
        h.addWidget(self.settings_btn)
        v.addWidget(self.header)
        v.addWidget(_divider())

        # Pages
        self.stack = QStackedWidget()
        self.home = HomeView(palette)
        self.home.list.chosen.connect(self.suggestion_chosen.emit)
        self.results = ResultList(palette)
        self.results.chosen.connect(self.suggestion_chosen.emit)
        results_page = QWidget()
        rl = QVBoxLayout(results_page)
        rl.setContentsMargins(0, 8, 0, 6)
        rl.addWidget(self.results)
        self.chat = ChatView(palette)
        self.chat.action_requested.connect(self.action_requested.emit)
        self.conversation = self.chat.conversation
        self.text_view = TextModeView(palette)
        self.text_view.action_chosen.connect(self.text_action.emit)
        for page in (self.home, results_page, self.chat, self.text_view):
            self.stack.addWidget(page)
        v.addWidget(self.stack, 1)
        v.addWidget(_divider())

        # Footer
        foot = QWidget()
        f = QHBoxLayout(foot)
        f.setContentsMargins(16, 8, 14, 9)
        f.setSpacing(6)
        self.status_dot = QLabel()
        self.status_dot.setFixedSize(8, 8)
        f.addWidget(self.status_dot)
        self.status = QLabel("WinAuto")
        self.status.setObjectName("Footer")
        f.addWidget(self.status)
        f.addStretch(1)
        self.toast = QLabel("")
        self.toast.setObjectName("Toast")
        f.addWidget(self.toast)
        f.addSpacing(10)
        self.hints = QHBoxLayout()
        self.hints.setSpacing(5)
        f.addLayout(self.hints)
        v.addWidget(foot)

        self.set_model_status(None, "")
        self.set_mode("home")

    # ----- painting: soft shadow around the rounded panel -----

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.panel.geometry())
        alpha = 46 if self.p.name == "dark" else 22
        for i in range(SHADOW, 0, -2):
            c = QColor(0, 0, 0, int(alpha * (1 - i / SHADOW) ** 2))
            path = QPainterPath()
            path.addRoundedRect(r.adjusted(-i, -i + 6, i, i + 6), 16 + i, 16 + i)
            painter.fillPath(path, c)

    # ----- modes -----

    def set_mode(self, mode: str) -> None:
        self.mode = mode
        index = {"home": 0, "results": 1, "chat": 2, "text": 3}[mode]
        self.stack.setCurrentIndex(index)
        lead = {"chat": "sparkles", "text": "text"}.get(mode, "search")
        self.lead.setPixmap(pixmap(lead, self.p.accent if mode in ("chat", "text") else self.p.muted, 20))
        placeholders = {
            "home": "Search apps and commands, or ask anything…",
            "results": "Search apps and commands, or ask anything…",
            "chat": "Ask a follow-up…",
            "text": "Or tell me what to do with the selected text…",
        }
        self.input.setPlaceholderText(placeholders[mode])
        hints = {
            "home": [("↵", "Open"), ("Ctrl ↵", "Ask AI")],
            "results": [("↑↓", "Select"), ("↵", "Open"), ("Ctrl ↵", "Ask AI")],
            "chat": [("↵", "Send"), ("Esc", "Hide")],
            "text": [("↵", "Apply"), ("Esc", "Back")],
        }[mode]
        _clear_layout(self.hints)
        for key, what in hints:
            self.hints.addWidget(kbd(key))
            lab = QLabel(what)
            lab.setObjectName("Footer")
            self.hints.addWidget(lab)
            self.hints.addSpacing(6)

    def enter_chat(self) -> None:
        self.has_chat = True
        self.set_mode("chat")

    def show_results(self, suggestions: list[Suggestion]) -> None:
        if self.mode != "results":
            return
        self.results.set_items([("", suggestions)])

    def show_text_mode(self, text: str, actions: list[tuple[str, str, str]]) -> None:
        self.text_view.set_content(text, actions)
        self.input.clear()
        self.set_mode("text")
        if not self.isVisible():
            self.show_popup()

    def _text_changed(self, text: str) -> None:
        if self.mode in ("text", "chat"):
            return
        if text.strip():
            if self.mode != "results":
                self.set_mode("results")
            self.query_changed.emit(text)
        else:
            self.set_mode("chat" if self.has_chat else "home")

    # ----- keys -----

    def handle_key(self, event: QKeyEvent) -> bool:
        key, mods = event.key(), event.modifiers()
        ctrl = bool(mods & Qt.KeyboardModifier.ControlModifier)
        if key in (Qt.Key.Key_Up, Qt.Key.Key_Down):
            step = -1 if key == Qt.Key.Key_Up else 1
            if self.mode == "results":
                self.results.move(step)
            elif self.mode == "home":
                self.home.list.move(step)
            else:
                self.recall(step)
            return True
        if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            text = self.input.text().strip()
            if ctrl and text:
                self._submit()
            elif self.mode == "text":
                if text:
                    self._remember(text)
                    self.input.clear()
                    self.text_action.emit("custom:" + text)
            elif self.mode == "results":
                chosen = self.results.current()
                if chosen is not None:
                    self._remember(text)
                    self.suggestion_chosen.emit(chosen)
                elif text:
                    self._submit()
            elif self.mode == "home" and not text:
                chosen = self.home.list.current()
                if chosen is not None:
                    self.suggestion_chosen.emit(chosen)
            elif text:
                self._submit()
            return True
        if key == Qt.Key.Key_Escape:
            if self.input.text():
                self.input.clear()
            elif self.mode == "text":
                self.set_mode("chat" if self.has_chat else "home")
            else:
                self.hide()
            return True
        return False

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802
        if event.key() == Qt.Key.Key_Escape:
            self.hide()
            return
        super().keyPressEvent(event)

    # ----- showing / hiding -----

    def show_popup(self) -> None:
        screen = QGuiApplication.screenAt(QCursor.pos()) or QGuiApplication.primaryScreen()
        geo = screen.availableGeometry()
        x = geo.x() + (geo.width() - self.width()) // 2
        y = geo.y() + max(int(geo.height() * 0.16), 0)
        if y + self.height() > geo.bottom():
            y = max(geo.y(), geo.bottom() - self.height())
        self.setWindowOpacity(0.0)
        self.move(x, y - 8)
        self.show()
        self.raise_()
        self.activateWindow()
        self.input.setFocus()
        self.input.selectAll()
        fade = QPropertyAnimation(self, b"windowOpacity", self)
        fade.setDuration(140)
        fade.setStartValue(0.0)
        fade.setEndValue(1.0)
        fade.setEasingCurve(QEasingCurve.Type.OutCubic)
        slide = QPropertyAnimation(self, b"pos", self)
        slide.setDuration(160)
        slide.setStartValue(QPoint(x, y - 8))
        slide.setEndValue(QPoint(x, y))
        slide.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._anims = (fade, slide)
        fade.start()
        slide.start()

    def toggle(self) -> None:
        if self.isVisible() and self.isActiveWindow():
            self.hide()
        else:
            self.show_popup()

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

    # ----- conversation (used by the controller) -----

    def add_user(self, text: str) -> None:
        self.enter_chat()
        self.chat.add_user(text)

    def add_bot(self, text: str, error: bool = False) -> None:
        self.enter_chat()
        self.chat.add_bot(text, error)

    def add_reply(self, reply: AgentReply) -> None:
        self.enter_chat()
        self.chat.add_reply(reply)

    def add_card(self, request: ConfirmRequest) -> ConfirmCard:
        self.enter_chat()
        if not self.isVisible():
            self.show_popup()
        return self.chat.add_card(request)

    def stream_token(self, delta: str) -> None:
        if delta and self.mode != "chat":
            self.enter_chat()
        self.chat.stream_token(delta)

    def clear(self) -> None:
        self.chat.clear()
        self.has_chat = False
        self.input.clear()
        self.set_mode("home")
        self.set_status("")

    # ----- status -----

    def set_busy(self, busy: bool) -> None:
        self._busy = busy
        if busy:
            self.spinner.start()
            self.stop_btn.show()
            self.mic_btn.hide()
            if self.mode == "chat":
                self.chat.start_typing()
        else:
            self.spinner.stop()
            self.stop_btn.hide()
            self.mic_btn.show()
            self.chat.end_typing()
            self.set_status("")
            self.input.setFocus()

    def is_busy(self) -> bool:
        return self._busy

    def set_status(self, text: str) -> None:
        self.status.setText(text or self._model_label)

    def set_model_status(self, ok: bool | None, label: str) -> None:
        self._model_label = label or "WinAuto"
        color = self.p.faint if ok is None else (self.p.success if ok else self.p.danger)
        self.status_dot.setStyleSheet(f"background: {color}; border-radius: 4px;")
        self.status_dot.setToolTip({None: "Checking the AI model…", True: "AI model ready", False: "AI model not available"}[ok])
        if not self._busy:
            self.status.setText(self._model_label)

    def flash(self, text: str, ms: int = 1600) -> None:
        self.toast.setText(text)
        QTimer.singleShot(ms, lambda: self.toast.setText(""))

    # ----- input -----

    def _remember(self, text: str) -> None:
        if text and (not self._history or self._history[-1] != text):
            self._history.append(text)
        self._history_pos = len(self._history)

    def _submit(self) -> None:
        text = self.input.text().strip()
        if not text or self._busy:
            return
        self.input.clear()
        self._remember(text)
        self.add_user(text)
        self.submitted.emit(text)

    def recall(self, direction: int) -> None:
        if not self._history:
            return
        self._history_pos = max(0, min(len(self._history), self._history_pos + direction))
        self.input.setText(self._history[self._history_pos] if self._history_pos < len(self._history) else "")
