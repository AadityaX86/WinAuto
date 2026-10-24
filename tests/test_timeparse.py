from datetime import datetime

import pytest

from winauto.core.timeparse import describe, find_when, parse_duration, parse_when

NOW = datetime(2026, 10, 24, 14, 5)  # a Saturday afternoon


@pytest.mark.parametrize(
    "text, expected, has_time, rest",
    [
        ("call mom tomorrow at 5pm", datetime(2026, 10, 25, 17, 0), True, "call mom"),
        ("in 10 minutes", datetime(2026, 10, 24, 14, 15), True, ""),
        ("dentist friday", datetime(2026, 10, 30, 9, 0), False, "dentist"),
        ("meeting next monday 3:30 pm", datetime(2026, 10, 26, 15, 30), True, "meeting"),
        ("at 6", datetime(2026, 10, 24, 18, 0), True, ""),
        ("remind me at 4 to stretch", datetime(2026, 10, 24, 16, 0), True, "remind me to stretch"),
        ("tomorrow at 7", datetime(2026, 10, 25, 7, 0), True, ""),
        ("pay rent on 1st nov", datetime(2026, 11, 1, 9, 0), False, "pay rent"),
        ("oct 30 noon", datetime(2026, 10, 30, 12, 0), True, ""),
        ("2026-11-02 10:00", datetime(2026, 11, 2, 10, 0), True, ""),
        ("tonight", datetime(2026, 10, 24, 20, 0), True, ""),
        ("submit report by 9am", datetime(2026, 10, 25, 9, 0), True, "submit report"),
        ("in half an hour stretch", datetime(2026, 10, 24, 14, 35), True, "stretch"),
        ("this sunday evening", datetime(2026, 10, 25, 18, 0), True, ""),
        ("next week", datetime(2026, 10, 26, 9, 0), False, ""),
        ("jan 3", datetime(2027, 1, 3, 9, 0), False, ""),
        ("at 14:30", datetime(2026, 10, 24, 14, 30), True, ""),
        ("saturday", datetime(2026, 10, 31, 9, 0), False, ""),
    ],
)
def test_find_when(text, expected, has_time, rest):
    when, remaining = find_when(text, NOW)
    assert when is not None
    assert when.dt == expected
    assert when.has_time == has_time
    assert remaining == rest


@pytest.mark.parametrize("text", ["buy milk", "at 25%", "set volume to 50", "sat on the mat"])
def test_no_time(text):
    assert find_when(text, NOW)[0] is None


def test_parse_when_iso():
    assert parse_when("2026-11-05", NOW).has_time is False
    assert parse_when("2026-11-05T17:30", NOW).dt == datetime(2026, 11, 5, 17, 30)
    assert parse_when("", NOW) is None


def test_durations():
    assert [parse_duration(x) for x in ["10 minutes", "1h30m", "90 sec", "an hour and a half", "5", "2:30", "half an hour"]] == [
        600, 5400, 90, 5400, 300, 150, 1800]
    assert parse_duration("soon") is None


def test_describe():
    assert describe(datetime(2026, 10, 24, 17, 0), True, NOW) == "today 5:00 PM"
    assert describe(datetime(2026, 10, 25, 9, 0), False, NOW) == "tomorrow"
    assert describe(datetime(2026, 10, 28, 9, 0), False, NOW) == "Wednesday"
    assert describe(datetime(2026, 12, 1, 9, 0), False, NOW) == "Tue 1 Dec"
