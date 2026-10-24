from __future__ import annotations

import pytest

from winauto.core.quick import QuickMatcher
from winauto.core.registry import Registry
from winauto.skills.system import SystemSkill


class FakeSystem:
    def __init__(self):
        self.calls = []
        self.volume = 40
        self.brightness = 70
        self.radio_error = None

    def get_volume(self):
        return self.volume, False

    def set_volume(self, v):
        self.volume = v
        self.calls.append(("volume", v))

    def set_mute(self, m):
        self.calls.append(("mute", m))

    def get_brightness(self):
        return self.brightness

    def set_brightness(self, v):
        self.brightness = v
        self.calls.append(("brightness", v))

    def set_dark_mode(self, d):
        self.calls.append(("dark", d))

    def set_radio(self, kind, on):
        if self.radio_error:
            raise RuntimeError(self.radio_error)
        self.calls.append((kind, on))

    def open_uri(self, uri):
        self.calls.append(("uri", uri))

    def lock(self):
        self.calls.append(("lock",))

    def sleep(self):
        self.calls.append(("sleep",))

    def shutdown(self, kind, delay):
        self.calls.append(("shutdown", kind, delay))

    def cancel_shutdown(self):
        return True

    def recycle_bin(self):
        return 12, 3 * 1024**3

    def empty_recycle_bin(self):
        self.calls.append(("empty",))

    def uptime_seconds(self):
        return 3 * 86400 + 4 * 3600


@pytest.fixture
def system(ctx):
    backend = FakeSystem()
    return SystemSkill(ctx, backend), backend


def test_volume(system):
    skill, b = system
    assert skill.set_volume(150).message == "Volume set to 100%."
    b.volume = 40
    assert skill.change_volume(-10).message == "Volume down to 30%."
    assert skill.mute(True).ok and ("mute", True) in b.calls


def test_brightness_and_theme(system):
    skill, b = system
    assert skill.change_brightness(-15).message == "Brightness 55%."
    assert skill.dark_mode(False).message == "Light mode on."


def test_radio_failure_opens_settings(system):
    skill, b = system
    assert skill.wifi(True).message == "Wi-Fi on."
    b.radio_error = "denied"
    r = skill.bluetooth(False)
    assert not r.ok and "opened Bluetooth settings" in r.message
    assert ("uri", "ms-settings:bluetooth") in b.calls


def test_power_and_previews(system):
    skill, b = system
    assert skill.preview("power_off", {"action": "restart", "minutes": 5}) == "Restart the PC in 5 minutes? Save your work first."
    r = skill.power_off("shutdown", 10)
    assert r.ok and "cancel shutdown" in r.message and ("shutdown", "shutdown", 600) in b.calls
    assert "12 item(s) (3.0 GB)" in skill.preview("empty_recycle_bin", {})


def test_status_tools(system):
    skill, _ = system
    assert skill.pc_status().ok and "Up for 3 days 4 h" in skill.pc_status().message
    assert skill.battery_status().ok


def test_not_on_windows(ctx):
    r = SystemSkill(ctx).set_volume(20)
    assert not r.ok and "Windows" in r.message


@pytest.fixture
def quick(system):
    reg = Registry()
    reg.add(system[0])
    return QuickMatcher(reg)


@pytest.mark.parametrize("text, tool, args", [
    ("volume 30", "set_volume", {"level": 30}),
    ("set the volume to 75%", "set_volume", {"level": 75}),
    ("volume up", "change_volume", {"change": 10}),
    ("turn the volume down by 20", "change_volume", {"change": -20}),
    ("louder", "change_volume", {"change": 10}),
    ("mute", "mute", {"mute": True}),
    ("unmute the sound", "mute", {"mute": False}),
    ("brightness 40", "set_brightness", {"level": 40}),
    ("dim the screen", "change_brightness", {"change": -15}),
    ("dark mode on", "dark_mode", {"on": True}),
    ("turn off dark mode", "dark_mode", {"on": False}),
    ("light mode", "dark_mode", {"on": False}),
    ("turn off wifi", "wifi", {"on": False}),
    ("bluetooth on", "bluetooth", {"on": True}),
    ("lock", "lock_pc", {}),
    ("lock my computer", "lock_pc", {}),
    ("shut down", "power_off", {"action": "shutdown", "minutes": 0}),
    ("shutdown the pc in 30 minutes", "power_off", {"action": "shutdown", "minutes": 30}),
    ("restart", "power_off", {"action": "restart", "minutes": 0}),
    ("cancel shutdown", "cancel_shutdown", {}),
    ("how much battery is left", "battery_status", {}),
    ("why is my laptop so slow", "pc_status", {}),
    ("empty the recycle bin", "empty_recycle_bin", {}),
    ("open bluetooth settings", "open_settings", {"page": "bluetooth"}),
    ("display settings", "open_settings", {"page": "display"}),
])
def test_quick_rules(quick, text, tool, args):
    call = quick.match(text)
    assert call is not None, text
    assert (call.name, call.arguments) == (tool, args)
