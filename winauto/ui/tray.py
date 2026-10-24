"""System tray icon and menu."""

from __future__ import annotations

from typing import Callable

from PySide6.QtCore import Signal
from PySide6.QtGui import QAction, QIcon
from PySide6.QtWidgets import QMenu, QSystemTrayIcon


def pretty_hotkey(hotkey: str) -> str:
    return "+".join(p.capitalize() if len(p) > 1 else p.upper() for p in hotkey.split("+"))


class Tray(QSystemTrayIcon):
    # Emitting this is safe from any thread.
    notify_requested = Signal(str, str)

    def __init__(
        self,
        icon: QIcon,
        hotkey: str,
        on_open: Callable[[], None],
        on_settings: Callable[[], None],
        on_data_folder: Callable[[], None],
        on_log: Callable[[], None],
        on_quit: Callable[[], None],
    ):
        super().__init__(icon)
        self._icon = icon
        self.setToolTip("WinAuto")
        self.menu = QMenu()
        self.open_action = QAction("Open WinAuto", self.menu)
        self.open_action.triggered.connect(on_open)
        self.menu.addAction(self.open_action)
        settings = QAction("Settings…", self.menu)
        settings.triggered.connect(on_settings)
        self.menu.addAction(settings)
        self.menu.addSeparator()
        folder = QAction("Open data folder", self.menu)
        folder.triggered.connect(on_data_folder)
        self.menu.addAction(folder)
        log_action = QAction("Open log file", self.menu)
        log_action.triggered.connect(on_log)
        self.menu.addAction(log_action)
        self.menu.addSeparator()
        quit_action = QAction("Quit WinAuto", self.menu)
        quit_action.triggered.connect(on_quit)
        self.menu.addAction(quit_action)
        self.setContextMenu(self.menu)
        self.set_hotkey(hotkey)
        self.activated.connect(
            lambda reason: on_open()
            if reason in (QSystemTrayIcon.ActivationReason.Trigger, QSystemTrayIcon.ActivationReason.DoubleClick)
            else None
        )
        self.notify_requested.connect(self._show)

    def set_hotkey(self, hotkey: str) -> None:
        self.open_action.setText(f"Open WinAuto   ({pretty_hotkey(hotkey)})")

    def notify(self, title: str, message: str) -> None:
        self.notify_requested.emit(title, message)

    def _show(self, title: str, message: str) -> None:
        self.showMessage(title, message, self._icon, 10000)
