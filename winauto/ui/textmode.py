"""Writing tools view: the selected text and one-click actions."""

from __future__ import annotations

from PySide6.QtCore import (
    QSize,
    Qt,
    Signal,
)
from PySide6.QtWidgets import (
    QGridLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from winauto.ui.icons import icon
from winauto.ui.parts import (
    clear_layout,
    make_label,
)
from winauto.ui.theme import Palette


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
        self.quote = make_label("", object_name="Quote")
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
        clear_layout(self.grid)
        for i, (key, label, icon_name) in enumerate(actions):
            btn = QPushButton(label)
            btn.setObjectName("Chip")
            btn.setIcon(icon(icon_name, self.p.text, 15))
            btn.setIconSize(QSize(15, 15))
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.clicked.connect(lambda _=False, k=key: self.action_chosen.emit(k))
            self.grid.addWidget(btn, i // 3, i % 3)
