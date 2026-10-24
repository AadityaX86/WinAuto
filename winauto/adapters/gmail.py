"""Gmail over SMTP (sending) and IMAP (reading), signed in with an app password."""

from __future__ import annotations

import email
import email.policy
import imaplib
import re
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import parsedate_to_datetime
from typing import Any

from winauto.adapters.http import html_to_text

# Name of the app password in Windows Credential Manager.
SECRET_NAME = "gmail-app-password"


class EmailError(Exception):
    pass


class GmailBackend:
    """Talks to Gmail over SMTP (sending) and IMAP (reading)."""

    def __init__(self, address: str, password: str):
        self.address = address
        self.password = password.replace(" ", "")

    def _imap(self) -> imaplib.IMAP4_SSL:
        try:
            conn = imaplib.IMAP4_SSL("imap.gmail.com", 993, ssl_context=ssl.create_default_context(), timeout=20)
            conn.login(self.address, self.password)
        except imaplib.IMAP4.error as exc:
            raise EmailError("Gmail rejected the sign-in. Check the address and app password in Settings.") from exc
        except OSError as exc:
            raise EmailError(f"Couldn't reach Gmail: {exc}") from exc
        return conn

    def check(self) -> str:
        conn = self._imap()
        conn.logout()
        return f"Signed in to Gmail as {self.address}."

    def send(self, msg: EmailMessage) -> None:
        try:
            with smtplib.SMTP_SSL("smtp.gmail.com", 465, context=ssl.create_default_context(), timeout=30) as smtp:
                smtp.login(self.address, self.password)
                smtp.send_message(msg)
        except smtplib.SMTPAuthenticationError as exc:
            raise EmailError("Gmail rejected the sign-in. Check the address and app password in Settings.") from exc
        except (smtplib.SMTPException, OSError) as exc:
            raise EmailError(f"Sending failed: {exc}") from exc

    def search(self, query: str, limit: int) -> list[dict[str, Any]]:
        conn = self._imap()
        try:
            conn.select("INBOX", readonly=True)
            gm_query = '"' + query.replace("\\", "").replace('"', "'") + '"'
            status, data = conn.uid("SEARCH", "X-GM-RAW", gm_query)
            if status != "OK":
                raise EmailError("Gmail search failed.")
            uids = data[0].split()[-limit:][::-1] if data and data[0] else []
            if not uids:
                return []
            status, fetched = conn.uid("FETCH", b",".join(uids), "(UID FLAGS BODY.PEEK[HEADER.FIELDS (FROM SUBJECT DATE)])")
            items: dict[bytes, dict[str, Any]] = {}
            for part in fetched:
                if not isinstance(part, tuple):
                    continue
                meta, raw = part
                uid_match = re.search(rb"UID (\d+)", meta)
                if not uid_match:
                    continue
                headers = email.message_from_bytes(raw, policy=email.policy.default)
                items[uid_match.group(1)] = {
                    "id": uid_match.group(1).decode(),
                    "from": str(headers.get("From", "")),
                    "subject": str(headers.get("Subject", "")) or "(no subject)",
                    "date": short_date(str(headers.get("Date", ""))),
                    "unread": b"\\Seen" not in meta,
                }
            return [items[u] for u in uids if u in items]
        finally:
            logout(conn)

    def fetch(self, uid: str) -> EmailMessage:
        conn = self._imap()
        try:
            conn.select("INBOX", readonly=True)
            status, size_data = conn.uid("FETCH", uid, "(RFC822.SIZE)")
            size = re.search(rb"RFC822.SIZE (\d+)", size_data[0] or b"") if status == "OK" and size_data and size_data[0] else None
            if not size:
                raise EmailError(f"There's no email with id {uid}.")
            spec = "(BODY.PEEK[])" if int(size.group(1)) < 5_000_000 else "(BODY.PEEK[HEADER] BODY.PEEK[1])"
            status, data = conn.uid("FETCH", uid, spec)
            raw = b"".join(part[1] for part in data if isinstance(part, tuple))
            return email.message_from_bytes(raw, policy=email.policy.default)  # type: ignore[return-value]
        finally:
            logout(conn)


def logout(conn: imaplib.IMAP4_SSL) -> None:
    try:
        conn.logout()
    except Exception:
        pass


def short_date(value: str) -> str:
    try:
        return parsedate_to_datetime(value).astimezone().strftime("%d %b %H:%M")
    except (TypeError, ValueError):
        return value


def body_text(msg: EmailMessage, limit: int = 6000) -> str:
    part = msg.get_body(preferencelist=("plain", "html"))
    if part is None:
        return ""
    try:
        content = part.get_content()
    except (LookupError, ValueError):
        content = part.get_payload(decode=True).decode("utf-8", "replace") if part.get_payload(decode=True) else ""
    if part.get_content_type() == "text/html":
        content, _ = html_to_text(content)
    # Drop the quoted history in replies.
    content = re.split(r"\n(?:On .+ wrote:|-----Original Message-----)\s*\n", content, maxsplit=1)[0]
    content = re.sub(r"\n{3,}", "\n\n", content).strip()
    return content[:limit] + ("…" if len(content) > limit else "")
