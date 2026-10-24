"""Desktop app entry point: tray icon + hotkey + popup."""

from __future__ import annotations

import getpass
import logging
import os
import sys

from PySide6.QtCore import QObject, QTimer, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import QApplication

from winauto import APP_NAME
from winauto.log import setup_logging
from winauto.paths import data_dir, log_dir

log = logging.getLogger(__name__)

SERVER_NAME = f"WinAuto-{getpass.getuser()}"

WELCOME = """Hi! I'm **WinAuto**. Press **{hotkey}** anytime to open me, and **{text_hotkey}** with text selected for writing tools.

Type to search apps, settings and commands, or just ask:
- open spotify · snap chrome left · volume 30
- todo call mom tomorrow 6pm · remind me to stretch in 20 minutes
- email Ram that the meeting moved to 3pm
- what's on my screen? · good morning · 100 usd to npr
- `>` runs a terminal command, `:` finds emoji, `/` finds files"""


class _Signals(QObject):
    toggle = Signal()
    show = Signal()
    hide = Signal()
    text_mode = Signal(str)  # selected text for writing tools


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
    from winauto.adapters.winos.hotkey import HotkeyListener
    from winauto.adapters.winos.startup import set_start_with_windows
    from winauto.config import load_config
    from winauto.runtime import Runtime
    from winauto.services.settings import SettingsService
    from winauto.ui.async_util import run_async
    from winauto.ui.controller import Controller, QtConfirmer
    from winauto.ui.popup import PopupWindow
    from winauto.ui.settings import SettingsDialog
    from winauto.ui.theme import app_icon, apply_palette, base_font, palette, stylesheet
    from winauto.ui.tray import Tray, pretty_hotkey

    config = load_config()
    _upgrade_settings(config)
    icon = app_icon()
    app.setWindowIcon(icon)
    app.setFont(base_font())
    pal = palette(getattr(config, "theme", "system"))
    app.setStyleSheet(stylesheet(pal))
    apply_palette(app, pal)

    popup = PopupWindow(pal)
    popup_hwnd = int(popup.winId())  # read here: Qt widgets must only be touched on this thread
    confirmer = QtConfirmer()
    controller = Controller(popup, confirmer)
    signals = _Signals()

    state: dict[str, object] = {"hotkeys": [], "settings": None}

    def open_path(path) -> None:
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))

    tray = Tray(
        icon,
        config.hotkey,
        on_open=lambda: show_popup(),
        on_settings=lambda: open_settings(),
        on_data_folder=lambda: open_path(data_dir()),
        on_log=lambda: open_path(log_dir() / "winauto.log"),
        on_quit=app.quit,
        palette=pal,
    )
    tray.show()

    runtime = Runtime(confirmer, config=config, notify=tray.notify, on_status=controller.on_status)
    controller.attach(runtime)
    # The desktop shell skills see through ctx.host (thread-safe: these emit Qt signals).
    runtime.ctx.host.show_popup = signals.show.emit
    runtime.ctx.host.hide_popup = signals.hide.emit

    def show_popup() -> None:
        was_visible = popup.isVisible()
        popup.show_popup()
        if not was_visible:
            controller.refresh_home()
            QTimer.singleShot(250, controller.maybe_morning_briefing)

    def toggle_popup() -> None:
        if popup.isVisible() and popup.isActiveWindow():
            popup.hide()
        else:
            show_popup()

    signals.toggle.connect(toggle_popup)
    signals.show.connect(show_popup)
    signals.hide.connect(popup.hide)

    def remember_foreground() -> None:
        # Remember the window you were in, so "snap this left" and "replace selection" know where to go.
        if sys.platform == "win32" and not popup.isVisible():
            try:
                from winauto.adapters.winos.windows import WindowsLayout

                hwnd = WindowsLayout().foreground()
                if hwnd and hwnd != popup_hwnd:
                    runtime.ctx.host.last_window = hwnd
            except Exception:
                log.debug("couldn't read the foreground window", exc_info=True)

    def on_hotkey() -> None:
        remember_foreground()
        signals.toggle.emit()

    def on_text_hotkey() -> None:
        remember_foreground()
        selection = ""
        if sys.platform == "win32":
            try:
                from winauto.adapters.winos.selection import capture_selection

                selection = capture_selection()
            except Exception:
                log.exception("couldn't read the selection")
        signals.text_mode.emit(selection)

    def open_text_mode(selection: str) -> None:
        if not selection.strip():
            show_popup()
            popup.add_bot("Select some text in any app first, then press "
                          f"**{pretty_hotkey(runtime.config.text_hotkey)}** for writing tools.")
            return
        controller.open_text_mode(selection)
        popup.show_popup()

    signals.text_mode.connect(open_text_mode)

    runtime.start()

    def register_hotkeys() -> None:
        for old in state["hotkeys"]:  # type: ignore[union-attr]
            old.stop()
        listeners = []
        for combo, handler in ((runtime.config.hotkey, on_hotkey), (runtime.config.text_hotkey, on_text_hotkey)):
            if not combo:
                continue
            listener = HotkeyListener(combo, handler)
            if not listener.start():
                log.warning("Hotkey: %s", listener.error)
                if sys.platform == "win32":
                    popup.add_bot(f"Hotkey problem: {listener.error}", error=True)
            listeners.append(listener)
        state["hotkeys"] = listeners
        tray.set_hotkey(runtime.config.hotkey)

    def open_settings() -> None:
        skills = [(s.name, s.description, s.icon) for s in runtime.registry.skills]
        dialog = SettingsDialog(runtime.config, popup if popup.isVisible() else None, skills=skills, palette=pal,
                                service=SettingsService(runtime.ai_setup))
        state["settings"] = dialog

        def saved(cfg) -> None:
            hotkeys_changed = (cfg.hotkey, cfg.text_hotkey) != (runtime.config.hotkey, runtime.config.text_hotkey)
            ai_changed = (cfg.llm.backend, cfg.llm.builtin_model) != (runtime.config.llm.backend, runtime.config.llm.builtin_model)
            runtime.apply_config(cfg)
            if ai_changed and runtime.ai_setup.needed():
                runtime.ai_setup.start(user_asked=True)  # they picked a model: download it now
            controller.attach(runtime)
            try:
                set_start_with_windows(cfg.start_with_windows)
            except OSError:
                log.exception("Couldn't update start-with-Windows")
            if hotkeys_changed:
                register_hotkeys()
            check_model()

        dialog.saved.connect(saved)
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()

    popup.settings_requested.connect(open_settings)

    def check_model(try_start: bool = True) -> None:
        popup.show_setup(runtime.ai_setup.view())  # hides the built-in AI card when it's not in use
        if runtime.config.llm.backend == "builtin":
            # WinAuto's own AI: download it on first run, otherwise load it in the background.
            setup = runtime.ai_setup
            if setup.needed():
                setup.start()
            else:
                run_async(setup.load, lambda result, error: None)
            return
        popup.set_model_status(None, runtime.llm.model)

        def done(result, error) -> None:
            ok, msg = result if result else (False, str(error))
            log.info("Model check: %s", msg)
            popup.set_model_status(ok, runtime.llm.model if ok else "AI model offline")
            if ok:
                return
            if try_start and "isn't running" in msg:
                from winauto.adapters.winos.ollama import start_ollama

                if start_ollama():
                    log.info("Started Ollama; checking again shortly")
                    QTimer.singleShot(8000, lambda: check_model(try_start=False))
                    return
            popup.add_bot(f"⚠ {msg}\n\nQuick commands still work in the meantime.", error=True)

        run_async(runtime.llm.check, done)

    # Second launches ask this instance to show itself.
    server = QLocalServer()
    QLocalServer.removeServer(SERVER_NAME)
    server.listen(SERVER_NAME)

    def on_connection() -> None:
        conn = server.nextPendingConnection()
        if conn:
            conn.readyRead.connect(lambda: (conn.readAll(), show_popup()))

    server.newConnection.connect(on_connection)

    register_hotkeys()
    first_run = runtime.db.get_value("welcomed") is None
    if first_run:
        popup.add_bot(WELCOME.format(hotkey=pretty_hotkey(runtime.config.hotkey),
                                     text_hotkey=pretty_hotkey(runtime.config.text_hotkey)))
        runtime.db.set_value("welcomed", "1")
    check_model()
    if not background or first_run:
        show_popup()
    elif sys.platform == "win32":
        tray.notify("WinAuto is running", f"Press {pretty_hotkey(runtime.config.hotkey)} to open it.")

    code = app.exec()
    for listener in state["hotkeys"]:  # type: ignore[union-attr]
        listener.stop()
    runtime.stop()
    return code


def _upgrade_settings(config) -> None:
    """Settings from WinAuto 0.1 only knew Ollama: keep it if it's running, else use the built-in AI."""
    from winauto.adapters.llm import OllamaClient
    from winauto.config import save_config
    from winauto.services.ai_setup import upgrade_config

    def ollama_ready() -> bool:
        ok, _ = OllamaClient(base_url=config.llm.base_url, model=config.llm.model).check()
        return ok

    if upgrade_config(config, ollama_ready):
        log.info("Settings upgraded; AI backend: %s", config.llm.backend)
        save_config(config)


if __name__ == "__main__":
    os._exit(main())
