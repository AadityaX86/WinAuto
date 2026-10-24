from __future__ import annotations

import os
import time
from pathlib import Path

import pytest

from fakes import RecordingConfirmer, ScriptedLLM
from winauto.core.quick import QuickMatcher
from winauto.core.registry import Registry
from winauto.skills.clipboard import ClipboardSkill
from winauto.skills.contacts import ContactsSkill
from winauto.skills.discord import DiscordSkill
from winauto.skills.files import FilesSkill, kind_of
from winauto.skills.media import MediaSkill, first_youtube_video
from winauto.skills.window_layout import WindowLayoutSkill, layout_rect
from winauto.winos.apps import WindowInfo


# ---------------- discord ----------------

class FakeDiscord:
    def __init__(self):
        self.calls = []
        self.focus_ok = True

    def open_dm(self, target):
        self.calls.append(("open", target))
        return True

    def type_message(self, text, send):
        self.calls.append(("type", text, send))
        return self.focus_ok


@pytest.fixture
def discord(ctx):
    ContactsSkill(ctx).add_contact("Sita Karki", discord="sita_k", nickname="didi")
    ContactsSkill(ctx).add_contact("Ram Sharma", email="ram@example.com")
    backend = FakeDiscord()
    return DiscordSkill(ctx, backend), backend


def test_discord_send(discord, ctx):
    skill, backend = discord
    r = skill.send_discord("didi", "gg wp")
    assert r.ok and backend.calls == [("open", "@sita_k"), ("type", "gg wp", True)]
    assert skill.preview("send_discord", {"to": "didi"}) == "Discord to Sita Karki (@sita_k)"
    assert skill.send_discord("#general", "hello all").ok and backend.calls[-2] == ("open", "#general")
    assert skill.send_discord("someone_else", "yo").ok and backend.calls[-2] == ("open", "@someone_else")
    # A known contact without a Discord name is an error, not a guess.
    r = skill.send_discord("ram", "hi")
    assert not r.ok and "Discord username" in r.message
    ctx.config.messaging.discord_auto_send = False
    assert "Press Enter" in skill.send_discord("didi", "hi").message
    backend.focus_ok = False
    assert "nothing was sent" in skill.send_discord("didi", "hi").message


def test_discord_quick(discord):
    reg = Registry()
    reg.add(discord[0])
    call = QuickMatcher(reg).match("discord didi: are you on tonight?")
    assert (call.name, call.arguments) == ("send_discord", {"to": "didi", "message": "are you on tonight?"})


# ---------------- files ----------------

@pytest.fixture
def tree(tmp_path):
    home = tmp_path / "home"
    for d in ("Desktop", "Documents", "Downloads", "Pictures"):
        (home / d).mkdir(parents=True)
    files = {
        "Documents/Resume 2026.pdf": 2000, "Documents/old/Resume 2019.docx": 1000,
        "Documents/budget.xlsx": 500, "Downloads/setup.exe": 9000, "Downloads/holiday.jpg": 3000,
        "Downloads/song.mp3": 100, "Downloads/notes.txt": 10, "Downloads/big.zip": 50000,
        "Downloads/partial.crdownload": 5, "Pictures/passport photo.png": 700,
        "Documents/node_modules/resume.js": 1,
    }
    for rel, size in files.items():
        p = home / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"x" * size)
    old = time.time() - 400 * 86400
    os.utime(home / "Documents/old/Resume 2019.docx", (old, old))
    return home


@pytest.fixture
def files(ctx, tree):
    opened, trashed = [], []
    skill = FilesSkill(ctx, roots=[tree / d for d in ("Desktop", "Documents", "Downloads", "Pictures")],
                       opener=opened.append, trash=trashed.append)
    return skill, opened, trashed, tree


def test_find_and_open(files):
    skill, opened, _, tree = files
    r = skill.find_files("resume")
    names = [Path(p).name for p in r.data["files"]]
    assert names[:2] == ["Resume 2026.pdf", "Resume 2019.docx"] and "resume.js" not in names
    assert [Path(p).name for p in skill.find_files("resume", kind="pdf").data["files"]] == ["Resume 2026.pdf"]
    assert skill.open_file("passport photo").ok and opened[-1].endswith("passport photo.png")
    assert not skill.open_file("nonexistent thing").ok
    assert skill.open_folder("downloads").ok and opened[-1] == str(tree / "Downloads")


def test_organize_downloads(files):
    skill, _, _, tree = files
    preview = skill.preview("organize_downloads", {})
    assert "Installers: 1 file(s)" in preview and "Images: 1 file(s)" in preview
    r = skill.organize_downloads()
    assert r.ok and "Moved 5 file(s)" in r.message
    assert (tree / "Downloads/Installers/setup.exe").exists()
    assert (tree / "Downloads/partial.crdownload").exists()  # unfinished downloads stay put
    assert skill.organize_downloads().message == "Downloads is already tidy."


def test_largest_recent_delete_create(files):
    skill, _, trashed, tree = files
    assert skill.largest_files("downloads").message.splitlines()[1].startswith("1. **big.zip**")
    assert "**notes.txt**" in skill.recent_files("downloads").message
    target = tree / "Downloads/notes.txt"
    assert skill.delete_file(str(target)).ok and trashed == [str(target)]
    assert not skill.delete_file("notes.txt").ok  # needs a full path
    assert skill.create_folder("Taxes 2026", "documents").ok and (tree / "Documents/Taxes 2026").is_dir()


def test_kind_of():
    assert kind_of(Path("a.PNG")) == "image" and kind_of(Path("a.pdf")) == "document" and kind_of(Path("a.xyz")) == "other"


# ---------------- clipboard ----------------

