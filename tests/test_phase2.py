from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from winauto.adapters.gmail import GmailBackend, body_text
from winauto.core.quick import QuickMatcher
from winauto.core.registry import Registry
from winauto.skills.contacts import ContactsSkill, normalize_phone, parse_csv, parse_vcf
from winauto.skills.gmail import EmailSkill
from winauto.skills.reminders import RemindersSkill, next_occurrence
from winauto.skills.whatsapp import WhatsAppSkill

NOW = datetime(2026, 10, 24, 14, 5)  # Saturday


# ---------------- contacts ----------------

@pytest.fixture
def contacts(ctx):
    c = ContactsSkill(ctx)
    c.add_contact("Ram Sharma", email="ram@example.com", phone="9800000001")
    c.add_contact("Ram Thapa", phone="+977 980-000-0002")
    c.add_contact("Sita Karki", email="sita@example.com", nickname="didi", discord="sita_k")
    return c


def test_phone_normalization():
    assert normalize_phone("+977 980-000 0000") == "9779800000000"
    assert normalize_phone("9800000000", "977") == "9779800000000"
    assert normalize_phone("09800000000", "+977") == "9779800000000"
    assert normalize_phone("0044 7700 900123") == "447700900123"
    assert normalize_phone("9779800000000", "977") == "9779800000000"


def test_contact_lookup(contacts):
    book = contacts.book
    assert [r["name"] for r in book.find("ram")] == ["Ram Sharma", "Ram Thapa"]
    assert book.find("didi")[0]["name"] == "Sita Karki"
    assert book.find("sita@example.com")[0]["name"] == "Sita Karki"
    assert book.find("ram sharma")[0]["email"] == "ram@example.com"
    # Only one Ram has an email, so "ram" is unambiguous for email...
    c, err = book.resolve("ram", "email")
    assert c["name"] == "Ram Sharma" and err is None
    # ...but not for phone.
    c, err = book.resolve("ram", "phone")
    assert c is None and "Which ram?" in err
    c, err = book.resolve("sita", "phone")
    assert c is None and "update contact Sita Karki phone" in err


def test_contact_add_update_delete(contacts):
    r = contacts.add_contact("ram sharma", discord="ramji")
    assert r.ok and "Discord: ramji" in r.message
    assert not contacts.add_contact("Bob", email="nope").ok
    assert contacts.update_contact("didi", "phone", "9811111111").ok
    assert "9811111111" in contacts.find_contact("sita").message
    assert contacts.preview("delete_contact", {"name": "didi"}).startswith("Delete **Sita Karki**")
    assert contacts.delete_contact("didi").ok
    assert not contacts.find_contact("didi").ok


def test_contact_import(contacts, tmp_path):
    vcf = tmp_path / "c.vcf"
    vcf.write_text("BEGIN:VCARD\nFN:Hari Bahadur\nTEL;TYPE=CELL:+9779800000009\nEND:VCARD\n"
                   "BEGIN:VCARD\nFN:Gita\nEMAIL:gita@example.com\nEND:VCARD\n")
    assert len(parse_vcf(vcf)) == 2
    csv_file = tmp_path / "google.csv"
    csv_file.write_text("First Name,Last Name,E-mail 1 - Value,Phone 1 - Value\nMaya,Rai,maya@example.com,+977 98 ::: 01-555\n")
    assert parse_csv(csv_file) == [{"name": "Maya Rai", "email": "maya@example.com", "phone": "+977 98"}]
    r = contacts.import_contacts(str(vcf))
    assert r.message.startswith("Imported 2 new contact(s)")


@pytest.mark.parametrize("text, args", [
    ("add contact Hari Bahadur hari@example.com +977 9800000009",
     {"name": "Hari Bahadur", "email": "hari@example.com", "phone": "+977 9800000009", "discord": ""}),
    ("save contact mom phone 9800000010", {"name": "mom", "email": "", "phone": "9800000010", "discord": ""}),
    ("new contact Alex discord alex_99", {"name": "Alex", "email": "", "phone": "", "discord": "alex_99"}),
])
def test_contact_quick_add(contacts, text, args):
    reg = Registry()
    reg.add(contacts)
    call = QuickMatcher(reg).match(text)
    assert call.name == "add_contact" and call.arguments == args


# ---------------- reminders ----------------

class Clock:
    def __init__(self, now):
        self.now = now

    def __call__(self):
        return self.now


