"""Send WhatsApp messages through WhatsApp Desktop (or WhatsApp Web)."""

from __future__ import annotations

import logging
import re
from typing import Any

from winauto.adapters.winos import NotOnWindows
from winauto.adapters.winos.whatsapp import WhatsAppDesktop
from winauto.core.context import Context
from winauto.core.launcher import starts, template
from winauto.core.skill import QuickRule, Risk, Skill, Suggestion, ToolResult, fail, ok, tool
from winauto.skills.shared.contacts import ContactBook, normalize_phone

log = logging.getLogger(__name__)

class WhatsAppSkill(Skill):
    name = "whatsapp"
    icon = "message"
    description = "WhatsApp messages."
    keywords = r"\b(whats ?app|wa|messages?|msg|chat|dm)\b|\b(?:tell|text|ping|send)\s+(?!me\b|us\b|it\b)\w+"
    prompt_hint = (
        "WhatsApp: send_whatsapp takes a contact name or phone number. Write the message as the user would "
        "send it (casual, short, no sign-off). The user approves it first."
    )

    def __init__(self, ctx: Context, backend: Any = None):
        super().__init__(ctx)
        self.backend = backend or WhatsAppDesktop()
        self.book = ContactBook(ctx)

    def _target(self, to: str) -> tuple[str | None, str, str | None]:
        """(phone digits, display name, error)."""
        cc = self.ctx.config.messaging.default_country_code
        if re.fullmatch(r"\+?[\d\s().-]{7,}", to.strip()):
            return normalize_phone(to, cc), to.strip(), None
        contact, error = self.book.resolve(to, "phone")
        if not contact:
            return None, to, error
        phone = normalize_phone(contact["phone"], cc)
        if len(phone) < 10 and not cc:
            return None, contact["name"], (
                f"{contact['name']}'s number ({contact['phone']}) has no country code. "
                "Add it to the contact, or set your country code in Settings → Accounts → Messaging."
            )
        return phone, contact["name"], None

    @tool(
        "Send a WhatsApp message. The user sees and can edit it first.",
        params={"to": "Contact name or phone number", "message": "The message text"},
        risk=Risk.CONFIRM, editable=("message",), confirm_label="Send", title="WhatsApp {to}: {message}")
    def send_whatsapp(self, to: str, message: str) -> ToolResult:
        phone, name, error = self._target(to)
        if error or not phone:
            return fail(error or f"I need a phone number for {to}.", fallback=True)
        if not message.strip():
            return fail("What should the message say?")
        try:
            where = self.backend.open_chat(phone, message.strip())
            if where == "web":
                return ok(f"WhatsApp Desktop isn't installed, so I opened WhatsApp Web with your message to {name}. "
                          "Press Enter there to send it.")
            if not self.ctx.config.messaging.whatsapp_auto_send:
                return ok(f"Your message to {name} is ready in WhatsApp. Press Enter to send it.")
            if self.backend.press_send():
                return ok(f"Sent to {name} on WhatsApp.")
            return ok(f"Your message to {name} is typed in WhatsApp, but I couldn't press Send. Press Enter there.")
        except NotOnWindows as exc:
            return fail(str(exc))
        except OSError as exc:
            return fail(f"Couldn't open WhatsApp: {exc}")

    def precheck(self, tool_name: str, args: dict[str, Any]) -> ToolResult | None:
        if tool_name != "send_whatsapp":
            return None
        to = str(args.get("to", ""))
        phone, _, error = self._target(to)
        if phone and not error:
            return None
        return fail((error or f"I need a phone number for {to}.") +
                    f" Type their number instead, with the country code (whatsapp +<number>: hi), "
                    f"or save it once: add contact {to} +<number>", fallback=True)

    def preview(self, tool_name: str, args: dict[str, Any]) -> str | None:
        if tool_name == "send_whatsapp":
            phone, name, error = self._target(str(args.get("to", "")))
            if error:
                return f"WhatsApp to {name}\n⚠ {error}"
            return f"WhatsApp to {name} (+{phone})"
        return None

    @tool("Open a WhatsApp chat with someone without sending anything.", params={"to": "Contact name or phone number"},
          hides_popup=True, title="Open WhatsApp chat with {to}")
    def open_whatsapp_chat(self, to: str) -> ToolResult:
        phone, name, error = self._target(to)
        if error or not phone:
            return fail(error or f"I need a phone number for {to}.", fallback=True)
        try:
            self.backend.open_chat(phone, "")
        except (OSError, NotOnWindows) as exc:
            return fail(f"Couldn't open WhatsApp: {exc}")
        return ok(f"Opened your WhatsApp chat with {name}.")

    def suggest(self, query: str) -> list[Suggestion]:
        if not starts(query, "whatsapp", "whats app", "message", "send a message", "text"):
            return []
        return [template("Message on WhatsApp…", "whatsapp ", "Type name: message, e.g. ram: on my way", "message", 86)]

    def quick_rules(self) -> list[QuickRule]:
        def send(m):
            return "send_whatsapp", {"to": m["to"].strip(), "message": m["msg"].strip()}

        return [
            # Only exact wording goes the quick way: "whatsapp ram: on my way".
            QuickRule(r"(?:send\s+(?:a\s+)?)?(?:whats ?app|wa)\s+(?:to\s+)?(?P<to>[\w .+()-]+?)\s*:\s*(?P<msg>.+)", send),
            QuickRule(r"(?:send\s+(?:a\s+)?)?(?:whats ?app|wa)\s+(?:to\s+)?(?P<to>[\w .+()-]+?)\s+(?:saying|that says)\s+(?P<msg>.+)", send),
            QuickRule(r"open\s+(?:my\s+)?(?:whats ?app\s+)?chat\s+with\s+(?P<to>.+?)(?:\s+on\s+whats ?app)?",
                      lambda m: ("open_whatsapp_chat", {"to": m["to"].strip()})),
        ]
