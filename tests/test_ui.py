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
    """The parts of winauto.runtime.Runtime the controller uses."""

    def __init__(self, agent, ctx):
        from winauto.services.home import HomeService
        from winauto.services.voice import VoiceService
        from winauto.services.writing import WritingTools

        self.agent = agent
        self.registry = agent.registry
        self.ctx = ctx
        self.config = ctx.config
        self.home = HomeService(ctx, self.registry)
        self.writing = WritingTools(ctx)
        self.voice = VoiceService(ctx)


def _setup(qapp, ctx, llm):
    from winauto.ui.cards import ConfirmCard
    from winauto.ui.controller import Controller, QtConfirmer
    from winauto.ui.popup import PopupWindow
    from winauto.ui.theme import DARK

    popup = PopupWindow(DARK)
    confirmer = QtConfirmer()
    controller = Controller(popup, confirmer)
    reg = Registry()
    skill = Demo()
    reg.add(skill)
    controller.runtime = _Runtime(Agent(reg, llm, confirmer, on_status=controller.on_status), ctx)
    return popup, controller, skill, ConfirmCard


def _cards(popup, card_cls):
    return popup.conversation.findChildren(card_cls)


def _bubble_texts(popup):
    return [w.text() for w in popup.conversation.findChildren(QtWidgets.QLabel) if w.objectName() == "BotBubble"]


def test_full_request_with_confirmation(qapp, ctx):
    llm = ScriptedLLM(("send", {"to": "bo", "body": "draft"}))
    popup, controller, skill, card_cls = _setup(qapp, ctx, llm)
    popup.input.setText("tell bo hi")
    popup._submit()
    assert wait_for(qapp, lambda: _cards(popup, card_cls))
    card = _cards(popup, card_cls)[0]
    card._fields["body"].setPlainText("edited body")
    card.ok_btn.click()
    assert wait_for(qapp, lambda: any("Sent to bo" in t for t in _bubble_texts(popup)))
    assert skill.sent == [("bo", "edited body")]
    assert not popup.is_busy() and popup.mode == "chat"


def test_stop_cancels_waiting_card(qapp, ctx):
    llm = ScriptedLLM(("send", {"to": "bo", "body": "draft"}))
    popup, controller, skill, card_cls = _setup(qapp, ctx, llm)
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

    dialog = SettingsDialog(Config(), skills=[("apps", "Open apps"), ("notes", "Notes")])
    dialog.model.setCurrentText("llama3.1:8b")
    dialog._skill_toggles["notes"].setChecked(False)
    dialog.hotkey.setText("ctrl+shift+k")
    got = []
    dialog.saved.connect(got.append)
    dialog._save()
    assert got and got[0].llm.model == "llama3.1:8b" and got[0].hotkey == "ctrl+shift+k"
    assert got[0].disabled_skills == ["notes"]
    dialog2 = SettingsDialog(Config())
    dialog2.hotkey.setText("banana")
    dialog2._save()
    assert "Unknown key" in dialog2.error.text()


def test_hotkey_parsing():
    from winauto.adapters.winos.hotkey import MOD_ALT, MOD_CONTROL, parse_hotkey

    assert parse_hotkey("ctrl+alt+space") == (MOD_CONTROL | MOD_ALT, 0x20)
    assert parse_hotkey("Ctrl + Alt + K") == (MOD_CONTROL | MOD_ALT, ord("K"))
    assert parse_hotkey("alt+f1")[1] == 0x70
    for bad in ("space", "ctrl+alt", "ctrl+a+b"):
        with pytest.raises(ValueError):
            parse_hotkey(bad)


def test_launcher_flow(qapp, ctx):
    """Typing shows results; Enter runs the selected one; copy results flash and hide."""
    from winauto.runtime import Runtime
    from winauto.ui.controller import Controller, QtConfirmer
    from winauto.ui.popup import PopupWindow
    from winauto.ui.theme import LIGHT

    popup = PopupWindow(LIGHT)
    confirmer = QtConfirmer()
    controller = Controller(popup, confirmer)
    rt = Runtime(confirmer, db=ctx.db, llm=ScriptedLLM("Paris."))
    controller.attach(rt)
    popup.show_popup()
    assert popup.mode == "home" and popup.home.list.count() >= 3
    popup.input.setText("12*7")
    assert popup.mode == "results"
    assert wait_for(qapp, lambda: popup.results.count() > 0)
    top = popup.results.current()
    assert top.title == "= 84"
    # Writing tools mode
    controller.open_text_mode("teh quick brown fox")
    assert popup.mode == "text" and "teh quick" in popup.text_view.quote.text()
    # Streaming tokens create a live bubble
    popup.clear()
    popup.stream_token("")
    popup.stream_token("Hello ")
    popup.stream_token("world")
    assert popup.mode == "chat" and popup.chat._stream_text == "Hello world"
