from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from fakes import RecordingConfirmer, ScriptedLLM

from winauto.adapters.winos.apps import WindowInfo
from winauto.skills.briefing import BriefingSkill
from winauto.skills.calendar import CalendarSkill, parse_ics
from winauto.skills.focus import FocusSkill
from winauto.skills.info import InfoSkill, parse_rss
from winauto.skills.voice import VoiceSkill, speakable

NOW = datetime(2026, 10, 24, 8, 30)  # Saturday morning

ICS = """BEGIN:VCALENDAR
BEGIN:VEVENT
SUMMARY:Standup
DTSTART:20261019T090000
DTEND:20261019T091500
RRULE:FREQ=WEEKLY;BYDAY=MO,WE,FR,SA;COUNT=20
LOCATION:Zoom
END:VEVENT
BEGIN:VEVENT
SUMMARY:Mom's birthday
DTSTART;VALUE=DATE:20261024
DTEND;VALUE=DATE:20261025
END:VEVENT
BEGIN:VEVENT
SUMMARY:Dentist\\, checkup
DTSTART:20261026T140000
DURATION:PT45M
END:VEVENT
BEGIN:VEVENT
SUMMARY:Cancelled thing
DTSTART:20261024T100000
STATUS:CANCELLED
END:VEVENT
BEGIN:VEVENT
SUMMARY:Gym
DTSTART:20261020T180000
DTEND:20261020T190000
RRULE:FREQ=DAILY;INTERVAL=2
EXDATE:20261024T180000
END:VEVENT
END:VCALENDAR
"""


class Clock:
    def __init__(self, now):
        self.now = now

    def __call__(self):
        return self.now


# ---------------- calendar ----------------

def test_parse_ics_expands_repeats():
    day = datetime(2026, 10, 24)
    events = parse_ics(ICS, day, day + timedelta(days=1))
    titles = [(e.title, e.start.strftime("%H:%M"), e.all_day) for e in events]
    assert ("Standup", "09:00", False) in titles
    assert ("Mom's birthday", "00:00", True) in titles
    assert not any(t[0] in ("Cancelled thing", "Gym") for t in titles)  # cancelled, and the 24th is excluded
    monday = datetime(2026, 10, 26)
    mon = parse_ics(ICS, monday, monday + timedelta(days=1))
    assert [e.title for e in mon] == ["Standup", "Dentist, checkup", "Gym"]
    assert mon[1].end - mon[1].start == timedelta(minutes=45)


@pytest.fixture
def calendar(ctx):
    ctx.config.calendar_urls = ["webcal://calendar.example.com/private.ics"]
    fetched = []
    clock = Clock(NOW)

    def fetcher(url, **kw):
        fetched.append(url)
        return ICS, url

    skill = CalendarSkill(ctx, fetcher=fetcher, clock=clock)
    return skill, fetched, clock


def test_agenda_and_next(calendar):
    skill, fetched, _ = calendar
    r = skill.get_agenda("today")
    assert r.ok and "**All day** Mom's birthday" in r.message and "**9:00 AM–9:15 AM** Standup · Zoom" in r.message
    assert fetched == ["https://calendar.example.com/private.ics"]
    skill.get_agenda("today")
    assert len(fetched) == 1  # cached
    assert "Standup" in skill.next_event().message and "in 30 min" in skill.next_event().message


def test_local_events(calendar, ctx):
    from winauto.skills.reminders import RemindersSkill

    skill, _, clock = calendar
    rem = RemindersSkill(ctx, clock=clock, sound=lambda k: None)
    ctx.skills = {"reminders": rem}
    r = skill.add_event("Lunch with Ram", "today 1pm")
    assert r.ok and "remind you 10 minutes before" in r.message
    assert "Lunch with Ram" in skill.get_agenda("today").message
    assert ctx.db.one("SELECT text FROM reminders")["text"] == "Lunch with Ram in 10 minutes"
    assert skill.delete_event("lunch").ok


def test_no_calendar_hint(ctx):
    skill = CalendarSkill(ctx, clock=Clock(NOW))
    assert "iCal link" in skill.get_agenda().message


# ---------------- info ----------------

RATES = {"result": "success", "rates": {"USD": 1, "NPR": 133.5, "EUR": 0.92, "INR": 83.4}}
RSS = """<rss><channel>
<item><title>Big match tonight - Sports Daily</title><link>https://ex.com/1</link><source>Sports Daily</source>
<pubDate>Sat, 24 Oct 2026 05:00:00 GMT</pubDate></item>
<item><title>Rain expected</title><link>https://ex.com/2</link></item>
</channel></rss>"""


@pytest.fixture
def info(ctx):
    calls = []

    def json_fetcher(url, **kw):
        calls.append(url)
        if "er-api" in url:
            return RATES
        if "dictionaryapi" in url:
            return [{"word": "serendipity", "phonetic": "/ˌsɛrənˈdɪpɪti/", "meanings": [
                {"partOfSpeech": "noun", "definitions": [{"definition": "Luck in finding good things.", "example": "pure serendipity"}]}]}]
        if "opensearch" in url:
            return ["kathmandu", ["Kathmandu"], [""], [""]]
        if "summary" in url:
            return {"title": "Kathmandu", "extract": "Kathmandu is the capital of Nepal.",
                    "content_urls": {"desktop": {"page": "https://en.wikipedia.org/wiki/Kathmandu"}}}
        raise AssertionError(url)

    skill = InfoSkill(ctx, json_fetcher=json_fetcher, fetcher=lambda url, **kw: (RSS, url))
    return skill, calls