@pytest.fixture
def reminders(ctx):
    clock = Clock(NOW)
    sounds = []
    skill = RemindersSkill(ctx, clock=clock, sound=sounds.append)
    skill.clock_obj = clock
    skill.sounds = sounds
    return skill


def test_next_occurrence():
    due = datetime(2026, 10, 23, 9, 0)  # Friday
    assert next_occurrence(due, "daily", NOW) == datetime(2026, 10, 25, 9, 0)
    assert next_occurrence(due, "weekdays", NOW) == datetime(2026, 10, 26, 9, 0)
    assert next_occurrence(datetime(2026, 1, 31, 9), "monthly", NOW) == datetime(2026, 10, 31, 9)
    assert next_occurrence(due, "none", NOW) is None


def test_reminder_fires_once(reminders, ctx):
    r = reminders.set_reminder("to call mom", "in 10 minutes")
    assert r.ok and "remind you to call mom today 2:15 PM" in r.message
    assert reminders.check_due() == []
    reminders.clock_obj.now = NOW + timedelta(minutes=11)
    fired = reminders.check_due()
    assert len(fired) == 1 and ctx.notifications == [("Reminder", "call mom")]
    assert reminders.sounds == ["reminder"]
    assert reminders.check_due() == []
    assert reminders.list_reminders().message == "No reminders or timers set."


def test_repeating_and_missed(reminders, ctx):
    reminders.set_reminder("take vitamins", "tomorrow 8am", repeat="daily")
    reminders.clock_obj.now = NOW + timedelta(days=3)  # PC was off
    reminders.check_due(missed_label=True)
    assert ctx.notifications[0][0] == "Missed reminder"
    row = reminders.db.one("SELECT * FROM reminders")
    assert row["active"] == 1 and row["due_at"] == "2026-10-28 08:00:00"


def test_reminder_errors(reminders):
    assert not reminders.set_reminder("x", "someday").ok
    assert "already passed" in reminders.set_reminder("x", "2020-01-01 10:00").message


def test_timer(reminders, ctx):
    r = reminders.set_timer("1h30m", "pasta")
    assert r.ok and "1 hour 30 minutes" in r.message and "Ends at 3:35 PM" in r.message
    assert "1 hour 30 minutes left" in reminders.list_reminders().message
    reminders.clock_obj.now = NOW + timedelta(minutes=91)
    reminders.check_due()
    assert ctx.notifications == [("⏰ Time's up", "Pasta timer (1 hour 30 minutes) is done.")]


def test_cancel(reminders):
    reminders.set_reminder("pay rent", "friday 10am")
    reminders.set_timer("5 min")
    assert reminders.cancel_reminder("timer").ok
    assert reminders.cancel_reminder("rent").ok
    assert not reminders.cancel_reminder("rent").ok


@pytest.mark.parametrize("text, tool, check", [
    ("remind me to call mom at 6pm", "set_reminder", {"text": "call mom", "when": "2026-10-24 18:00", "repeat": "none"}),
    ("remind me in 20 minutes to stretch", "set_reminder", {"text": "stretch", "when": "2026-10-24 14:25", "repeat": "none"}),
    ("remind me to drink water every day at 10am", "set_reminder", {"text": "drink water", "when": "2026-10-25 10:00", "repeat": "daily"}),
    ("set a timer for 10 minutes", "set_timer", {"duration": "10 minutes", "label": ""}),
    ("pasta timer 8 min", "set_timer", {"duration": "8 min", "label": "pasta"}),
    ("5 min timer", "set_timer", {"duration": "5 min", "label": ""}),
    ("show my reminders", "list_reminders", {}),
    ("cancel the timer", "cancel_reminder", {"which": "timer"}),
    ("cancel reminder about rent", "cancel_reminder", {"which": "rent"}),
])
def test_reminder_quick(reminders, text, tool, check):
    reg = Registry()
    reg.add(reminders)
    call = QuickMatcher(reg).match(text)
    assert call is not None, text
    assert (call.name, call.arguments) == (tool, check)


def test_remind_without_time_goes_to_model(reminders):
    reg = Registry()
    reg.add(reminders)
    assert QuickMatcher(reg).match("remind me to call mom") is None


# ---------------- gmail ----------------