class FakeClipboard:
    def __init__(self):
        self.text = ""
        self.seq = 0

    def sequence(self):
        return self.seq

    def get_text(self):
        return self.text

    def set_text(self, t):
        self.text = t
        self.seq += 1


def test_clipboard(ctx):
    cb = FakeClipboard()
    skill = ClipboardSkill(ctx, cb, watch=False)
    assert not skill.get_clipboard().ok
    for t in ("first", "second", "first"):
        cb.set_text(t)
        skill.capture()
    assert list(skill.history) == ["first", "second"]
    assert skill.get_clipboard().data["text"] == "first"
    assert skill.copy_from_history(2).ok and cb.text == "second"
    assert skill.set_clipboard("hello").ok and cb.text == "hello"
    assert "1. hello" in skill.clipboard_history().message


# ---------------- media ----------------

class FakeMedia:
    def __init__(self):
        self.keys, self.opened = [], []

    def press(self, vk):
        self.keys.append(vk)

    def now_playing(self):
        return {"title": "Blinding Lights", "artist": "The Weeknd", "app": "Spotify.exe", "status": "Playing"}

    def open(self, target):
        self.opened.append(target)


def test_media(ctx):
    backend = FakeMedia()
    yt_html = 'xx"videoRenderer":{"videoId":"dQw4w9WgXcQ","thumb"'
    skill = MediaSkill(ctx, backend, fetcher=lambda url, **kw: (yt_html, url))
    assert skill.play_pause().ok and backend.keys == [0xB3]
    assert skill.now_playing().message == "🎵 Blinding Lights by The Weeknd, in Spotify."
    r = skill.play_music("lofi beats")
    assert r.message == "Playing “lofi beats” on YouTube." and backend.opened[-1].endswith("v=dQw4w9WgXcQ")
    assert skill.play_music("jazz", "spotify").ok and backend.opened[-1] == "spotify:search:jazz"
    assert first_youtube_video("nothing here") is None


# ---------------- windows layout ----------------

class FakeLayout:
    def __init__(self):
        self.placed, self.shown = [], []

    def work_area(self, hwnd):
        return (0, 0, 1920, 1040)

    def place(self, hwnd, x, y, w, h):
        self.placed.append((hwnd, x, y, w, h))

    def show(self, hwnd, cmd):
        self.shown.append((hwnd, cmd))

    def screenshot(self, folder, hwnd=None):
        return folder / "shot.png"


class FakeApps:
    def find_windows(self, name):
        return [WindowInfo(42, "Chrome", 1, "chrome")] if name == "chrome" else []


def test_layout(ctx):
    backend = FakeLayout()
    skill = WindowLayoutSkill(ctx, backend, apps=FakeApps())
    assert layout_rect("right", (0, 0, 1920, 1040)) == (960, 0, 960, 1040)
    assert skill.arrange_window("left", "chrome").ok and backend.placed[-1] == (42, 0, 0, 960, 1040)
    assert not skill.arrange_window("left", "").ok  # no remembered window yet
    ctx.services["last_window"] = 77
    assert skill.arrange_window("maximize").ok and backend.shown[-1] == (77, 3)
    assert not skill.arrange_window("left", "zoom").ok
    assert skill.take_screenshot("screen").ok


# ---------------- whole-app routing and routines ----------------

@pytest.fixture
def runtime(ctx):
    from winauto.runtime import Runtime

    rt = Runtime(RecordingConfirmer(), db=ctx.db, llm=ScriptedLLM())
    return rt


@pytest.mark.parametrize("text, tool", [
    ("open downloads", "open_folder"),
    ("open my documents folder", "open_folder"),
    ("find my resume pdf", "find_files"),
    ("where is my passport photo", "find_files"),
    ("organize my downloads", "organize_downloads"),
    ("what's taking up space", "largest_files"),
    ("pause", "play_pause"),
    ("pause the music", "play_pause"),
    ("next song", "next_track"),
    ("what's playing", "now_playing"),
    ("play lofi beats on youtube", "play_music"),
    ("play despacito", "play_music"),
    ("stop the timer", "cancel_reminder"),
    ("snap chrome to the left", "arrange_window"),
    ("snap left", "arrange_window"),
    ("maximize", "arrange_window"),
    ("minimize everything", "show_desktop"),
    ("take a screenshot", "take_screenshot"),
    ("put chrome and vs code side by side", "side_by_side"),
    ("what's on my clipboard", "get_clipboard"),
    ("clipboard history", "clipboard_history"),
    ("copy 2", "copy_from_history"),
    ("discord didi: hi", "send_discord"),
    ("whatsapp didi: hi", "send_whatsapp"),
    ("volume 30", "set_volume"),
    ("todo buy milk", "add_todo"),
    ("12*7", "calculate"),
    ("open youtube", "open_website"),
    ("remind me to stretch in 20 minutes", "set_reminder"),
    ("check my email", "check_email"),
    ("show my routines", "list_routines"),
])
def test_full_routing(runtime, text, tool):
    call = runtime.ctx.services["quick_match"](text)
    assert call is not None, text
    assert call.name == tool, (text, call)


def test_routines_end_to_end(runtime):
    routines = runtime.ctx.services["skills"]["routines"]
    r = routines.create_routine("work mode", ["todo check email", "wait 0 seconds", "12*7"])
    assert not r.ok  # "wait 0 seconds" isn't a valid wait
    assert routines.create_routine("work mode", ["todo check email", "12*7"]).ok
    bad = routines.create_routine("bad", ["make me a sandwich"])
    assert not bad.ok and "make me a sandwich" in bad.message
    reply = runtime.agent.handle("work mode")
    assert reply.text == "Ran “work mode” (2 steps). ✓"
    assert runtime.db.one("SELECT text FROM todos")["text"] == "check email"
    assert "work mode" in runtime.agent.handle("show my routines").text
