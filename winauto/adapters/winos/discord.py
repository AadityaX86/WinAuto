"""Driving the Discord desktop app with the keyboard (open, Ctrl+K to a DM, type, Enter)."""

from __future__ import annotations

import time

from winauto.adapters.winos.shell import open_app_uri

DISCORD_EXES = {"discord", "discordptb", "discordcanary"}


class DiscordApp:
    def open(self) -> int | None:
        from winauto.adapters.winos.keyboard import wait_for_window

        hwnd = wait_for_window(DISCORD_EXES, timeout=0.5)
        if hwnd:
            return hwnd
        if not open_app_uri("discord://-/channels/@me"):
            return None
        return wait_for_window(DISCORD_EXES, timeout=25)

    def open_dm(self, target: str) -> bool:
        """Focus Discord and switch to the DM/channel. `target` is '@user' or '#channel'."""
        from winauto.adapters.winos.keyboard import bring_to_front, press, type_text

        hwnd = self.open()
        if not hwnd or not bring_to_front(hwnd, DISCORD_EXES):
            return False
        time.sleep(0.6)
        press("ctrl+k")
        time.sleep(0.6)
        type_text(target)
        time.sleep(1.2)  # let the switcher find them
        press("enter")
        time.sleep(1.5)  # chat loads and the message box gets focus
        return True

    def type_message(self, text: str, send: bool) -> bool:
        from winauto.adapters.winos.keyboard import foreground_exe, press, type_text

        if foreground_exe() not in DISCORD_EXES:
            return False
        type_text(text)
        if send:
            time.sleep(0.3)
            press("enter")
        return True
