from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from winauto.core.quick import QuickMatcher
from winauto.core.registry import Registry
from winauto.skills.notes import NotesSkill


@pytest.fixture
def notes(ctx):
    return NotesSkill(ctx)


@pytest.fixture
def quick(notes):
    reg = Registry()
    reg.add(notes)
    return QuickMatcher(reg)


def test_notes_roundtrip(notes):
    r = notes.add_note("Wifi password is on the sticker under the router")
    assert r.ok and r.message.startswith("Saved note #1")
    notes.add_note("Passport renewal: bring 2 photos and old passport", title="Passport")
    found = notes.search_notes("where is my wifi password?")
    assert found.ok and found.data["notes"][0]["id"] == 1
    assert "No notes" in notes.search_notes("bananas").message
    assert "#2 **Passport**" in notes.list_notes().message
    assert notes.append_to_note(2, "Fee is 5000").ok
    assert "Fee is 5000" in notes.read_note(2).message
    assert notes.delete_note(1).ok and not notes.read_note(1).ok
    assert "Delete note #2: Passport?" == notes.preview("delete_note", {"note_id": 2})


def test_todos_due_dates(notes):
    r = notes.add_todo("call mom tomorrow 6pm")
    assert r.ok and "call mom" in r.message and "tomorrow 6:00 PM" in r.message
    row = notes.db.one("SELECT * FROM todos WHERE id = 1")
    assert row["text"] == "call mom" and row["due_has_time"] == 1
    r = notes.add_todo("pay rent", due="friday")
    assert "due" in r.message
    r = notes.add_todo("water plants", due="whenever")
    assert "didn't understand" in r.message
    assert notes.add_todo("URGENT fix laptop").ok
    listing = notes.list_todos().message
    assert listing.splitlines()[1].startswith("- ‼ #4")  # high priority first


def test_overdue_and_today(notes):
    yesterday = (datetime.now() - timedelta(days=1)).replace(microsecond=0)
    notes.db.execute("INSERT INTO todos(text, due_at, due_has_time, created_at) VALUES('old thing', ?, 1, 'x')",
                     (yesterday.isoformat(sep=" "),))
    notes.add_todo("later thing", due="in 3 days")
    assert "old thing" in notes.list_todos("overdue").message
    assert "later thing" not in notes.list_todos("today").message
    assert "⚠ overdue" in notes.list_todos().message
    assert "later thing" in notes.list_todos("upcoming").message


def test_complete_update_delete(notes):
    notes.add_todo("buy milk")
    notes.add_todo("book dentist appointment")
    r = notes.complete_todo("dentist")
    assert r.ok and "book dentist appointment" in r.message and "1 left" in r.message
    assert notes.complete_todo("#1").ok
    assert not notes.complete_todo("dentist").ok  # already done, not open anymore
    assert "Done:" in notes.list_todos("done").message
    assert notes.update_todo("1", due="tomorrow").ok
    assert notes.update_todo("milk", text="buy oat milk").ok
    assert notes.db.one("SELECT text FROM todos WHERE id = 1")["text"] == "buy oat milk"
    assert notes.clear_done_todos().message == "Cleared 2 finished todo(s)."
    assert notes.list_todos().message == "Your todo list is empty. 🎉"


@pytest.mark.parametrize("text, tool, args", [
    ("todo call mom tomorrow 6pm", "add_todo", {"task": "call mom tomorrow 6pm"}),
    ("add todo: buy milk", "add_todo", {"task": "buy milk"}),
    ("add eggs to my list", "add_todo", {"task": "eggs"}),
    ("task: renew passport", "add_todo", {"task": "renew passport"}),
    ("show my todos", "list_todos", {"which": "open"}),
    ("todos", "list_todos", {"which": "open"}),
    ("show today's tasks", "list_todos", {"which": "today"}),
    ("my todos for today", "list_todos", {"which": "today"}),
    ("what's on my list", "list_todos", {"which": "open"}),
    ("what do i have to do today", "list_todos", {"which": "today"}),
    ("mark 3 as done", "complete_todo", {"todo": "3"}),
    ("done buy milk", "complete_todo", {"todo": "buy milk"}),
    ("note that the spare key is with Sita", "add_note", {"text": "the spare key is with Sita"}),
    ("remember the car is parked on level 3", "add_note", {"text": "the car is parked on level 3"}),
    ("show my notes", "list_notes", {}),
    ("search notes for wifi", "search_notes", {"query": "wifi"}),
])
def test_quick_rules(quick, text, tool, args):
    call = quick.match(text)
    assert call is not None, text
    assert (call.name, call.arguments) == (tool, args)


@pytest.mark.parametrize("text", ["task manager", "what is today", "open task manager", "notepad"])
def test_quick_rules_leave_alone(quick, text):
    assert quick.match(text) is None
