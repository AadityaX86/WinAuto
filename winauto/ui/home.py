"""The home screen: greeting, today's cards, suggestions and recent commands."""

from __future__ import annotations

from datetime import datetime

from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from winauto.core.skill import Suggestion
from winauto.ui.icons import pixmap
from winauto.ui.parts import clear_layout
from winauto.ui.setup import SetupCard
from winauto.ui.theme import Palette
from winauto.ui.welcome import WelcomeCard
from winauto.ui.widgets import ResultList


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
        # First run only: how to use WinAuto.
        self.welcome = WelcomeCard(palette)
        welcome_box = QHBoxLayout()
        welcome_box.setContentsMargins(22, 2, 22, 0)  # hidden boxes keep their margins: keep them small
        welcome_box.addWidget(self.welcome)
        v.addLayout(welcome_box)
        # Built-in AI download/loading progress (hidden when there's nothing to say).
        self.setup = SetupCard(palette)
        setup_box = QHBoxLayout()
        setup_box.setContentsMargins(22, 2, 22, 0)
        setup_box.addWidget(self.setup)
        v.addLayout(setup_box)
        self.widgets_row = QHBoxLayout()
        self.widgets_row.setContentsMargins(22, 8, 22, 2)
        self.widgets_row.setSpacing(8)
        v.addLayout(self.widgets_row)
        self.list = ResultList(palette)
        self.list.setMinimumHeight(40)  # the cards above keep their full height; the list scrolls
        v.addWidget(self.list, 1)
        self._widget_items: list[tuple[str, str]] = []
        self.refresh_greeting("")

    def refresh_greeting(self, name: str) -> None:
        now = datetime.now()
        part = "Good morning" if 5 <= now.hour < 12 else "Good afternoon" if now.hour < 17 else "Good evening"
        self.greeting.setText(f"{part}{', ' + name.split()[0] if name else ''}")
        self.sub.setText(now.strftime("%A, %d %B"))

    def hide_welcome(self) -> None:
        self.welcome.hide()
        self.set_widgets(self._widget_items)  # back in the room the welcome card used

    def set_widgets(self, items: list[tuple[str, str]]) -> None:
        self._widget_items = list(items)
        clear_layout(self.widgets_row)
        if not self.welcome.isHidden():
            return  # first run: the welcome card needs the room
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
