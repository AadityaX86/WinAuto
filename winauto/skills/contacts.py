"""Your contacts: names -> email, phone (WhatsApp), Discord username."""

from __future__ import annotations

import csv
import re
from pathlib import Path
from typing import Any, Literal

from winauto.core.matching import normalize, rank
from winauto.core.skill import QuickRule, Risk, Skill, Suggestion, ToolResult, fail, ok, tool
from winauto.storage.db import now_iso

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

    def __init__(self, ctx: Any):
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


def _describe(row: dict[str, Any]) -> str:
    parts = [f"**{row['name']}**" + (f" ({row['nickname']})" if row["nickname"] else "")]
    for label, key in (("email", "email"), ("phone", "phone"), ("Discord", "discord")):
        if row[key]:
            parts.append(f"{label}: {row[key]}")
    return " · ".join(parts)


class ContactsSkill(Skill):
    name = "contacts"
    description = "Contact book."
    keywords = r"\b(contacts?|number|phone|email address|address|discord|whatsapp|add .+ to contacts)\b|'s (email|number|phone)"
    prompt_hint = "Contacts: use find_contact to look up someone's email or number before saying you don't know it."

    def __init__(self, ctx: Any):
        super().__init__(ctx)
        self.book = ContactBook(ctx)

    @tool(
        "Save a contact (or add details to an existing one with the same name).",
        params={"name": "Full name", "email": "Email address", "phone": "Phone number with country code if known",
                "discord": "Discord username", "nickname": "What you call them, e.g. 'mom'"},
    )
    def add_contact(self, name: str, email: str = "", phone: str = "", discord: str = "", nickname: str = "") -> ToolResult:
        name = name.strip()
        if not name:
            return fail("What's their name?")
        if email and not EMAIL_RE.fullmatch(email.strip()):
            return fail(f"'{email}' doesn't look like an email address.")
        values = {"email": email.strip(), "phone": phone.strip(), "discord": discord.strip().lstrip("@"),
                  "nickname": nickname.strip()}
        existing = [r for r in self.book.all() if normalize(r["name"]) == normalize(name)]
        stamp = now_iso()
        if existing:
            row = existing[0]
            changes = {k: v for k, v in values.items() if v}
            if not changes:
                return ok(f"{row['name']} is already saved: {_describe(row)}")
            sets = ", ".join(f"{k} = ?" for k in changes)
            self.db.execute(f"UPDATE contacts SET {sets}, updated_at = ? WHERE id = ?", (*changes.values(), stamp, row["id"]))
            return ok("Updated " + _describe(self.book.get(row["id"])))
        cid = self.db.execute(
            "INSERT INTO contacts(name, nickname, email, phone, discord, created_at, updated_at) VALUES(?,?,?,?,?,?,?)",
            (name, values["nickname"], values["email"], values["phone"], values["discord"], stamp, stamp),
        )
        return ok("Saved " + _describe(self.book.get(cid)), data={"id": cid})

    @property
    def db(self):
        return self.ctx.db

    @tool(
        "Change one detail of a contact.",
        params={"name": "Who", "field": "Which detail", "value": "New value (empty to remove)"},
    )
    def update_contact(self, name: str, field: Literal["email", "phone", "discord", "nickname", "name"], value: str = "") -> ToolResult:
        matches = self.book.find(name)
        if not matches:
            return fail(f"I don't have a contact called '{name}'.", fallback=True)
        if len(matches) > 1:
            return fail(f"Which one? {', '.join(m['name'] for m in matches)}")
        row = matches[0]
        value = value.strip().lstrip("@") if field == "discord" else value.strip()
        if field == "email" and value and not EMAIL_RE.fullmatch(value):
            return fail(f"'{value}' doesn't look like an email address.")
        if field == "name" and not value:
            return fail("A contact needs a name.")
        self.db.execute(f"UPDATE contacts SET {field} = ?, updated_at = ? WHERE id = ?", (value, now_iso(), row["id"]))
        return ok("Updated " + _describe(self.book.get(row["id"])))

    @tool("Look up a contact's details.", params={"name": "Name, nickname, email or number"})
    def find_contact(self, name: str) -> ToolResult:
        matches = self.book.find(name)
        if not matches:
            return fail(f"I don't have a contact called '{name}'.", fallback=True)
        return ok("\n".join(_describe(m) for m in matches),
                  data=[{k: m[k] for k in ("name", "nickname", "email", "phone", "discord")} for m in matches])

    @tool("List all contacts.")
    def list_contacts(self) -> ToolResult:
        rows = self.book.all()
        if not rows:
            return ok("No contacts yet. Try: add contact Ram Sharma ram@example.com +977 9800000000")
        lines = [f"- {_describe(r)}" for r in rows[:60]]
        more = f"\n…and {len(rows) - 60} more" if len(rows) > 60 else ""
        return ok(f"{len(rows)} contacts:\n" + "\n".join(lines) + more)

    @tool("Delete a contact.", params={"name": "Who"}, risk=Risk.CONFIRM, confirm_label="Delete")
    def delete_contact(self, name: str) -> ToolResult:
        matches = self.book.find(name)
        if len(matches) != 1:
            return fail(f"I couldn't pick out one contact called '{name}'.")
        self.db.execute("DELETE FROM contacts WHERE id = ?", (matches[0]["id"],))
        return ok(f"Deleted {matches[0]['name']}.")

    def preview(self, tool_name: str, args: dict[str, Any]) -> str | None:
        if tool_name == "delete_contact":
            matches = self.book.find(str(args.get("name", "")))
            return f"Delete {_describe(matches[0])}?" if len(matches) == 1 else None
        return None

    @tool(
        "Import contacts from a .vcf (vCard) or .csv file, e.g. exported from Google Contacts or Outlook.",
        params={"path": "Full path to the file"},
    )
    def import_contacts(self, path: str) -> ToolResult:
        file = Path(path.strip().strip('"')).expanduser()
        if not file.exists():
            return fail(f"I can't find {file}.")
        try:
            people = parse_vcf(file) if file.suffix.lower() == ".vcf" else parse_csv(file)
        except (OSError, csv.Error, UnicodeDecodeError) as exc:
            return fail(f"Couldn't read {file.name}: {exc}")
        added = updated = 0
        for p in people:
            before = len(self.book.all())
            r = self.add_contact(p["name"], p.get("email", ""), p.get("phone", ""))
            if r.ok:
                if len(self.book.all()) > before:
                    added += 1
                else:
                    updated += 1
        return ok(f"Imported {added} new contact(s) and updated {updated} from {file.name}.")

    def suggest(self, query: str) -> list[Suggestion]:
        q = query.strip()
        if len(q) < 2 or len(q.split()) > 3:
            return []
        out = []
        for row in self.book.find(q)[:2]:
            detail = row["email"] or row["phone"] or row["discord"]
            out.append(Suggestion(title=row["name"], subtitle=detail, tool="find_contact", args={"name": row["name"]},
                                  kind="Contact", icon="user", score=66))
        return out

    def quick_rules(self) -> list[QuickRule]:
        def add(m):
            rest = m["rest"]
            email = EMAIL_RE.search(rest)
            if email:
                rest = rest.replace(email.group(0), " ")
            discord = re.search(r"\bdiscord\s*[:=]?\s*@?(\S+)", rest, re.I)
            if discord:
                rest = rest.replace(discord.group(0), " ")
            phone = PHONE_RE.search(rest)
            if phone:
                rest = rest.replace(phone.group(0), " ")
            name = re.sub(r"\b(email|phone|number|mobile|with|and)\b", " ", rest, flags=re.I)
            name = " ".join(name.replace(",", " ").split())
            if not name or not (email or phone or discord):
                return None
            return "add_contact", {"name": name, "email": email.group(0) if email else "",
                                   "phone": phone.group(0).strip() if phone else "",
                                   "discord": discord.group(1) if discord else ""}

        return [
            QuickRule(r"(?:add|save|new|create)\s+(?:a\s+)?contact\s*[:\-]?\s+(?P<rest>.+)", add),
            QuickRule(r"(?:what(?:'s| is)\s+)?(?P<n>[\w .]+?)'s\s+(?:email|e-mail|number|phone(?: number)?|contact|discord)(?:\s+address)?",
                      lambda m: ("find_contact", {"name": m["n"]})),
            QuickRule(r"(?:show|list|view)\s+(?:all\s+)?(?:my\s+)?contacts", lambda m: ("list_contacts", {})),
        ]


