"""The card on the home screen that shows the built-in AI being downloaded and loaded."""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QProgressBar, QPushButton, QVBoxLayout

from winauto.ui.icons import pixmap
from winauto.ui.theme import Palette


class SetupCard(QFrame):
    """Draws a services.ai_setup.SetupView. Emits `action` with the view's action name."""

    action = Signal(str)
    dismissed = Signal()

    def __init__(self, palette: Palette):
        super().__init__()
        self.p = palette
        self.setObjectName("Card")
        h = QHBoxLayout(self)
        h.setContentsMargins(14, 12, 14, 12)
        h.setSpacing(12)
        self.icon = QLabel()
        self.icon.setPixmap(pixmap("sparkles", palette.accent, 22))
        self.icon.setAlignment(Qt.AlignmentFlag.AlignTop)
        h.addWidget(self.icon)
        body = QVBoxLayout()
        body.setSpacing(4)
        self.title = QLabel()
        self.title.setObjectName("CardTitle")
        self.message = QLabel()
        self.message.setObjectName("Muted")
        self.message.setWordWrap(True)
        self.bar = QProgressBar()
        self.bar.setObjectName("SetupProgress")
        self.bar.setTextVisible(False)
        self.bar.setRange(0, 1000)
        bottom = QHBoxLayout()
        bottom.setSpacing(10)
        self.detail = QLabel()
        self.detail.setObjectName("Muted")
        self.button = QPushButton()
        self.button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.button.clicked.connect(lambda: self.action.emit(self._action))
        bottom.addWidget(self.detail, 1)
        bottom.addWidget(self.button)
        body.addWidget(self.title)
        body.addWidget(self.message)
        body.addSpacing(2)
        body.addWidget(self.bar)
        body.addLayout(bottom)
        h.addLayout(body, 1)
        self._action = ""
        self._hide_timer = QTimer(self)
        self._hide_timer.setSingleShot(True)
        self._hide_timer.timeout.connect(self._auto_hide)
        self.hide()

    def show_view(self, view: Any) -> None:
        if not view.visible:
            self._hide_timer.stop()
            self.hide()
            return
        self.title.setText(view.title)
        self.message.setText(view.message)
        if view.progress is None:
            self.bar.hide()
        else:
            self.bar.show()
            if view.progress < 0:
                self.bar.setRange(0, 0)  # busy
            else:
                self.bar.setRange(0, 1000)
                self.bar.setValue(int(view.progress * 1000))
        self.detail.setText(view.detail)  # stays in the layout (even empty) so the button keeps its size
        self._action = view.action
        self.button.setText(view.action_label)
        self.button.setObjectName("Primary" if view.action in ("resume", "retry") else "")
        self.button.style().unpolish(self.button)
        self.button.style().polish(self.button)
        self.button.setVisible(bool(view.action))
        ready = view.dot is True
        self.icon.setPixmap(pixmap("check" if ready else "sparkles", self.p.success if ready else self.p.accent, 22))
        self.show()
        if view.hide_after_ms:
            self._hide_timer.start(view.hide_after_ms)

    def _auto_hide(self) -> None:
        self.hide()
        self.dismissed.emit()
