"""Drives the real Qt widgets offscreen."""

from __future__ import annotations

import os
import time

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
QtWidgets = pytest.importorskip("PySide6.QtWidgets")

from fakes import ScriptedLLM  # noqa: E402
from test_core import Demo  # noqa: E402
from winauto.config import Config  # noqa: E402
from winauto.core.agent import Agent  # noqa: E402
from winauto.core.registry import Registry  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    yield app


def wait_for(app, predicate, timeout=5.0):
    end = time.time() + timeout
    while time.time() < end:
        app.processEvents()
        if predicate():
            return True
        time.sleep(0.01)
    return False


class _Runtime:
    def __init__(self, agent):
        self.agent = agent


def _setup(qapp, llm):
    from winauto.ui.controller import Controller, QtConfirmer
    from winauto.ui.popup import ConfirmCard, PopupWindow
    from winauto.ui.theme import DARK

    popup = PopupWindow(DARK)
    confirmer = QtConfirmer()
    controller = Controller(popup, confirmer)
    reg = Registry()
    skill = Demo()
    reg.add(skill)
    controller.runtime = _Runtime(Agent(reg, llm, confirmer, on_status=controller.on_status))
    return popup, controller, skill, ConfirmCard


def _cards(popup, card_cls):
    return popup.conversation.findChildren(card_cls)


def _bubble_texts(popup):
    return [w.text() for w in popup.conversation.findChildren(QtWidgets.QLabel) if w.objectName() == "BotBubble"]


def test_full_request_with_confirmation(qapp):
    llm = ScriptedLLM(("send", {"to": "bo", "body": "draft"}))
    popup, controller, skill, card_cls = _setup(qapp, llm)
    popup.input.setText("tell bo hi")
    popup._submit()
    assert wait_for(qapp, lambda: _cards(popup, card_cls))
    card = _cards(popup, card_cls)[0]
    card._fields["body"].setPlainText("edited body")
    card.ok_btn.click()
    assert wait_for(qapp, lambda: any("Sent to bo" in t for t in _bubble_texts(popup)))
    assert skill.sent == [("bo", "edited body")]
    assert popup.send_btn.text() == "Send"


def test_stop_cancels_waiting_card(qapp):
    llm = ScriptedLLM(("send", {"to": "bo", "body": "draft"}))
    popup, controller, skill, card_cls = _setup(qapp, llm)
    controller.submit("tell bo hi")
    assert wait_for(qapp, lambda: _cards(popup, card_cls))
    controller.stop()
    assert wait_for(qapp, lambda: not controller.confirmer._pending)
    assert skill.sent == []
    # A new request works afterwards.
    llm.replies.append("hello again")
    controller.submit("hi")
    assert wait_for(qapp, lambda: any("hello again" in t for t in _bubble_texts(popup)))


def test_settings_dialog_collects_values(qapp):
    from winauto.ui.settings import SettingsDialog

    dialog = SettingsDialog(Config())
    dialog.model.setCurrentText("llama3.1:8b")
    dialog.hotkey.setText("ctrl+shift+k")
    got = []
    dialog.saved.connect(got.append)
    dialog._save()
    assert got and got[0].llm.model == "llama3.1:8b" and got[0].hotkey == "ctrl+shift+k"
    dialog2 = SettingsDialog(Config())
    dialog2.hotkey.setText("banana")
    dialog2._save()
    assert "Unknown key" in dialog2.error.text()


def test_hotkey_parsing():
    from winauto.winos.hotkey import MOD_ALT, MOD_CONTROL, parse_hotkey

    assert parse_hotkey("ctrl+alt+space") == (MOD_CONTROL | MOD_ALT, 0x20)
    assert parse_hotkey("Ctrl + Alt + K") == (MOD_CONTROL | MOD_ALT, ord("K"))
    assert parse_hotkey("alt+f1")[1] == 0x70
    for bad in ("space", "ctrl+alt", "ctrl+a+b"):
        with pytest.raises(ValueError):
            parse_hotkey(bad)