def test_currency(info, ctx):
    skill, calls = info
    r = skill.convert_currency(100, "dollars", "NPR")
    assert r.ok and "100.00 USD = **13,350.00 NPR**" in r.message
    skill.convert_currency(5, "usd", "inr")
    assert len([c for c in calls if "er-api" in c]) == 1  # rates cached
    ctx.config.messaging.default_country_code = "977"
    assert skill._code("rupees") == "NPR"
    assert not skill.convert_currency(1, "usd", "XYZ").ok


def test_dictionary_wiki_news(info):
    skill, _ = info
    assert "*noun* Luck in finding good things." in skill.define_word("serendipity").message
    assert "capital of Nepal" in skill.wikipedia_summary("kathmandu").message
    news = skill.get_news()
    assert "[Big match tonight](https://ex.com/1) · Sports Daily" in news.message
    assert parse_rss(RSS)[1]["title"] == "Rain expected"


# ---------------- briefing ----------------

def test_briefing(ctx, calendar):
    cal, _, clock = calendar
    from winauto.skills.notes import NotesSkill

    notes = NotesSkill(ctx)
    notes.add_todo("pay electricity bill", due="today")

    class Weather:
        def get_weather(self, loc):
            from winauto.core.skill import ok
            return ok("**Pokhara**: 18°C and sunny.")

    ctx.config.user_name = "Aaditya Joshi"
    ctx.skills = {"calendar": cal, "notes": notes, "web": Weather()}
    b = BriefingSkill(ctx, clock=clock)
    assert b.due_for_morning_briefing()
    r = b.daily_briefing(include_news=False)
    assert r.message.startswith("### Good morning, Aaditya!")
    for part in ("**Weather**", "18°C", "**Calendar**", "Standup", "**Due today**", "pay electricity bill"):
        assert part in r.message
    assert not b.due_for_morning_briefing()  # once a day


# ---------------- focus ----------------

class FakeApps:
    def __init__(self):
        self.open = {"discord": [WindowInfo(5, "Discord", 1, "discord")]}

    def find_windows(self, name):
        return self.open.get(name, [])


def test_focus_rounds(ctx):
    clock = Clock(NOW)
    skill = FocusSkill(ctx, clock=clock, apps=FakeApps())
    r = skill.start_focus(25, rounds=2, break_minutes=5, block_apps=["discord"])
    assert r.ok and "2 × 25 min" in r.message and "ends at 8:55 AM" in r.message
    clock.now = NOW + timedelta(minutes=10)
    assert skill.focus_status().message.startswith("Focus: 15:00 left")
    clock.now = NOW + timedelta(minutes=26)
    skill.tick()
    assert skill.state.phase == "break" and ctx.notifications[-1][0] == "☕ Break time"
    clock.now += timedelta(minutes=6)
    skill.tick()
    assert skill.state.phase == "work" and skill.state.round == 2
    clock.now += timedelta(minutes=26)
    skill.tick()
    assert skill.state is None and ctx.notifications[-1][0] == "🎯 Focus session done"
    assert skill.stop_focus().message == "No focus session is running."


# ---------------- voice ----------------

class FakeSpeaker:
    def __init__(self):
        self.said = []
        self.speaking = False

    def say(self, text):
        self.said.append(text)
        self.speaking = True

    def stop(self):
        was, self.speaking = self.speaking, False
        return was


def test_voice(ctx):
    speaker = FakeSpeaker()
    skill = VoiceSkill(ctx, speaker)
    assert skill.read_aloud("**Hello** [there](https://x.com)!").ok and speaker.said == ["Hello there!"]
    assert skill.stop_speaking().message == "Stopped."
    assert speakable("- one\n- two") == "one two"


# ---------------- routing ----------------

@pytest.fixture
def runtime(ctx):
    from winauto.runtime import Runtime

    return Runtime(RecordingConfirmer(), db=ctx.db, llm=ScriptedLLM())


@pytest.mark.parametrize("text, tool", [
    ("convert 100 usd to npr", "convert_currency"),
    ("50 dollars in rupees", "convert_currency"),
    ("10 km to miles", "convert_units"),
    ("define serendipity", "define_word"),
    ("what does ephemeral mean", "define_word"),
    ("wiki kathmandu", "wikipedia_summary"),
    ("news", "get_news"),
    ("latest news about cricket", "get_news"),
    ("what's on my calendar tomorrow", "get_agenda"),
    ("do i have any meetings today", "get_agenda"),
    ("what's my next meeting", "next_event"),
    ("good morning", "daily_briefing"),
    ("brief me", "daily_briefing"),
    ("focus for 50 minutes", "start_focus"),
    ("start pomodoro", "start_focus"),
    ("stop focus", "stop_focus"),
    ("read this aloud", "read_aloud"),
    ("stop talking", "stop_speaking"),
])
def test_routing(runtime, text, tool):
    call = runtime.match_command(text)
    assert call is not None and call.name == tool, (text, call)
