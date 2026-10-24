"""Discord direct messages, by driving the Discord app like you would.

Discord doesn't allow automating personal accounts through its API
("self-bots" get banned), so this opens the app, uses its Ctrl+K quick
switcher to find the person, types the message, and presses Enter only
after you approve.
"""

from __future__ import annotations

import logging
from typing import Any

from winauto.adapters.winos import NotOnWindows
from winauto.adapters.winos.discord import DiscordApp
from winauto.core.context import Context
from winauto.core.skill import QuickRule, Risk, Skill, ToolResult, fail, ok, tool
from winauto.skills.shared.contacts import ContactBook

log = logging.getLogger(__name__)

class DiscordSkill(Skill):
    name = "discord"
    icon = "message"
    description = "Discord direct messages."
    keywords = r"\b(discord|dm)\b"
    prompt_hint = "Discord: send_discord takes a contact name, a Discord username, or '#channel'. Casual tone."

    def __init__(self, ctx: Context, backend: Any = None):
        super().__init__(ctx)
        self.backend = backend or DiscordApp()
        self.book = ContactBook(ctx)

    def _target(self, to: str) -> tuple[str | None, str, str | None]:
        """(switcher text, display name, error)."""
        to = to.strip()
        if to.startswith("#"):
            return to, to, None
        if to.startswith("@"):
            return to, to, None
        contact, error = self.book.resolve(to, "discord")
        if contact:
            return "@" + contact["discord"], contact["name"], None
        if self.book.find(to):
            return None, to, error
        # Not a contact: treat it as a Discord username.
        return "@" + to.replace(" ", ""), to, None

    @tool(
        "Send a Discord direct message (or a message in a #channel of the open server). The user approves it first.",
        params={"to": "Contact name, Discord username, or #channel", "message": "The message"},
        risk=Risk.CONFIRM, editable=("message",), confirm_label="Send",
    )
    def send_discord(self, to: str, message: str) -> ToolResult:
        target, name, error = self._target(to)
        if error or not target:
            return fail(error or f"Who is {to} on Discord?", fallback=True)
        if not message.strip():
            return fail("What should the message say?")
        auto = self.ctx.config.messaging.discord_auto_send
        try:
            if not self.backend.open_dm(target):
                return fail("I couldn't open Discord. Is it installed and signed in?")
            if not self.backend.type_message(message.strip(), send=auto):
                return fail("Discord lost focus before I could type, so nothing was sent.")
        except NotOnWindows as exc:
            return fail(str(exc))
        except OSError as exc:
            return fail(f"Discord: {exc}")
        if auto:
            return ok(f"Sent to {name} on Discord. (Glance at Discord to make sure it went to the right chat.)")
        return ok(f"Your message to {name} is typed in Discord. Press Enter to send it.")

    def preview(self, tool_name: str, args: dict[str, Any]) -> str | None:
        if tool_name == "send_discord":
            target, name, error = self._target(str(args.get("to", "")))
            return f"Discord to {name}" + (f" ({target})" if target and target != name else "") + (f"\n⚠ {error}" if error else "")
        return None

    @tool("Open a Discord chat with someone without sending anything.", params={"to": "Contact, username or #channel"},
          hides_popup=True)
    def open_discord_chat(self, to: str) -> ToolResult:
        target, name, error = self._target(to)
        if error or not target:
            return fail(error or f"Who is {to} on Discord?", fallback=True)
        try:
            if not self.backend.open_dm(target):
                return fail("I couldn't open Discord.")
        except NotOnWindows as exc:
            return fail(str(exc))
        return ok(f"Opened Discord chat with {name}.")

    def quick_rules(self) -> list[QuickRule]:
        def send(m):
            return "send_discord", {"to": m["to"].strip(), "message": m["msg"].strip()}

        return [
            QuickRule(r"(?:send\s+(?:a\s+)?)?(?:discord|dm)\s+(?:to\s+)?(?P<to>[@#]?[\w .-]+?)\s*:\s*(?P<msg>.+)", send),
            QuickRule(r"(?:discord|dm)\s+(?P<to>[@#]?[\w .-]+?)\s+(?:saying|that says)\s+(?P<msg>.+)", send),
        ]
