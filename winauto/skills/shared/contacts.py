"""The contact book: finding people by name for email, WhatsApp and Discord."""

from __future__ import annotations

import re
from typing import Any

from winauto.core.context import Context
from winauto.core.matching import normalize, rank

EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
PHONE_RE = re.compile(r"\+?\d[\d\s().-]{6,}\d")
FIELDS = ("email", "phone", "discord", "nickname")


def normalize_phone(phone: str, default_cc: str = "") -> str:
    """Digits only, with country code, as WhatsApp wants: '+977 980-000 0000' -> '9779800000000'."""
    raw = phone.strip()
    digits = re.sub(r"\D", "", raw)
    if not digits:
        return ""
    if raw.startswith("+"):
        return digits
    if digits.startswith("00"):
        return digits[2:]
    cc = re.sub(r"\D", "", default_cc or "")
    if cc and digits.startswith(cc) and len(digits) > 10:
        return digits
    if digits.startswith("0"):
        digits = digits.lstrip("0")
    return (cc + digits) if cc else digits


class ContactBook:
    """Shared lookups used by the email and messaging skills."""

    def __init__(self, ctx: Context):
        self.ctx = ctx

    @property
    def db(self):
        return self.ctx.db

    def all(self) -> list[dict[str, Any]]:
        return self.db.query("SELECT * FROM contacts ORDER BY name COLLATE NOCASE")

    def get(self, contact_id: int) -> dict[str, Any] | None:
        return self.db.one("SELECT * FROM contacts WHERE id = ?", (contact_id,))

    def find(self, name: str) -> list[dict[str, Any]]:
        """Best matches for a name, nickname, first name, email or number."""
        query = name.strip().lstrip("@")
        if not query:
            return []
        rows = self.all()
        q = normalize(query)
        exact = [r for r in rows if q in (normalize(r["name"]), normalize(r["nickname"]))]
        if exact:
            return exact
        by_value = [r for r in rows if query.lower() in (r["email"].lower(), r["discord"].lower().lstrip("@"))
                    or (re.sub(r"\D", "", query) and re.sub(r"\D", "", query) == re.sub(r"\D", "", r["phone"]))]
        if by_value:
            return by_value
        first = [r for r in rows if normalize(r["name"]).split()[:1] == q.split()[:1] and len(q.split()) == 1]
        if first:
            return first
        names = {}
        for r in rows:
            names[r["name"]] = r
            if r["nickname"]:
                names[r["nickname"]] = r
        found = rank(query, names.keys(), limit=3, cutoff=80)
        seen, out = set(), []
        for n, _ in found:
            if names[n]["id"] not in seen:
                seen.add(names[n]["id"])
                out.append(names[n])
        return out

    def resolve(self, name: str, need: str) -> tuple[dict[str, Any] | None, str | None]:
        """One contact that has `need` (email/phone/discord), or an explanation."""
        matches = self.find(name)
        if not matches:
            return None, f"I don't have a contact called '{name}'."
        with_field = [m for m in matches if m.get(need)]
        if len(with_field) > 1:
            names = ", ".join(m["name"] for m in with_field)
            return None, f"Which {name}? I have {names}."
        if not with_field:
            label = {"phone": "phone number", "email": "email address", "discord": "Discord username"}[need]
            return None, (f"I don't have a {label} for {matches[0]['name']}. "
                          f"Add it with: update contact {matches[0]['name']} {need} ...")
        return with_field[0], None
