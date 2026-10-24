"""Desktop app entry point: tray icon + hotkey + popup."""

from __future__ import annotations

import getpass
import logging
import os
import sys

from PySide6.QtCore import QObject, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import QApplication

from winauto import APP_NAME
from winauto.log import setup_logging
from winauto.paths import data_dir, log_dir

log = logging.getLogger(__name__)

SERVER_NAME = f"WinAuto-{getpass.getuser()}"

WELCOME = """Hi! I'm **WinAuto**. Press **{hotkey}** anytime to open me.

Things to try:
- open spotify / close chrome
- todo call mom tomorrow 6pm / show my todos
- note wifi password is in the drawer
- search best budget laptops / open youtube
- volume 30 / dark mode on / lock"""


class _Signals(QObject):
    toggle = Signal()
    show = Signal()


def _tell_running_instance() -> bool:
    """If WinAuto is already running, ask it to show itself and return True."""
    sock = QLocalSocket()
    sock.connectToServer(SERVER_NAME)
    if sock.waitForConnected(300):
        sock.write(b"show")
        sock.flush()
        sock.waitForBytesWritten(300)
        sock.disconnectFromServer()
        return True
    return False


def _log_uncaught(exc_type, exc, tb) -> None:
    log.critical("Uncaught error", exc_info=(exc_type, exc, tb))


def main(argv: list[str] | None = None) -> int:
    argv = list(argv if argv is not None else sys.argv)
    setup_logging()
    sys.excepthook = _log_uncaught
    background = "--background" in argv

    app = QApplication(argv)
    app.setApplicationName(APP_NAME)
    app.setQuitOnLastWindowClosed(False)
    if _tell_running_instance():
        log.info("Already running; asked the other instance to show itself")
        return 0

    # Imported after QApplication exists.
    from winauto.runtime import Runtime
    from winauto.ui.async_util import run_async
    from winauto.ui.controller import Controller, QtConfirmer
    from winauto.ui.popup import PopupWindow
    from winauto.ui.settings import SettingsDialog
    from winauto.ui.theme import app_icon, base_font, palette, stylesheet
    from winauto.ui.tray import Tray, pretty_hotkey
    from winauto.winos.hotkey import HotkeyListener
    from winauto.winos.startup import set_start_with_windows

    icon = app_icon()
    app.setWindowIcon(icon)
    app.setFont(base_font())
    pal = palette()
    app.setStyleSheet(stylesheet(pal))

    popup = PopupWindow(pal)
    confirmer = QtConfirmer()
    controller = Controller(popup, confirmer)
    signals = _Signals()
    signals.toggle.connect(popup.toggle)
    signals.show.connect(popup.show_popup)

    state: dict[str, object] = {"hotkey": None, "settings": None}

    def open_path(path) -> None:
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))

    def quit_app() -> None:
        app.quit()

    tray = Tray(
        icon,
        "ctrl+alt+space",
        on_open=popup.show_popup,
        on_settings=lambda: open_settings(),
        on_data_folder=lambda: open_path(data_dir()),
        on_log=lambda: open_path(log_dir() / "winauto.log"),
        on_quit=quit_app,
    )
    tray.show()

    runtime = Runtime(confirmer, notify=tray.notify, on_status=controller.on_status)
    controller.runtime = runtime
    runtime.ctx.services["show_popup"] = signals.show.emit
    runtime.start()
    tray.set_hotkey(runtime.config.hotkey)

    def register_hotkey() -> None:
        old = state["hotkey"]
        if old is not None:
            old.stop()  # type: ignore[attr-defined]
        listener = HotkeyListener(runtime.config.hotkey, signals.toggle.emit)
        if not listener.start():
            log.warning("Hotkey: %s", listener.error)
            if sys.platform == "win32":
                popup.add_bot(f"Hotkey problem: {listener.error}", error=True)
        state["hotkey"] = listener

    def open_settings() -> None:
        dialog = SettingsDialog(runtime.config, popup if popup.isVisible() else None)
        state["settings"] = dialog

        def saved(cfg) -> None:
            hotkey_changed = cfg.hotkey != runtime.config.hotkey
            runtime.apply_config(cfg)
            try:
                set_start_with_windows(cfg.start_with_windows)
            except OSError:
                log.exception("Couldn't update start-with-Windows")
            if hotkey_changed:
                register_hotkey()
                tray.set_hotkey(cfg.hotkey)
            check_model()

        dialog.saved.connect(saved)
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()

    popup.settings_requested.connect(open_settings)

    def check_model() -> None:
        def done(result, error) -> None:
            ok, msg = result if result else (False, str(error))
            if not ok:
                popup.add_bot(f"⚠ {msg}\n\nQuick commands still work in the meantime.", error=True)
            log.info("Model check: %s", msg)

        run_async(runtime.llm.check, done)

    # Second launches ask this instance to show itself.
    server = QLocalServer()
    QLocalServer.removeServer(SERVER_NAME)
    server.listen(SERVER_NAME)

    def on_connection() -> None:
        conn = server.nextPendingConnection()
        if conn:
            conn.readyRead.connect(lambda: (conn.readAll(), popup.show_popup()))

    server.newConnection.connect(on_connection)

    register_hotkey()
    first_run = runtime.db.get_value("welcomed") is None
    if first_run or not background:
        popup.add_bot(WELCOME.format(hotkey=pretty_hotkey(runtime.config.hotkey)))
        runtime.db.set_value("welcomed", "1")
    check_model()
    if not background or first_run:
        popup.show_popup()
    elif sys.platform == "win32":
        tray.notify("WinAuto is running", f"Press {pretty_hotkey(runtime.config.hotkey)} to open it.")

    code = app.exec()
    listener = state["hotkey"]
    if listener is not None:
        listener.stop()  # type: ignore[attr-defined]
    runtime.stop()
    return code


if __name__ == "__main__":
    os._exit(main())
