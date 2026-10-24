"""Quick links (saved web addresses, with optional {query}) and snippets (saved text you paste anywhere)."""

from __future__ import annotations

import re
import time
import urllib.parse
from datetime import datetime
from typing import Any, Callable

from winauto.core.matching import normalize, rank
from winauto.core.skill import QuickRule, Risk, Skill, Suggestion, ToolResult, fail, ok, tool
from winauto.adapters.storage.db import now_iso
from winauto.adapters.winos import NotOnWindows
from winauto.adapters.winos.shell import open_url


def fill_placeholders(text: str, clipboard: Callable[[], str | None] | None = None) -> str:
    now = datetime.now()
    values = {
        "date": now.strftime("%d %B %Y"), "time": now.strftime("%I:%M %p").lstrip("0"),
        "day": now.strftime("%A"), "year": str(now.year),
    }
    out = re.sub(r"\{(date|time|day|year)\}", lambda m: values[m.group(1)], text)
    if "{clipboard}" in out and clipboard:
        out = out.replace("{clipboard}", clipboard() or "")
    return out


class ShortcutsSkill(Skill):
    name = "shortcuts"
    description = "Quick links and text snippets."
    keywords = r"\b(quick ?links?|bookmarks?|snippets?|paste my|shortcut)\b"
    prompt_hint = (
        "Shortcuts: quick links are saved URLs (use {query} where search words go); snippets are saved text "
        "the user pastes with paste_snippet. Snippets may use {date}, {time}, {clipboard}."
    )

    def __init__(self, ctx: Any, opener: Callable[[str], Any] | None = None, clipboard: Any = None,
                 paste: Callable[[], None] | None = None):
        super().__init__(ctx)
        self._open = opener or open_url
        self._clipboard = clipboard
        self._paste = paste

    @property
    def db(self):
        return self.ctx.db

    def clipboard(self):
        if self._clipboard is None:
            from winauto.adapters.winos.clipboard import WindowsClipboard

            self._clipboard = WindowsClipboard()
        return self._clipboard

    def _find(self, table: str, name: str) -> dict[str, Any] | None:
        rows = self.db.query(f"SELECT * FROM {table}")
        exact = [r for r in rows if normalize(r["name"]) == normalize(name)]
        if exact:
            return exact[0]
        best = rank(name, [r["name"] for r in rows], limit=1, cutoff=85)
        return next((r for r in rows if best and r["name"] == best[0][0]), None)

    # ----- quick links -----

    @tool("Save a quick link. Put {query} in the address where search words should go.",
          params={"name": "Short name, e.g. 'gh' or 'jira'", "url": "e.g. https://github.com/search?q={query}"})
    def add_quicklink(self, name: str, url: str) -> ToolResult:
        name, url = name.strip(), url.strip()
        if not name or not url:
            return fail("A quick link needs a name and an address.")
        if not re.match(r"^[a-z][a-z0-9+.-]*:", url, re.I):
            url = "https://" + url
        self.db.execute("INSERT INTO quicklinks(name, url, created_at) VALUES(?, ?, ?) "
                        "ON CONFLICT(name) DO UPDATE SET url = excluded.url", (name, url, now_iso()))
        how = f"“{name} <words>”" if "{query}" in url else f"“{name}”"
        return ok(f"Saved quick link {name} → {url}. Say {how} to use it.")

    @tool("Open a saved quick link.", params={"name": "The quick link's name", "query": "Words for {query}, if it takes any"},
          hides_popup=True)
    def open_quicklink(self, name: str, query: str = "") -> ToolResult:
        link = self._find("quicklinks", name)
        if not link:
            return fail(f"There's no quick link called “{name}”.", fallback=True)
        url = link["url"]
        if "{query}" in url:
            url = url.replace("{query}", urllib.parse.quote_plus(query.strip()))
        self._open(url)
        return ok(f"Opened {link['name']}" + (f" for “{query}”." if query.strip() else "."))

    @tool("List saved quick links.")
    def list_quicklinks(self) -> ToolResult:
        rows = self.db.query("SELECT * FROM quicklinks ORDER BY name")
        if not rows:
            return ok("No quick links yet. Try: add quicklink gh https://github.com/search?q={query}")
        return ok("Quick links:\n" + "\n".join(f"- **{r['name']}** → {r['url']}" for r in rows))

    @tool("Delete a quick link.", params={"name": "Its name"}, risk=Risk.CONFIRM, confirm_label="Delete")
    def delete_quicklink(self, name: str) -> ToolResult:
        link = self._find("quicklinks", name)
        if not link:
            return fail(f"There's no quick link called “{name}”.")
        self.db.execute("DELETE FROM quicklinks WHERE name = ?", (link["name"],))
        return ok(f"Deleted quick link {link['name']}.")

    # ----- snippets -----

    @tool("Save a text snippet to paste later (addresses, replies you type often...).",
          params={"name": "Short name, e.g. 'address'", "text": "The text. May use {date}, {time}, {clipboard}."})
    def add_snippet(self, name: str, text: str) -> ToolResult:
        if not name.strip() or not text.strip():
            return fail("A snippet needs a name and some text.")
        self.db.execute("INSERT INTO snippets(name, text, created_at) VALUES(?, ?, ?) "
                        "ON CONFLICT(name) DO UPDATE SET text = excluded.text", (name.strip(), text, now_iso()))
        return ok(f"Saved snippet “{name.strip()}”. Say “paste {name.strip()}” to use it.")

    @tool("Paste a saved snippet into the app you were using (also leaves it on the clipboard).",
          params={"name": "The snippet's name"}, hides_popup=True)
    def paste_snippet(self, name: str) -> ToolResult:
        snip = self._find("snippets", name)
        if not snip:
            return fail(f"There's no snippet called “{name}”.", fallback=True)
        try:
            text = fill_placeholders(snip["text"], self.clipboard().get_text)
            self.clipboard().set_text(text)
            pasted = self._paste_into_previous_window()
        except (NotOnWindows, OSError) as exc:
            return fail(str(exc))
        if pasted:
            return ok(f"Pasted “{snip['name']}”.")
        return ok(f"Copied “{snip['name']}”. Press Ctrl+V where you want it.")

    def _paste_into_previous_window(self) -> bool:
        if self._paste is not None:
            self._paste()
            return True
        hwnd = self.ctx.services.get("last_window")
        hide = self.ctx.services.get("hide_popup")
        if not hwnd:
            return False
        if callable(hide):
            hide()
        from winauto.adapters.winos.apps import focus_window
        from winauto.adapters.winos.keyboard import press

        time.sleep(0.25)
        if not focus_window(hwnd):
            return False
        time.sleep(0.15)
        press("ctrl+v")
        return True

    @tool("List saved snippets.")
    def list_snippets(self) -> ToolResult:
        rows = self.db.query("SELECT * FROM snippets ORDER BY name")
        if not rows:
            return ok("No snippets yet. Try: save snippet address: 12 Lake Road, Pokhara")
        lines = [f"- **{r['name']}**: {' '.join(r['text'].split())[:70]}" for r in rows]
        return ok("Snippets:\n" + "\n".join(lines))

    @tool("Delete a snippet.", params={"name": "Its name"}, risk=Risk.CONFIRM, confirm_label="Delete")
    def delete_snippet(self, name: str) -> ToolResult:
        snip = self._find("snippets", name)
        if not snip:
            return fail(f"There's no snippet called “{name}”.")
        self.db.execute("DELETE FROM snippets WHERE name = ?", (snip["name"],))
        return ok(f"Deleted snippet {snip['name']}.")

    # ----- launcher & quick commands -----

    def suggest(self, query: str) -> list[Suggestion]:
        q = query.strip()
        if not q:
            return []
        out = []
        first, _, rest = q.partition(" ")
        for link in self.db.query("SELECT * FROM quicklinks"):
            n = normalize(link["name"])
            takes_query = "{query}" in link["url"]
            if normalize(first) == n and (rest or not takes_query):
                out.append(Suggestion(title=f"{link['name']}" + (f": {rest}" if rest else ""), subtitle=link["url"],
                                      tool="open_quicklink", args={"name": link["name"], "query": rest},
                                      kind="Quick link", icon="link", score=97))
            elif n.startswith(normalize(q)) and len(q) >= 2:
                out.append(Suggestion(title=link["name"], subtitle=link["url"], tool="open_quicklink",
                                      args={"name": link["name"]}, kind="Quick link", icon="link", score=82))
        snip_q = normalize(re.sub(r"^paste\s+", "", q, flags=re.I))
        if len(snip_q) >= 2:
            for snip in self.db.query("SELECT * FROM snippets"):
                if normalize(snip["name"]).startswith(snip_q):
                    preview = " ".join(snip["text"].split())[:70]
                    out.append(Suggestion(title=f"Paste {snip['name']}", subtitle=preview, tool="paste_snippet",
                                          args={"name": snip["name"]}, kind="Snippet", icon="text", score=85))
        return out

    def quick_rules(self) -> list[QuickRule]:
        def use_link(m):
            link = self._find("quicklinks", m["n"])
            if not link or normalize(link["name"]) != normalize(m["n"]):
                return None
            if "{query}" in link["url"] and not (m["q"] or "").strip():
                return None
            return "open_quicklink", {"name": link["name"], "query": (m["q"] or "").strip()}

        def paste(m):
            snip = self._find("snippets", m["n"])
            return ("paste_snippet", {"name": snip["name"]}) if snip else None

        return [
            QuickRule(r"(?:add|save|new|create)\s+(?:a\s+)?quick\s?link\s+(?P<n>[\w.-]+)\s*(?:->|=|:|as|for)?\s*(?P<u>\S+)",
                      lambda m: ("add_quicklink", {"name": m["n"], "url": m["u"]})),
            QuickRule(r"(?:add|save|new|create)\s+(?:a\s+)?snippet\s+(?P<n>[\w .-]+?)\s*[:=]\s*(?P<t>.+)",
                      lambda m: ("add_snippet", {"name": m["n"], "text": m["t"]})),
            QuickRule(r"(?:show|list)\s+(?:my\s+)?quick\s?links", lambda m: ("list_quicklinks", {})),
            QuickRule(r"(?:show|list)\s+(?:my\s+)?snippets", lambda m: ("list_snippets", {})),
            QuickRule(r"paste\s+(?:my\s+)?(?P<n>.+)", paste, priority=30),
            QuickRule(r"(?:open\s+)?(?P<n>[\w.-]+)(?:\s+(?P<q>.+))?", use_link, priority=25),
        ]