RAW_EMAIL = (b"From: Ram Sharma <ram@example.com>\r\nTo: me@gmail.com\r\nSubject: Lunch?\r\n"
             b"Message-ID: <abc@example.com>\r\nDate: Sat, 24 Oct 2026 10:00:00 +0000\r\n"
             b"Content-Type: text/plain; charset=utf-8\r\n\r\nWant to grab lunch at 1?\r\n\r\n"
             b"On Fri, Oct 23 someone wrote:\r\n> old stuff\r\n")


class FakeIMAP:
    def __init__(self):
        self.queries = []

    def select(self, box, readonly=False):
        return "OK", [b"2"]

    def uid(self, command, *args):
        if command == "SEARCH":
            self.queries.append(args[1])
            return "OK", [b"101 102"]
        spec = args[1]
        if spec == "(RFC822.SIZE)":
            return "OK", [b"1 (UID 102 RFC822.SIZE 400)"]
        if spec == "(BODY.PEEK[])":
            return "OK", [(b"1 (UID 102 BODY[] {400}", RAW_EMAIL), b")"]
        return "OK", [
            (b"1 (UID 102 FLAGS () BODY[HEADER.FIELDS (FROM SUBJECT DATE)] {90}",
             b"From: Ram Sharma <ram@example.com>\r\nSubject: Lunch?\r\nDate: Sat, 24 Oct 2026 10:00:00 +0000\r\n\r\n"),
            b")",
            (b"2 (UID 101 FLAGS (\\Seen) BODY[HEADER.FIELDS (FROM SUBJECT DATE)] {60}",
             b"From: news@shop.com\r\nSubject: =?utf-8?q?Sale_=F0=9F=8E=89?=\r\n\r\n"),
            b")",
        ]

    def logout(self):
        pass


def test_gmail_backend_parsing(monkeypatch):
    fake = FakeIMAP()
    backend = GmailBackend("me@gmail.com", "abcd efgh ijkl mnop")
    assert backend.password == "abcdefghijklmnop"
    monkeypatch.setattr(backend, "_imap", lambda: fake)
    items = backend.search("in:inbox", 5)
    assert [i["id"] for i in items] == ["102", "101"]
    assert items[0]["unread"] and not items[1]["unread"]
    assert items[1]["subject"] == "Sale 🎉"
    msg = backend.fetch("102")
    assert body_text(msg) == "Want to grab lunch at 1?"


class FakeMail:
    def __init__(self):
        self.sent = []
        self.inner = GmailBackend("me@gmail.com", "x")
        self.fake_imap = FakeIMAP()
        self.inner._imap = lambda: self.fake_imap

    def send(self, msg):
        self.sent.append(msg)

    def search(self, q, limit):
        return self.inner.search(q, limit)

    def fetch(self, uid):
        return self.inner.fetch(uid)


@pytest.fixture
def mail(ctx, contacts):
    ctx.config.email.address = "me@gmail.com"
    ctx.config.user_name = "Aaditya"
    ctx.config.email.signature = "— Sent with WinAuto"
    backend = FakeMail()
    return EmailSkill(ctx, backend), backend


def test_send_email(mail):
    skill, backend = mail
    r = skill.send_email("ram, boss@work.com", "Meeting moved", "Hi,\nThe meeting is at 3pm now.\nAaditya")
    assert r.ok and r.message == "Sent “Meeting moved” to Ram Sharma, boss@work.com."
    msg = backend.sent[0]
    assert msg["To"] == "Ram Sharma <ram@example.com>, boss@work.com"
    assert msg["From"] == "Aaditya <me@gmail.com>"
    assert msg.get_content().endswith("— Sent with WinAuto\n")
    preview = skill.preview("send_email", {"to": "ram"})
    assert preview == "From: Aaditya <me@gmail.com>\nTo: Ram Sharma <ram@example.com>"


def test_send_email_unknown_recipient(mail):
    skill, backend = mail
    r = skill.send_email("zorro", "x", "y")
    assert not r.ok and "zorro" in r.message and backend.sent == []
    assert "⚠" in skill.preview("send_email", {"to": "zorro"})


def test_check_read_reply(mail):
    skill, backend = mail
    r = skill.check_email(query="from:ram")
    assert "● **Ram Sharma**: Lunch?" in r.message and "[#102]" in r.message
    assert backend.fake_imap.queries[-1] == '"in:inbox is:unread from:ram@example.com"'
    assert "Want to grab lunch at 1?" in skill.read_email("#102").message
    r = skill.reply_email("102", "Sure, see you at 1!")
    reply = backend.sent[-1]
    assert r.ok and reply["Subject"] == "Re: Lunch?" and reply["In-Reply-To"] == "<abc@example.com>"
    assert reply["To"] == "Ram Sharma <ram@example.com>"


