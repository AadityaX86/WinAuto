"""Opening a WhatsApp chat with the message typed in, then pressing Enter in WhatsApp Desktop."""

from __future__ import annotations

import time
import urllib.parse

from winauto.adapters.winos.shell import open_app_uri, open_url

WHATSAPP_EXES = {"whatsapp", "whatsapp.root"}


class WhatsAppDesktop:
    def open_chat(self, phone: str, text: str) -> str:
        """Opens the chat with `text` typed in. Returns 'desktop' or 'web'."""
        query = f"phone={phone}" + (f"&text={urllib.parse.quote(text)}" if text else "")
        if open_app_uri("whatsapp://send?" + query):
            return "desktop"
        open_url("https://web.whatsapp.com/send?" + query)
        return "web"

    def press_send(self, timeout: float = 15.0) -> bool:
        from winauto.adapters.winos.keyboard import (
            bring_to_front,
            press,
            wait_for_window,
        )

        hwnd = wait_for_window(WHATSAPP_EXES, timeout)
        if not hwnd:
            return False
        time.sleep(2.0)  # let the chat load and the text land in the box
        if not bring_to_front(hwnd, WHATSAPP_EXES):
            return False
        press("enter")
        return True
