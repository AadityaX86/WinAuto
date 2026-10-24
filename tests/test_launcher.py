from __future__ import annotations

import pytest
from fakes import RecordingConfirmer, ScriptedLLM
from test_apps import FakeWindowsApps
from test_phase3 import FakeClipboard

from winauto.core.launcher import ASK_TOOL, FILL_TOOL
from winauto.skills.shortcuts import ShortcutsSkill, fill_placeholders
from winauto.skills.tools import (
    ToolsSkill,
    color_formats,
    make_password,
    parse_color,
    search_emoji,
)


@pytest.fixture
def runtime(ctx):
    from winauto.runtime import Runtime

    rt = Runtime(RecordingConfirmer(), db=ctx.db, llm=ScriptedLLM())
    apps = rt.ctx.skill("apps")
    apps.backend = FakeWindowsApps()
    apps.refresh()
    return rt


def top(rt, query):
    results = rt.launcher.search(query)
    return results[0] if results else None


def test_launcher_apps_and_ask(runtime):
    r = top(runtime, "spo")
    assert (r.tool, r.args, r.kind) == ("open_app", {"name": "Spotify"}, "App")
    # A sentence goes to the assistant first.
    r = top(runtime, "email ram about the meeting tomorrow")
    assert r.tool == ASK_TOOL and r.args == {"text": "email ram about the meeting tomorrow"}
    # Ask AI is always offered.
    assert any(s.tool == ASK_TOOL for s in runtime.launcher.search("spo"))


def test_launcher_windows_and_settings(runtime):
    results = runtime.launcher.search("gmail")
    assert any(s.kind == "Window" and s.args == {"name": "Inbox - Gmail - Google Chrome"} for s in results)
    assert any(s.title == "Open Gmail" for s in results)
    r = top(runtime, "bluetooth")
    assert r.tool in ("open_settings", "bluetooth")
    assert any(s.title == "Bluetooth settings" for s in runtime.launcher.search("bluetooth"))
    assert top(runtime, "lock").title in ("Lock PC", "Lock")


def test_launcher_inline_answers(runtime):
    r = top(runtime, "12*7")
    assert (r.title, r.tool, r.args) == ("= 84", "set_clipboard", {"text": "84"})
    r = top(runtime, "10 km to miles")
    assert r.title == "= 6.2137 miles"
    r = top(runtime, "#ff8800")
    assert r.kind == "Colour" and r.icon == "swatch:#FF8800"
    r = top(runtime, ":party")
    assert r.kind == "Emoji" and "🥳" in r.title
    r = top(runtime, "> ipconfig")
    assert (r.tool, r.args) == ("run_command", {"command": "ipconfig"})
    assert top(runtime, "password").tool == "set_clipboard"
    assert top(runtime, "/resume").tool == "find_files"


def test_launcher_quick_command_result(runtime):
    r = top(runtime, "volume 30")
    assert (r.tool, r.args, r.kind) == ("set_volume", {"level": 30}, "Command")


def test_launcher_notes_routines_contacts(runtime):
    skills = runtime.ctx.skills
    skills["notes"].add_note("Wifi password is on the router", title="Wifi password")
    skills["routines"].create_routine("work mode", ["todo check email"])
    skills["contacts"].add_contact("Sita Karki", email="sita@example.com")
    assert any(s.tool == "read_note" for s in runtime.launcher.search("wifi"))
    assert top(runtime, "work mode").tool == "run_routine"
    assert any(s.kind == "Contact" for s in runtime.launcher.search("sita"))


# ---------------- shortcuts ----------------

@pytest.fixture
def shortcuts(ctx):
    opened, pasted = [], []
    cb = FakeClipboard()
    skill = ShortcutsSkill(ctx, opener=opened.append, clipboard=cb, paste=lambda: pasted.append(cb.text))
    return skill, opened, pasted, cb


def test_quicklinks(shortcuts):
    skill, opened, _, _ = shortcuts
    assert skill.add_quicklink("gh", "github.com/search?q={query}").ok
    assert skill.add_quicklink("mail", "https://mail.google.com").ok
    assert skill.open_quicklink("gh", "winauto python").ok
    assert opened[-1] == "https://github.com/search?q=winauto+python"
    s = skill.suggest("gh local ai")[0]
    assert (s.tool, s.args) == ("open_quicklink", {"name": "gh", "query": "local ai"})
    assert "**gh**" in skill.list_quicklinks().message
    assert skill.delete_quicklink("mail").ok and not skill.open_quicklink("mail").ok


def test_snippets(shortcuts, ctx):
    skill, _, pasted, cb = shortcuts
    assert skill.add_snippet("sig", "Thanks,\nAaditya — {date}").ok
    r = skill.paste_snippet("sig")
    assert r.ok and pasted and pasted[0].startswith("Thanks,\nAaditya — ")
    assert "{date}" not in cb.text
    assert skill.suggest("paste si")[0].tool == "paste_snippet"
    assert fill_placeholders("{clipboard}!", lambda: "hi") == "hi!"


