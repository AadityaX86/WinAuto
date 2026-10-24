"""Drives the real Qt widgets offscreen."""

from __future__ import annotations

import os
import time

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
QtWidgets = pytest.importorskip("PySide6.QtWidgets")
from fakes import ScriptedLLM  # noqa: E402
from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
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
    # Shortcuts are recorded by pressing them.
    QTest.keyClick(dialog.hotkey, Qt.Key.Key_K, Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier)
    assert dialog.hotkey.text() == "Ctrl + Shift + K"
    QTest.keyClick(dialog.text_hotkey, Qt.Key.Key_Backspace)  # turns writing tools' shortcut off
    dialog.hide_on_click.setChecked(False)
    got = []
    dialog.saved.connect(got.append)
    dialog._save()
    assert got and got[0].llm.model == "llama3.1:8b" and got[0].hotkey == "ctrl+shift+k"
    assert got[0].text_hotkey == "" and got[0].hide_on_click_away is False
    assert got[0].disabled_skills == ["notes"]
    dialog2 = SettingsDialog(Config())
    QTest.keyClick(dialog2.hotkey, Qt.Key.Key_K)  # no ctrl/alt/shift/win
    dialog2._save()
    assert "needs at least one of ctrl" in dialog2.error.text()
    dialog3 = SettingsDialog(Config())
    QTest.keyClick(dialog3.hotkey, Qt.Key.Key_T, Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.AltModifier)
    dialog3._save()
    assert "must be different" in dialog3.error.text()


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


def _app_popup(qapp, ctx, llm=None):
    from winauto.runtime import Runtime
    from winauto.ui.controller import Controller, QtConfirmer
    from winauto.ui.popup import PopupWindow
    from winauto.ui.theme import DARK

    popup = PopupWindow(DARK)
    confirmer = QtConfirmer()
    controller = Controller(popup, confirmer)
    rt = Runtime(confirmer, db=ctx.db, llm=llm or ScriptedLLM("ok"))
    controller.attach(rt)
    return popup, controller, rt


def test_templates_fill_the_search_box(qapp, ctx):
    popup, controller, _ = _app_popup(qapp, ctx)
    popup.show_popup()
    popup.input.setText("remi")
    assert wait_for(qapp, lambda: popup.results.count() > 0)
    top = popup.results.current()
    assert top.title == "Remind me to…" and top.kind == "Fill in"
    popup.suggestion_chosen.emit(top)
    # Nothing ran: the box now holds the start of the command, cursor at the end, ready to finish.
    assert popup.input.text() == "remind me to " and popup.input.cursorPosition() == len("remind me to ")
    assert popup.mode == "results" and not popup.has_chat


def test_welcome_card_until_got_it(qapp, ctx):
    popup, controller, rt = _app_popup(qapp, ctx)
    controller.refresh_home()
    card = popup.home.welcome
    assert not card.isHidden() and "Ctrl+Alt+Space" in card.message.text()
    assert not card.startup.isHidden()  # start with Windows is off by default
    card.done.click()
    assert card.isHidden() and not rt.home.welcome_due()
    controller.refresh_home()
    assert card.isHidden()  # stays gone


def test_popup_hides_on_click_away_unless_waiting(qapp, ctx):
    popup, controller, _ = _app_popup(qapp, ctx)
    popup.show_popup()
    popup._focus_left_winauto = lambda: True  # as if another app was clicked
    popup._hide_if_left()
    assert popup.isVisible()  # off unless Settings turns it on
    popup.hide_on_blur = True
    popup.set_busy(True)
    popup._hide_if_left()
    assert popup.isVisible()  # still working on something
    popup.set_busy(False)
    from winauto.core.agent import ConfirmRequest

    card = popup.add_card(ConfirmRequest("send", "Send this?", "", {"body": "hi"}, editable=("body",)))
    popup._hide_if_left()
    assert popup.isVisible()  # an approval is waiting
    card.cancel_btn.click()
    popup._hide_if_left()
    assert not popup.isVisible()


def test_card_editor_fits_its_text():
    from winauto.ui.cards import editor_lines

    assert editor_lines("short") == 3
    assert editor_lines("Hi Ram,\n\nThe meeting moved to 3pm.\n\nThanks,\nSita") == 6
    assert editor_lines("word " * 400) == 8  # long text scrolls inside the box
    assert editor_lines("dir", minimum=2) == 2


def test_reopening_later_starts_over(qapp, ctx):
    popup, controller, _ = _app_popup(qapp, ctx)
    popup.show_popup()
    popup.add_user("hi")
    popup.add_bot("Hello!")
    popup.hide()
    controller.maybe_start_over()
    assert popup.has_chat  # just closed: the conversation is still there
    popup._hidden_at -= 600  # ten minutes later
    controller.maybe_start_over()
    assert not popup.has_chat and popup.mode == "home"


def test_first_run_cards_are_not_squashed(qapp, ctx):
    """Welcome + AI download + a home chip on a first run: the cards keep their full height."""
    from winauto.services.ai_setup import SetupView

    popup, controller, _ = _app_popup(qapp, ctx)
    popup.show_popup()
    controller.refresh_home()
    popup.show_setup(SetupView(True, "Setting up your private AI", "Downloading Qwen3-VL 8B (5.8 GB, only this "
                               "once). Quick commands work meanwhile.", 0.4, "2.3 GB of 5.8 GB", "pause", "Pause"))
    popup.home.set_widgets([("cloud", "18° Partly cloudy")])
    wait_for(qapp, lambda: False, timeout=0.2)
    for card in (popup.home.welcome, popup.home.setup):
        assert card.isVisible() and card.height() >= card.heightForWidth(card.width()) - 1
    assert popup.home.widgets_row.count() == 0  # the chips wait until the welcome card is put away
    popup.home.welcome.done.click()
    assert popup.home.widgets_row.count() > 0
