"""Application services (winauto/services), the typed context ports, and home-screen widgets."""

from __future__ import annotations

from datetime import datetime, timedelta

from fakes import RecordingConfirmer, ScriptedLLM

from winauto.core.context import Host
from winauto.core.llm import ToolCall
from winauto.core.registry import Registry
from winauto.core.skill import Skill, Widget, ok, tool
from winauto.services.history import CommandHistory
from winauto.services.home import HomeService
from winauto.services.settings import SettingsService
from winauto.services.voice import VoiceService
from winauto.services.writing import WritingTools
from winauto.skills.calendar import CalendarSkill
from winauto.skills.notes import NotesSkill
from winauto.skills.reminders import RemindersSkill
from winauto.skills.textactions import TextActionsSkill
from winauto.skills.web import WebSkill

# ---------------- ports ----------------


def test_host_defaults_are_headless():
    host = Host()
    assert host.hide() is False and host.last_window is None and host.selection == ""
    host.show()  # no popup: nothing happens
    calls = []
    host = Host(show_popup=lambda: calls.append("show"), hide_popup=lambda: calls.append("hide"))
    assert host.hide() is True
    host.show()
    assert calls == ["hide", "show"]


def test_runtime_is_the_assistant_skills_see(ctx):
    from winauto.runtime import Runtime

    rt = Runtime(RecordingConfirmer(), db=ctx.db, llm=ScriptedLLM("Paris."))
    assert rt.ctx.assistant is rt
    assert rt.ctx.skill("notes") is not None and rt.ctx.skill("nope") is None
    assert rt.match_command("todo buy milk").name == "add_todo"
    assert rt.run_tool(ToolCall("add_todo", {"task": "buy milk"})).ok
    assert rt.complete("system", "capital of france?") == "Paris."


def test_skills_without_an_engine_fail_politely(ctx):
    skill = TextActionsSkill(ctx, clipboard=_Clip("teh text"))
    result = skill.transform_text("fix")
    assert not result.ok and "isn't available" in result.message


class _Clip:
    def __init__(self, text=""):
        self.text = text

    def get_text(self):
        return self.text

    def set_text(self, text):
        self.text = text


# ---------------- history and home ----------------


def test_history_keeps_latest_unique(ctx):
    h = CommandHistory(ctx.db)
    for text in ["open spotify", "todo milk", "open spotify", "  ", "volume 30"]:
        h.record(text)
    assert h.recent(5) == ["volume 30", "open spotify", "todo milk"]
    h.KEEP = 2
    h.record("lock")
    assert h.recent(5) == ["lock", "volume 30"]


class _Cards(Skill):
    name = "cards"
    description = "test"

    def widgets(self):
        return [Widget("cloud", "late", order=90), Widget("check", "early", order=5)]

    @tool("A tool.")
    def list_todos(self):
        return ok("none")


class _Broken(Skill):
    name = "broken"
    description = "test"

    def widgets(self):
        raise RuntimeError("boom")


def test_home_collects_widgets_and_suggestions(ctx):
    reg = Registry()
    reg.add(_Broken(ctx))
    reg.add(_Cards(ctx))
    home = HomeService(ctx, reg)
    assert [w.text for w in home.widgets()] == ["early", "late"]  # sorted; the broken skill is skipped
    assert [s.tool for s in home.suggestions()] == ["list_todos"]  # only tools that exist
    home.record("what's the weather")
    assert home.recent()[0].args == {"text": "what's the weather"}
    assert home.briefing_due() is False  # no briefing skill loaded


def test_skill_widgets(ctx):
    notes = NotesSkill(ctx)
    assert notes.widgets() == []
    notes.add_todo("pay bill", due="today")
    notes.add_todo("someday thing")
    assert notes.widgets()[0].text == "1 due today"

    now = datetime(2026, 10, 24, 9, 0)
    rem = RemindersSkill(ctx, clock=lambda: now, sound=lambda s: None)
    rem.set_reminder("call mom", (now + timedelta(hours=2)).isoformat(sep=" "))
    assert rem.widgets()[0].text == "call mom · 11:00 AM"

    cal = CalendarSkill(ctx, clock=lambda: now)
    cal.add_event("Dentist", (now + timedelta(hours=3)).isoformat(sep=" "), remind=False)
    assert cal.widgets()[0].text == "Dentist · 12:00 PM"

    calls = []

    def weather(url, timeout):
        calls.append(url)
        return {"current_condition": [{"temp_C": "18", "weatherDesc": [{"value": "Partly cloudy"}]}]}

    web = WebSkill(ctx, json_fetcher=weather)
    assert web.widgets()[0].text == "18° Partly cloudy"
    assert web.widgets()[0].text == "18° Partly cloudy" and len(calls) == 1  # cached for an hour


# ---------------- writing tools and voice ----------------


def test_writing_tools(ctx):
    tools = WritingTools(ctx)
    assert tools.actions() == []  # skill not loaded
    ctx.skills["textactions"] = TextActionsSkill(ctx)
    keys = [k for k, _, _ in tools.actions()]
    assert "fix" in keys and tools.label("fix") == "Fix grammar" and tools.label("zzz") == "zzz"
    tools.begin("some text")
    assert ctx.host.selection == "some text"
    tools.end()
    assert ctx.host.selection == ""


def test_voice_service_speaks_only_when_enabled(ctx):
    said = []

    class Voice:
        def say(self, text):
            said.append(text)

    ctx.skills["voice"] = Voice()
    voice = VoiceService(ctx)
    voice.speak_reply("hello")
    assert said == []
    ctx.config.speak_replies = True
    voice.speak_reply("hello")
    assert said == ["hello"]


def test_settings_service_checks_hotkeys():
    service = SettingsService()
    assert service.hotkey_error("ctrl+alt+space") is None
    assert "Unknown key" in service.hotkey_error("banana")
    assert service.version
