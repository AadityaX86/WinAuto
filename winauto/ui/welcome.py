"""The card on the home screen the first time WinAuto opens: how to use it, in one glance."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QSizePolicy, QVBoxLayout

from winauto.ui.icons import pixmap
from winauto.ui.theme import Palette


class WelcomeCard(QFrame):
    """Emits `action` with "startup" (start with Windows), "examples" or "dismiss"."""

    action = Signal(str)

    def __init__(self, palette: Palette):
        super().__init__()
        self.setObjectName("Card")
        # Never squashed: the suggestions list below scrolls instead.
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        h = QHBoxLayout(self)
        h.setContentsMargins(14, 12, 14, 12)
        h.setSpacing(12)
        icon = QLabel()
        icon.setPixmap(pixmap("sparkles", palette.accent, 22))
        icon.setAlignment(Qt.AlignmentFlag.AlignTop)
        h.addWidget(icon)
        body = QVBoxLayout()
        body.setSpacing(4)
        self.title = QLabel("Welcome to WinAuto")
        self.title.setObjectName("CardTitle")
        self.message = QLabel()
        self.message.setObjectName("Muted")
        self.message.setWordWrap(True)
        self.message.setTextFormat(Qt.TextFormat.RichText)
        buttons = QHBoxLayout()
        buttons.setSpacing(8)
        self.startup = QPushButton("Start with Windows")
        self.startup.setToolTip("Run quietly in the tray when you sign in, so the shortcut always works.")
        self.examples = QPushButton("Show examples")
        self.done = QPushButton("Got it")
        self.done.setObjectName("Primary")
        for button, name in ((self.startup, "startup"), (self.examples, "examples"), (self.done, "dismiss")):
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.clicked.connect(lambda _=False, n=name: self.action.emit(n))
        buttons.addWidget(self.startup)
        buttons.addWidget(self.examples)
        buttons.addStretch(1)
        buttons.addWidget(self.done)
        body.addWidget(self.title)
        body.addWidget(self.message)
        body.addSpacing(4)
        body.addLayout(buttons)
        h.addLayout(body, 1)
        self.hide()

    def show_welcome(self, hotkey: str, starts_with_windows: bool) -> None:
        self.message.setText(
            f"Press <b>{hotkey}</b> anytime to open me. Type an app or setting to open it, a command like "
            "<i>volume 30</i> or <i>remind me to call mom at 6pm</i>, or ask anything."
        )
        self.set_starts_with_windows(starts_with_windows)
        self.show()

    def set_starts_with_windows(self, on: bool) -> None:
        self.startup.setVisible(not on)
