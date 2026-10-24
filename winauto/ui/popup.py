"""The popup window: search box, results, home, chat and writing tools, with keys and animation."""

from __future__ import annotations

import time

from PySide6.QtCore import (
    QEasingCurve,
    QEvent,
    QObject,
    QPoint,
    QPropertyAnimation,
    QRectF,
    Qt,
    QTimer,
    Signal,
)
from PySide6.QtGui import (
    QColor,
    QCursor,
    QGuiApplication,
    QKeyEvent,
    QPainter,
    QPainterPath,
)
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from winauto.core.agent import AgentReply, ConfirmRequest
from winauto.core.skill import Suggestion
from winauto.ui.cards import ConfirmCard
from winauto.ui.chat import ChatView
from winauto.ui.home import HomeView
from winauto.ui.icons import pixmap
from winauto.ui.parts import HEIGHT, SHADOW, WIDTH, clear_layout, divider
from winauto.ui.textmode import TextModeView
from winauto.ui.theme import Palette, base_font
from winauto.ui.widgets import ResultList, Spinner, icon_button, kbd


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
    setup_action = Signal(str)  # built-in AI card: "pause", "resume", "retry" or "dismiss"
    welcome_action = Signal(str)  # first-run card: "startup", "examples" or "dismiss"

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
        # Hide when another window is clicked (the app turns this on from Settings).
        self.hide_on_blur = False
        self._keep_open_until = 0.0
        self._hidden_at: float | None = None

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
        v.addWidget(divider())

        # Pages
        self.stack = QStackedWidget()
        self.home = HomeView(palette)
        self.home.setup.action.connect(self.setup_action.emit)
        self.home.setup.dismissed.connect(lambda: self.setup_action.emit("dismiss"))
        self.home.welcome.action.connect(self.welcome_action.emit)
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
        v.addWidget(divider())

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
        clear_layout(self.hints)
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

    def hideEvent(self, event) -> None:  # noqa: N802
        self._hidden_at = time.monotonic()
        super().hideEvent(event)

    def hidden_for(self) -> float:
        """Seconds since the popup was last hidden (0 while it's showing or before it ever was)."""
        return 0.0 if self.isVisible() or self._hidden_at is None else time.monotonic() - self._hidden_at

    def keep_open(self, ms: int) -> None:
        """Don't hide on click-away for a while (e.g. while Windows voice typing has the focus)."""
        self._keep_open_until = time.monotonic() + ms / 1000

    def changeEvent(self, event) -> None:  # noqa: N802
        if event.type() == QEvent.Type.ActivationChange and self.isVisible() and not self.isActiveWindow():
            QTimer.singleShot(200, self._hide_if_left)
        super().changeEvent(event)

    def _focus_left_winauto(self) -> bool:
        """True when another app has the focus (not this popup, Settings, a file picker or the tray menu)."""
        if self.isActiveWindow():
            return False
        return all(w is None for w in (QApplication.activeWindow(), QApplication.activeModalWidget(),
                                       QApplication.activePopupWidget()))

    def _hide_if_left(self) -> None:
        if not self.hide_on_blur or not self.isVisible() or not self._focus_left_winauto():
            return
        if self._busy or self.chat.has_open_cards() or time.monotonic() < self._keep_open_until:
            return  # still working, or waiting for an approval
        self.hide()

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

    def show_setup(self, view) -> None:
        """Show the built-in AI's progress (a services.ai_setup.SetupView)."""
        self.home.setup.show_view(view)
        if view.dot_label:
            self.set_model_status(view.dot, view.dot_label)

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

    def fill(self, text: str) -> None:
        """Start a command for the user ("remind me to "), cursor at the end, ready to finish."""
        if self.mode == "chat":
            self.set_mode("results")
        self.input.setText(text)
        self.input.setFocus()
        self.input.deselect()
        self.input.end(False)

    def recall(self, direction: int) -> None:
        if not self._history:
            return
        self._history_pos = max(0, min(len(self._history), self._history_pos + direction))
        self.input.setText(self._history[self._history_pos] if self._history_pos < len(self._history) else "")
