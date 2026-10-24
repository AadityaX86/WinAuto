"""Gmail: send, check, read and reply (SMTP/IMAP with an app password)."""

from __future__ import annotations

import logging
import re
from email.message import EmailMessage
from email.utils import formataddr, getaddresses, make_msgid
from typing import Any

from winauto.adapters.gmail import (
    SECRET_NAME,
    EmailError,
    GmailBackend,
    body_text,
    short_date,
)
from winauto.adapters.secrets import get_secret
from winauto.core.context import Context
from winauto.core.launcher import starts, template
from winauto.core.skill import QuickRule, Risk, Skill, Suggestion, ToolResult, fail, ok, tool
from winauto.skills.shared.contacts import EMAIL_RE, ContactBook

log = logging.getLogger(__name__)

SETUP_HELP = (
    "Gmail isn't set up yet. Open Settings → Accounts and enter your Gmail address and an app password. "
    "Create the app password at https://myaccount.google.com/apppasswords (it needs 2-Step Verification turned on)."
)


class EmailSkill(Skill):
    name = "email"
    icon = "mail"
    description = "Gmail: send, check, read, reply."
    keywords = r"\b(e-?mails?|mail|gmail|inbox|reply|replied|unread)\b"
    prompt_hint = (
        "Email: send_email takes contact names or addresses. Write the whole email (greeting, short body, "
        "sign-off with the user's name); the user reviews it before it's sent. Use check_email then "
        "read_email to answer questions about emails."
    )

    def __init__(self, ctx: Context, backend: Any = None):
        super().__init__(ctx)
        self._backend = backend
        self.book = ContactBook(ctx)

    def backend(self) -> Any:
        if self._backend is not None:
            return self._backend
        address = self.ctx.config.email.address.strip()
        password = get_secret(SECRET_NAME) or ""
        if not address or not password:
            raise EmailError(SETUP_HELP)
        return GmailBackend(address, password)

    def _sender(self) -> str:
        cfg = self.ctx.config
        name = cfg.email.display_name or cfg.user_name
        return formataddr((name, cfg.email.address)) if name else cfg.email.address

    def resolve_recipients(self, text: str) -> tuple[list[str], list[str]]:
        """'Ram, sita@x.com and mom' -> (['Ram Sharma <ram@...>', ...], [problems])."""
        found, problems = [], []
        for part in re.split(r"\s*(?:,|;|\band\b)\s*", text.strip()):
            part = part.strip()
            if not part:
                continue
            addr = EMAIL_RE.search(part)
            if addr:
                found.append(part if "<" in part else addr.group(0))
                continue
            contact, error = self.book.resolve(part, "email")
            if contact:
                found.append(formataddr((contact["name"], contact["email"])))
            else:
                problems.append(error or f"Who is {part}?")
        return found, problems

    @tool(
        "Send an email from the user's Gmail. The user sees and can edit it before it goes.",
        params={"to": "Contact names or email addresses, comma separated", "subject": "Subject line",
                "body": "The full email text", "cc": "Optional names/addresses to copy in"},
        risk=Risk.CONFIRM, editable=("to", "subject", "body"), confirm_label="Send",
    )
    def send_email(self, to: str, subject: str, body: str, cc: str = "") -> ToolResult:
        recipients, problems = self.resolve_recipients(to)
        cc_list, cc_problems = self.resolve_recipients(cc) if cc else ([], [])
        if problems or cc_problems:
            return fail(" ".join(problems + cc_problems), fallback=True)
        if not recipients:
            return fail("Who should I send it to?")
        try:
            backend = self.backend()
        except EmailError as exc:
            return fail(str(exc))
        msg = EmailMessage()
        msg["From"] = self._sender()
        msg["To"] = ", ".join(recipients)
        if cc_list:
            msg["Cc"] = ", ".join(cc_list)
        msg["Subject"] = subject.strip() or "(no subject)"
        msg["Message-ID"] = make_msgid(domain="winauto.local")
        msg.set_content(self._with_signature(body))
        try:
            backend.send(msg)
        except EmailError as exc:
            return fail(str(exc))
        names = ", ".join(n or a for n, a in getaddresses(recipients))
        return ok(f"Sent “{msg['Subject']}” to {names}.")

    def _with_signature(self, body: str) -> str:
        sig = self.ctx.config.email.signature.strip()
        body = body.strip()
        if sig and sig not in body:
            body += "\n\n" + sig
        return body + "\n"

    def precheck(self, tool_name: str, args: dict[str, Any]) -> ToolResult | None:
        if tool_name not in ("send_email", "reply_email") or self._backend is not None:
            return None
        if self.ctx.config.email.address.strip() and get_secret(SECRET_NAME):
            return None
        # Keep the draft, so setting up Gmail doesn't mean writing it again.
        draft = ""
        if args.get("body"):
            draft = "\n\nHere's the draft so you don't lose it:\n\n"
            if args.get("subject"):
                draft += f"**{args['subject']}**\n\n"
            draft += str(args["body"])
        return fail(SETUP_HELP + draft)

    def preview(self, tool_name: str, args: dict[str, Any]) -> str | None:
        if tool_name == "send_email":
            recipients, problems = self.resolve_recipients(str(args.get("to", "")))
            lines = [f"From: {self._sender() or 'your Gmail'}"]
            lines.append("To: " + (", ".join(recipients) if recipients else "?"))
            if args.get("cc"):
                lines.append("Cc: " + ", ".join(self.resolve_recipients(str(args["cc"]))[0]))
            if problems:
                lines.append("⚠ " + " ".join(problems))
            return "\n".join(lines)
        if tool_name == "reply_email":
            return f"Reply to email #{args.get('email_id')}"
        return None

    @tool(
        "List recent emails in the inbox. Supports Gmail search words, e.g. 'from:ram', 'subject:invoice', 'newer_than:2d'.",
        params={"query": "Gmail search (optional)", "unread_only": "Only unread ones (default true)",
                "limit": "How many (default 5)"},
        final=False, title="Check email: {query}")
    def check_email(self, query: str = "", unread_only: bool = True, limit: int = 5) -> ToolResult:
        try:
            backend = self.backend()
            parts = ["in:inbox"]
            if unread_only:
                parts.append("is:unread")
            if query.strip():
                parts.append(self._expand_names(query.strip()))
            items = backend.search(" ".join(parts), max(1, min(limit, 20)))
        except EmailError as exc:
            return fail(str(exc))
        if not items:
            what = "unread emails" if unread_only else "emails"
            return ok(f"No {what}{' matching ' + query if query.strip() else ''}. 📭", data={"emails": []})
        lines = []
        for it in items:
            sender = getaddresses([it["from"]])[0]
            who = sender[0] or sender[1]
            dot = "● " if it["unread"] else ""
            lines.append(f"- {dot}**{who}**: {it['subject']} ({it['date']}) [#{it['id']}]")
        heading = "Unread emails" if unread_only else "Emails"
        return ok(f"{heading}:\n" + "\n".join(lines), data={"emails": items})

    def _expand_names(self, query: str) -> str:
        """'from:ram' -> 'from:ram@x.com' when Ram is a contact."""
        def sub(m):
            contact, _ = self.book.resolve(m.group(2), "email")
            return f"{m.group(1)}:{contact['email']}" if contact else m.group(0)

        return re.sub(r"\b(from|to|cc):([^\s@]+)\b", sub, query)

    @tool("Read one email in full.", params={"email_id": "The number shown in check_email, e.g. 1234"}, final=False)
    def read_email(self, email_id: str) -> ToolResult:
        try:
            msg = self.backend().fetch(str(email_id).lstrip("#"))
        except EmailError as exc:
            return fail(str(exc))
        text = body_text(msg)
        header = f"From: {msg['From']}\nSubject: {msg['Subject']}\nDate: {short_date(str(msg['Date']))}"
        return ok(f"{header}\n\n{text}", data={"from": str(msg["From"]), "subject": str(msg["Subject"]), "body": text})

    @tool(
        "Reply to an email. The user sees and can edit it before it goes.",
        params={"email_id": "The email's number", "body": "The reply text"},
        risk=Risk.CONFIRM, editable=("body",), confirm_label="Send reply",
    )
    def reply_email(self, email_id: str, body: str) -> ToolResult:
        try:
            backend = self.backend()
            original = backend.fetch(str(email_id).lstrip("#"))
        except EmailError as exc:
            return fail(str(exc))
        reply_to = str(original.get("Reply-To") or original.get("From") or "")
        if not reply_to:
            return fail("That email has no sender to reply to.")
        subject = str(original.get("Subject", ""))
        msg = EmailMessage()
        msg["From"] = self._sender()
        msg["To"] = reply_to
        msg["Subject"] = subject if subject.lower().startswith("re:") else f"Re: {subject}"
        msg["Message-ID"] = make_msgid(domain="winauto.local")
        if original.get("Message-ID"):
            msg["In-Reply-To"] = original["Message-ID"]
            refs = str(original.get("References", "")).strip()
            msg["References"] = (refs + " " + original["Message-ID"]).strip()
        msg.set_content(self._with_signature(body))
        try:
            backend.send(msg)
        except EmailError as exc:
            return fail(str(exc))
        return ok(f"Replied to {getaddresses([reply_to])[0][0] or reply_to}.")

    def suggest(self, query: str) -> list[Suggestion]:
        if not starts(query, "email", "e-mail", "mail", "inbox", "gmail", "write an email", "send an email"):
            return []
        return [
            Suggestion(title="Check my email", subtitle="Unread emails in Gmail", tool="check_email", args={},
                       kind="Command", icon="mail", score=91),
            template("Write an email…", "email ", "Type who and what, e.g. ram that I'm running late", "mail", 85),
        ]

    def quick_rules(self) -> list[QuickRule]:
        return [
            QuickRule(r"(?:check|show|open\s+my\s+inbox|read|any)\s*(?:my\s+)?(?:new\s+|unread\s+)?(?:e-?mails?|mail|inbox|gmail)"
                      r"(?:\s+(?:today|now))?", lambda m: ("check_email", {})),
            QuickRule(r"(?:do i have\s+)?(?:any\s+)?(?:new\s+|unread\s+)?e-?mails?(?:\s+today)?",
                      lambda m: ("check_email", {})),
            QuickRule(r"(?:search|look\s+through|find\s+in)\s+(?:my\s+)?(?:e-?mails?|inbox|gmail)\s+(?:for\s+)?(?P<q>.+)",
                      lambda m: ("check_email", {"query": m["q"], "unread_only": False, "limit": 8})),
            QuickRule(r"(?:any\s+|show\s+|check\s+)?(?:new\s+)?e-?mails?\s+from\s+(?P<who>[\w .@-]+)",
                      lambda m: ("check_email", {"query": f"from:{m['who'].strip().split()[0]}", "unread_only": False})),
        ]
