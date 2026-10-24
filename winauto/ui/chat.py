"""The conversation: message bubbles, streaming answers, typing dots, action chips and cards."""

from __future__ import annotations

from PySide6.QtCore import (
    Qt,
    QTimer,
    Signal,
)
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from winauto.core.agent import AgentReply, ConfirmRequest
from winauto.ui.cards import ConfirmCard
from winauto.ui.icons import icon, pixmap
from winauto.ui.parts import SHADOW, WIDTH, dispose, fit_label, hard_breaks, make_label
from winauto.ui.theme import Palette


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
            fit_label(widget, self.max_bubble)
        self.layout_.addWidget(row)
        QTimer.singleShot(30, self.scroll_to_end)
        return row

    def scroll_to_end(self) -> None:
        bar = self.verticalScrollBar()
        bar.setValue(bar.maximum())

    def add_user(self, text: str) -> None:
        self._row(make_label(text, object_name="UserBubble"), align_right=True)

    def add_bot(self, text: str, error: bool = False) -> QLabel:
        label = make_label(hard_breaks(text), markdown=True, object_name="ErrorBubble" if error else "BotBubble")
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
            steps = make_label("   ".join(marks), object_name="Steps")
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
            dispose(self._typing)
            self._typing = None

    def stream_token(self, delta: str) -> None:
        if delta == "":
            # A new answer starts: drop the previous partial one.
            self.end_stream()
            return
        self.end_typing()
        if self._stream_label is None:
            self._stream_text = ""
            self._stream_label = make_label("", markdown=True, object_name="BotBubble")
            self._stream_label.setMinimumWidth(min(240, self.max_bubble))
            self._stream_row = self._row(self._stream_label, avatar=True)
        self._stream_text += delta
        self._stream_label.setText(hard_breaks(self._stream_text))
        fit_label(self._stream_label, self.max_bubble)
        QTimer.singleShot(10, self.scroll_to_end)

    def end_stream(self) -> None:
        if self._stream_row is not None:
            self.layout_.removeWidget(self._stream_row)
            dispose(self._stream_row)
        self._stream_row = None
        self._stream_label = None
        self._stream_text = ""

    def clear(self) -> None:
        self.end_typing()
        self.end_stream()
        while self.layout_.count() > 1:
            item = self.layout_.takeAt(1)
            if item.widget():
                dispose(item.widget())

    def is_empty(self) -> bool:
        return self.layout_.count() <= 1