def parse_vcf(path: Path) -> list[dict[str, str]]:
    people, current = [], {}
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        key, _, value = line.partition(":")
        key = key.upper()
        if key == "BEGIN" and value.upper() == "VCARD":
            current = {}
        elif key == "END":
            if current.get("name"):
                people.append(current)
        elif key.startswith("FN"):
            current["name"] = value.strip()
        elif key.startswith("EMAIL") and "email" not in current:
            current["email"] = value.strip()
        elif key.startswith("TEL") and "phone" not in current:
            current["phone"] = value.strip()
    return people


def parse_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", errors="replace", newline="") as fh:
        rows = list(csv.DictReader(fh))
    people = []
    for row in rows:
        lower = {k.lower().strip(): (v or "").strip() for k, v in row.items() if k}
        name = lower.get("name") or " ".join(
            x for x in (lower.get("first name") or lower.get("given name"), lower.get("last name") or lower.get("family name")) if x
        )
        email = next((v for k, v in lower.items() if ("e-mail" in k or "email" in k) and "@" in v), "")
        phone = next((v for k, v in lower.items() if ("phone" in k or "mobile" in k) and re.search(r"\d", v)), "")
        phone = phone.split(":::")[0].strip()  # Google joins several numbers with :::
        if name and (email or phone):
            people.append({"name": name, "email": email, "phone": phone})
    return people