def test_gmail_not_set_up(ctx):
    r = EmailSkill(ctx).check_email()
    assert not r.ok and "apppasswords" in r.message


def _agent(skill):
    from fakes import RecordingConfirmer

    from winauto.core.agent import Agent

    reg = Registry()
    reg.add(skill)
    confirmer = RecordingConfirmer()
    return Agent(reg, None, confirmer), confirmer


def test_no_approval_card_that_cant_work(ctx, contacts):
    """Gmail not set up / unknown WhatsApp contact: say so before the card, and keep the draft."""
    from winauto.core.llm import ToolCall

    agent, confirmer = _agent(EmailSkill(ctx))
    r = agent.run_tool(ToolCall("send_email", {"to": "ram", "subject": "Meeting", "body": "Moved to 3pm."}))
    assert not r.ok and "Settings → Accounts" in r.message and "Moved to 3pm." in r.message
    assert confirmer.requests == []
    ctx.config.messaging.default_country_code = "977"
    agent, confirmer = _agent(WhatsAppSkill(ctx, FakeWhatsApp()))
    r = agent.run_tool(ToolCall("send_whatsapp", {"to": "zorro", "message": "hi"}))
    assert not r.ok and "add contact zorro" in r.message and confirmer.requests == []
    # A known contact still gets the card.
    agent.run_tool(ToolCall("send_whatsapp", {"to": "ram sharma", "message": "hi"}))
    assert len(confirmer.requests) == 1


@pytest.mark.parametrize("text, args", [
    ("check my email", {}),
    ("any new emails", {}),
    ("emails from ram", {"query": "from:ram", "unread_only": False}),
])
def test_gmail_quick(mail, text, args):
    reg = Registry()
    reg.add(mail[0])
    call = QuickMatcher(reg).match(text)
    assert call.name == "check_email" and call.arguments == args


# ---------------- whatsapp ----------------

class FakeWhatsApp:
    def __init__(self, where="desktop", pressed=True):
        self.opened = []
        self.where = where
        self.pressed = pressed

    def open_chat(self, phone, text):
        self.opened.append((phone, text))
        return self.where

    def press_send(self):
        return self.pressed


@pytest.fixture
def whatsapp(ctx, contacts):
    ctx.config.messaging.default_country_code = "977"
    backend = FakeWhatsApp()
    return WhatsAppSkill(ctx, backend), backend


def test_whatsapp_send(whatsapp, ctx):
    skill, backend = whatsapp
    r = skill.send_whatsapp("ram sharma", "On my way!")
    assert r.ok and r.message == "Sent to Ram Sharma on WhatsApp."
    assert backend.opened == [("9779800000001", "On my way!")]
    assert skill.preview("send_whatsapp", {"to": "ram sharma"}) == "WhatsApp to Ram Sharma (+9779800000001)"
    assert skill.send_whatsapp("+1 555 123 4567", "hi").ok and backend.opened[-1][0] == "15551234567"
    ctx.config.messaging.whatsapp_auto_send = False
    assert "Press Enter" in skill.send_whatsapp("ram sharma", "hi").message


def test_whatsapp_problems(whatsapp):
    skill, backend = whatsapp
    assert "Which ram?" in skill.send_whatsapp("ram", "hi").message
    assert "phone number" in skill.send_whatsapp("sita", "hi").message
    backend.where = "web"
    assert "WhatsApp Web" in skill.send_whatsapp("ram thapa", "hi").message
    backend.where, backend.pressed = "desktop", False
    assert "couldn't press Send" in skill.send_whatsapp("ram thapa", "hi").message


@pytest.mark.parametrize("text, tool, args", [
    ("whatsapp ram sharma: on my way", "send_whatsapp", {"to": "ram sharma", "message": "on my way"}),
    ("send a whatsapp to didi saying happy birthday!", "send_whatsapp", {"to": "didi", "message": "happy birthday!"}),
    ("open chat with ram thapa", "open_whatsapp_chat", {"to": "ram thapa"}),
])
def test_whatsapp_quick(whatsapp, text, tool, args):
    reg = Registry()
    reg.add(whatsapp[0])
    call = QuickMatcher(reg).match(text)
    assert call is not None and (call.name, call.arguments) == (tool, args)