def test_shortcut_quick_rules(shortcuts):
    from winauto.core.quick import QuickMatcher
    from winauto.core.registry import Registry

    skill = shortcuts[0]
    reg = Registry()
    reg.add(skill)
    q = QuickMatcher(reg)
    assert q.match("add quicklink yt https://youtube.com/results?search_query={query}").name == "add_quicklink"
    skill.add_quicklink("yt", "https://youtube.com/results?search_query={query}")
    assert q.match("yt lofi").arguments == {"name": "yt", "query": "lofi"}
    assert q.match("save snippet address: 12 Lake Road, Pokhara").arguments == {"name": "address", "text": "12 Lake Road, Pokhara"}
    skill.add_snippet("address", "12 Lake Road")
    assert q.match("paste my address").name == "paste_snippet"


# ---------------- tools ----------------

def test_tools_helpers():
    assert parse_color("#f80") == (255, 136, 0)
    assert parse_color("rgb(255, 136, 0)") == (255, 136, 0)
    assert parse_color("hsl(32, 100%, 50%)") == (255, 136, 0)
    assert parse_color("banana") is None
    assert color_formats((255, 136, 0))["hsl"] == "hsl(32, 100%, 50%)"
    pw = make_password(20)
    assert len(pw) == 20 and any(c.isdigit() for c in pw) and any(not c.isalnum() for c in pw)
    assert search_emoji("party")[0][1] == "🥳"
    assert search_emoji("love")


def test_tools_skill(ctx):
    cb = FakeClipboard()
    skill = ToolsSkill(ctx, clipboard=cb, fetcher=lambda url, **kw: ("203.0.113.7\n", url))
    r = skill.generate_password(12)
    assert r.ok and len(cb.text) == 12 and "(copied)" in r.message
    assert skill.find_emoji("fire").message.startswith("🔥 copied")
    assert skill.convert_color("#00ff00").data["rgb"] == "rgb(0, 255, 0)"
    assert "Public IP: 203.0.113.7" in skill.network_info().message
    assert "Run this command?" in skill.preview("run_command", {"command": "dir"})


def titles(rt, query, n=4):
    return [s.title for s in rt.launcher.search(query)[:n]]


def test_command_rows_say_what_will_happen(runtime):
    # The instant-command row names the action in plain words, not the typed text.
    assert top(runtime, "todo buy milk").title == "Add todo: buy milk"
    assert top(runtime, "show my todos").title == "Show todos"  # default arguments are left out
    assert top(runtime, "vol 50").title == "Set volume to 50%"
    assert top(runtime, "shutdown in 10 minutes").title == "Shut down in 10 min"
    assert top(runtime, "youtube lofi").title == "Search YouTube for “lofi”"
    assert top(runtime, "remind me to stretch in 30 minutes").title.startswith("Remind me to stretch · ")
    assert top(runtime, "100 usd to npr").title == "Convert 100 USD to NPR"


def test_command_title_fallbacks():
    from winauto.core.launcher import command_title

    assert command_title("add_todo", {"task": "milk"}) == "Add todo: milk"
    assert command_title("dark_mode", {"on": True}) == "Dark mode: on"
    assert command_title("set_reminder", {"text": "x", "when": "2026-10-24 18:00"}).startswith("Set reminder: x, ")


def test_templates_start_common_commands(runtime):
    assert titles(runtime, "rem")[0] == "Remind me to…" and "Show my reminders" in titles(runtime, "rem")
    assert "Set a timer…" in titles(runtime, "timer")
    assert titles(runtime, "email")[:2] == ["Check my email", "Write an email…"]
    assert "Message on WhatsApp…" in titles(runtime, "whatsapp")
    assert "Add a todo…" in titles(runtime, "todo")
    r = next(s for s in runtime.launcher.search("rem") if s.title == "Remind me to…")
    assert (r.tool, r.args, r.kind) == (FILL_TOOL, {"text": "remind me to "}, "Fill in")


def test_volume_and_search_words(runtime):
    assert titles(runtime, "volume", 3) == ["Volume up", "Volume down", "Set volume to…"]
    assert "Brightness up" in titles(runtime, "brightness")
    # "google cats" searches for "cats", ahead of asking the AI
    r = top(runtime, "google cats")
    assert (r.tool, r.args["query"]) == ("search_web", "cats")
    # One "Open WhatsApp" result, not one per alias of the same page
    assert sum(s.tool == "open_website" for s in runtime.launcher.search("whatsapp")) == 1


def test_help_works_without_the_ai(runtime):
    assert top(runtime, "help").tool == "show_help"
    assert top(runtime, "what can you do").tool == "show_help"
    reply = runtime.agent.handle("help email")
    assert not reply.used_model and "check my email" in reply.text
    reply = runtime.agent.handle("what can you do")
    assert "Ctrl + Alt + Space" in reply.text and "Reminders" in reply.text
    # "help me …" is a request for the AI, not the help page
    assert top(runtime, "help me write an email to ram").tool == ASK_TOOL
