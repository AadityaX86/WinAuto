"""Notes and todos, stored locally."""

from __future__ import annotations

import re
from datetime import datetime, timedelta
from typing import Any, Literal

from winauto.core.matching import rank
from winauto.core.skill import QuickRule, Risk, Skill, ToolResult, fail, ok, tool
from winauto.core.timeparse import describe, find_when, parse_when
from winauto.storage.db import now_iso


def _ago(stamp: str) -> str:
    try:
        then = datetime.fromisoformat(stamp)
    except ValueError:
        return ""
    delta = datetime.now() - then
    if delta < timedelta(minutes=1):
        return "just now"
    if delta < timedelta(hours=1):
        return f"{int(delta.total_seconds() // 60)} min ago"
    if delta < timedelta(days=1):
        return f"{int(delta.total_seconds() // 3600)} h ago"
    if delta < timedelta(days=2):
        return "yesterday"
    if delta < timedelta(days=30):
        return f"{delta.days} days ago"
    return then.strftime("%d %b %Y")


def _first_words(text: str, n: int = 6) -> str:
    line = text.strip().splitlines()[0] if text.strip() else ""
    words = line.split()
    title = " ".join(words[:n])
    return title + ("…" if len(words) > n else "")


class NotesSkill(Skill):
    name = "notes"
    description = "Notes and todo list."
    prompt_hint = (
        "Notes/todos: to answer questions about things the user saved (passwords hints, addresses, plans), "
        "call search_notes first. Todo ids look like #3. Pass due dates in the user's words, e.g. 'tomorrow 5pm'."
    )

    # ---------- helpers ----------

    @property
    def db(self):
        return self.ctx.db

    def _todo_line(self, row: dict[str, Any], now: datetime | None = None) -> str:
        now = now or datetime.now()
        text = f"#{row['id']} {row['text']}"
        if row.get("priority", 0) > 0:
            text = "‼ " + text
        if row.get("due_at"):
            due = datetime.fromisoformat(row["due_at"])
            has_time = bool(row.get("due_has_time"))
            late = (due < now) if has_time else (due.date() < now.date())
            text += f" — {'⚠ overdue, was due ' if late and not row['done'] else 'due '}{describe(due, has_time, now)}"
        if row.get("done"):
            text = "~~" + text + "~~"
        return text

    def _find_todo(self, ref: str, include_done: bool = False) -> dict[str, Any] | None:
        ref = (ref or "").strip()
        m = re.fullmatch(r"#?\s*(\d+)", ref)
        if m:
            return self.db.one("SELECT * FROM todos WHERE id = ?", (int(m.group(1)),))
        where = "" if include_done else "WHERE done = 0"
        rows = self.db.query(f"SELECT * FROM todos {where} ORDER BY id DESC")
        if not rows:
            return None
        lowered = ref.lower()
        exact = [r for r in rows if lowered and lowered in r["text"].lower()]
        if len(exact) == 1:
            return exact[0]
        texts = {r["text"]: r for r in rows}
        best = rank(ref, texts.keys(), limit=1, cutoff=70)
        return texts[best[0][0]] if best else (exact[0] if exact else None)

    # ---------- notes ----------

    @tool(
        "Save a note.",
        params={"text": "What to write down", "title": "Optional short title"},
    )
    def add_note(self, text: str, title: str = "") -> ToolResult:
        text = text.strip()
        if not text:
            return fail("The note is empty.")
        title = title.strip() or _first_words(text)
        stamp = now_iso()
        note_id = self.db.execute(
            "INSERT INTO notes(title, body, created_at, updated_at) VALUES(?, ?, ?, ?)",
            (title, text, stamp, stamp),
        )
        return ok(f"Saved note #{note_id}: {title}", data={"id": note_id})

    @tool("Show the most recent notes.", params={"limit": "How many (default 10)"})
    def list_notes(self, limit: int = 10) -> ToolResult:
        rows = self.db.query("SELECT * FROM notes ORDER BY updated_at DESC, id DESC LIMIT ?", (max(1, min(limit, 50)),))
        if not rows:
            return ok("You don't have any notes yet. Try: note <something to remember>")
        lines = [f"- #{r['id']} **{r['title']}** ({_ago(r['updated_at'])})" for r in rows]
        return ok("Your notes:\n" + "\n".join(lines))

    @tool(
        "Search notes by words. Use this to answer questions about things the user saved earlier.",
        params={"query": "Words to look for"},
        final=False,
    )
    def search_notes(self, query: str) -> ToolResult:
        words = [w for w in re.findall(r"\w+", query.lower()) if len(w) > 1]
        stop = {"my", "the", "a", "an", "is", "what", "whats", "where", "of", "for", "to", "note", "notes", "about", "did", "i"}
        words = [w for w in words if w not in stop] or words
        if not words:
            return fail("What should I search for?")
        rows = self.db.query("SELECT * FROM notes ORDER BY updated_at DESC")
        scored = []
        for r in rows:
            hay = (r["title"] + " " + r["body"] + " " + r["tags"]).lower()
            hits = sum(1 for w in words if w in hay)
            if hits:
                scored.append((hits, r))
        scored.sort(key=lambda x: -x[0])
        top = [r for _, r in scored[:5]]
        if not top:
            return ok(f"No notes mention '{query}'.", data={"notes": []})
        lines = []
        for r in top:
            body = r["body"] if len(r["body"]) <= 300 else r["body"][:300] + "…"
            lines.append(f"**#{r['id']} {r['title']}**\n{body}")
        return ok("\n\n".join(lines), data={"notes": [{"id": r["id"], "title": r["title"], "body": r["body"][:2000]} for r in top]})

    @tool("Show one note in full.", params={"note_id": "The note's number"}, final=False)
    def read_note(self, note_id: int) -> ToolResult:
        row = self.db.one("SELECT * FROM notes WHERE id = ?", (note_id,))
        if not row:
            return fail(f"There's no note #{note_id}.")
        return ok(f"**#{row['id']} {row['title']}**\n{row['body']}", data={"id": row["id"], "body": row["body"]})

    @tool("Add text to the end of an existing note.", params={"note_id": "The note's number", "text": "Text to add"})
    def append_to_note(self, note_id: int, text: str) -> ToolResult:
        row = self.db.one("SELECT * FROM notes WHERE id = ?", (note_id,))
        if not row:
            return fail(f"There's no note #{note_id}.")
        self.db.execute("UPDATE notes SET body = ?, updated_at = ? WHERE id = ?",
                        (row["body"].rstrip() + "\n" + text.strip(), now_iso(), note_id))
        return ok(f"Added to note #{note_id}.")

    @tool("Delete a note.", params={"note_id": "The note's number"}, risk=Risk.CONFIRM, confirm_label="Delete")
    def delete_note(self, note_id: int) -> ToolResult:
        if not self.db.execute("DELETE FROM notes WHERE id = ?", (note_id,)):
            return fail(f"There's no note #{note_id}.")
        return ok(f"Deleted note #{note_id}.")

    # ---------- todos ----------

    @tool(
        "Add a todo / task to the list.",
        params={
            "task": "What needs doing",
            "due": "When it's due, in plain words (e.g. 'tomorrow 5pm', 'friday') or ISO date. Optional.",
            "priority": "'high' for important ones",
        },
    )
    def add_todo(self, task: str, due: str = "", priority: Literal["normal", "high"] = "normal") -> ToolResult:
        task = task.strip().rstrip(".")
        if not task:
            return fail("What's the todo?")
        when = None
        note = ""
        if due:
            when = parse_when(due)
            if when is None:
                note = f" (I didn't understand the due date '{due}', so I left it out.)"
        else:
            found, rest = find_when(task)
            if found and rest:
                when, task = found, rest
        if re.search(r"\b(urgent|important|asap)\b", task, re.I):
            priority = "high"
        todo_id = self.db.execute(
            "INSERT INTO todos(text, due_at, due_has_time, priority, created_at) VALUES(?, ?, ?, ?, ?)",
            (task, when.dt.isoformat(sep=" ") if when else None, int(bool(when and when.has_time)),
             1 if priority == "high" else 0, now_iso()),
        )
        due_text = f" (due {describe(when.dt, when.has_time)})" if when else ""
        return ok(f"Added todo #{todo_id}: {task}{due_text}.{note}", data={"id": todo_id})

    @tool(
        "Show todos.",
        params={"which": "open (default), today, overdue, upcoming (next 7 days), done, or all"},
    )
    def list_todos(self, which: Literal["open", "today", "overdue", "upcoming", "done", "all"] = "open") -> ToolResult:
        now = datetime.now()
        if which == "done":
            rows = self.db.query("SELECT * FROM todos WHERE done = 1 ORDER BY done_at DESC LIMIT 20")
        elif which == "all":
            rows = self.db.query("SELECT * FROM todos ORDER BY done, COALESCE(due_at, '9999'), id LIMIT 60")
        else:
            rows = self.db.query(
                "SELECT * FROM todos WHERE done = 0 ORDER BY priority DESC, COALESCE(due_at, '9999'), id"
            )
            end_today = datetime.combine(now.date(), datetime.max.time())
            if which == "today":
                rows = [r for r in rows if r["due_at"] and datetime.fromisoformat(r["due_at"]) <= end_today]
            elif which == "overdue":
                rows = [r for r in rows if r["due_at"] and self._is_overdue(r, now)]
            elif which == "upcoming":
                limit = end_today + timedelta(days=7)
                rows = [r for r in rows if r["due_at"] and datetime.fromisoformat(r["due_at"]) <= limit]
        if not rows:
            empty = {
                "open": "Your todo list is empty. 🎉",
                "today": "Nothing due today.",
                "overdue": "Nothing overdue.",
                "upcoming": "Nothing due in the next week.",
                "done": "No finished todos yet.",
                "all": "No todos yet.",
            }
            return ok(empty[which])
        heading = {"open": "Todos", "today": "Due today", "overdue": "Overdue", "upcoming": "Next 7 days",
                   "done": "Done", "all": "All todos"}[which]
        lines = [f"- {self._todo_line(r, now)}" for r in rows]
        return ok(f"{heading}:\n" + "\n".join(lines), data={"count": len(rows)})

    @staticmethod
    def _is_overdue(row: dict[str, Any], now: datetime) -> bool:
        due = datetime.fromisoformat(row["due_at"])
        return due < now if row.get("due_has_time") else due.date() < now.date()

    @tool("Mark a todo as done.", params={"todo": "The todo's number (e.g. 3 or #3) or some of its words"})
    def complete_todo(self, todo: str) -> ToolResult:
        row = self._find_todo(todo)
        if not row:
            return fail(f"I couldn't find an open todo matching '{todo}'.", fallback=True)
        if row["done"]:
            return ok(f"#{row['id']} {row['text']} was already done.")
        self.db.execute("UPDATE todos SET done = 1, done_at = ? WHERE id = ?", (now_iso(), row["id"]))
        left = self.db.one("SELECT COUNT(*) AS n FROM todos WHERE done = 0")["n"]
        return ok(f"✓ Done: {row['text']}. {left} left.")

    @tool(
        "Change a todo's text or due date.",
        params={"todo": "The todo's number or words", "text": "New text (optional)",
                "due": "New due date in plain words, or 'none' to clear it (optional)"},
    )
    def update_todo(self, todo: str, text: str = "", due: str = "") -> ToolResult:
        row = self._find_todo(todo, include_done=True)
        if not row:
            return fail(f"I couldn't find a todo matching '{todo}'.")
        changes = []
        if text.strip():
            self.db.execute("UPDATE todos SET text = ? WHERE id = ?", (text.strip(), row["id"]))
            changes.append(f"renamed to '{text.strip()}'")
        if due.strip():
            if due.strip().lower() in ("none", "no", "clear", "remove"):
                self.db.execute("UPDATE todos SET due_at = NULL, due_has_time = 0 WHERE id = ?", (row["id"],))
                changes.append("no due date")
            else:
                when = parse_when(due)
                if when is None:
                    return fail(f"I didn't understand the date '{due}'.")
                self.db.execute("UPDATE todos SET due_at = ?, due_has_time = ? WHERE id = ?",
                                (when.dt.isoformat(sep=" "), int(when.has_time), row["id"]))
                changes.append(f"due {describe(when.dt, when.has_time)}")
        if not changes:
            return fail("Tell me the new text or due date.")
        return ok(f"Updated #{row['id']}: " + ", ".join(changes) + ".")

    @tool("Delete a todo.", params={"todo": "The todo's number or words"}, risk=Risk.CONFIRM, confirm_label="Delete")
    def delete_todo(self, todo: str) -> ToolResult:
        row = self._find_todo(todo, include_done=True)
        if not row:
            return fail(f"I couldn't find a todo matching '{todo}'.")
        self.db.execute("DELETE FROM todos WHERE id = ?", (row["id"],))
        return ok(f"Deleted #{row['id']} {row['text']}.")

    @tool("Remove all finished todos from the list.", risk=Risk.CONFIRM, confirm_label="Clear")
    def clear_done_todos(self) -> ToolResult:
        n = self.db.execute("DELETE FROM todos WHERE done = 1")
        return ok(f"Cleared {n} finished todo(s).")

    def preview(self, tool_name: str, args: dict[str, Any]) -> str | None:
        if tool_name == "delete_note":
            row = self.db.one("SELECT * FROM notes WHERE id = ?", (args.get("note_id"),))
            return f"Delete note #{args.get('note_id')}: {row['title']}?" if row else None
        if tool_name == "delete_todo":
            row = self._find_todo(str(args.get("todo", "")), include_done=True)
            return f"Delete todo #{row['id']}: {row['text']}?" if row else None
        if tool_name == "clear_done_todos":
            n = self.db.one("SELECT COUNT(*) AS n FROM todos WHERE done = 1")["n"]
            return f"Remove {n} finished todo(s)?"
        return None

    # ---------- quick commands ----------

    def quick_rules(self) -> list[QuickRule]:
        which_words = {"today": "today", "overdue": "overdue", "done": "done", "completed": "done",
                       "finished": "done", "all": "all", "this week": "upcoming", "upcoming": "upcoming"}

        def list_todos(m):
            w = (m["w"] or "").lower()
            return "list_todos", {"which": which_words.get(w, "open")}

        def add_note(m):
            text = re.sub(r"^that\s+", "", m["t"].strip(), flags=re.I)
            return "add_note", {"text": text}

        todo_words = r"(?:todos?|to-?dos?|to do list|to-?do list|tasks)"
        return [
            QuickRule(r"(?:(?:add|new|create)\s+(?:an?\s+)?(?:new\s+)?)?(?:todo|to-do|to do)\s*[:\-]?\s+(?P<t>.+)",
                      lambda m: ("add_todo", {"task": m["t"]}) if not re.fullmatch(r"list|lists", m["t"], re.I) else None),
            QuickRule(r"(?:add|new|create)\s+(?:an?\s+)?(?:new\s+)?task\s*[:\-]?\s+(?P<t>.+)|task\s*:\s*(?P<t2>.+)",
                      lambda m: ("add_todo", {"task": m["t"] or m["t2"]})),
            QuickRule(r"add\s+(?P<t>.+?)\s+to\s+(?:my\s+)?(?:todos?|to-?do list|to-?dos|tasks?|list)",
                      lambda m: ("add_todo", {"task": m["t"]})),
            QuickRule(r"(?:(?:show|list|view|open|see|check)\s+)?(?:me\s+)?(?:my\s+)?(?:the\s+)?"
                      r"(?:(?P<w>today'?s|overdue|done|completed|finished|all)\s+)?" + todo_words +
                      r"(?:\s+(?:for\s+)?(?P<w2>today|this week|overdue|done))?",
                      lambda m: ("list_todos", {"which": which_words.get((m["w2"] or m["w"] or "").lower().replace("'s", ""), "open")})),
            QuickRule(r"what(?:'s| is)\s+on\s+(?:my\s+)?(?:todo\s+|to-?do\s+|task\s+)?list(?:\s+(?:for\s+)?(?P<w>today|this week))?",
                      list_todos),
            QuickRule(r"what\s+do\s+i\s+(?:have|need)\s+to\s+do(?:\s+(?P<w>today|this week))?", list_todos),
            QuickRule(r"what\s+are\s+my\s+" + todo_words + r"(?:\s+(?:for\s+)?(?P<w>today|this week))?", list_todos),
            QuickRule(r"(?:mark\s+)?(?:todo\s+|task\s+)?#?(?P<id>\d+)\s+(?:as\s+)?(?:done|complete|completed|finished)",
                      lambda m: ("complete_todo", {"todo": m["id"]})),
            QuickRule(r"(?:done|complete|finish|finished|check off|tick off)\s+(?:todo\s+|task\s+)?(?P<t>.+)",
                      lambda m: ("complete_todo", {"todo": m["t"]})),
            QuickRule(r"(?:take\s+a\s+|make\s+a\s+|add\s+a\s+|new\s+|save\s+a\s+)?note\s*[:\-]?\s+(?P<t>.+)", add_note),
            QuickRule(r"(?:remember|write down|jot down)\s+(?:that\s+)?(?P<t>.+)", add_note),
            QuickRule(r"(?:(?:show|list|view|open)\s+)?(?:me\s+)?(?:my\s+)?(?:all\s+)?notes", lambda m: ("list_notes", {})),
            QuickRule(r"(?:find|search)\s+(?:in\s+)?(?:my\s+)?notes?\s+(?:for\s+)?(?P<q>.+)",
                      lambda m: ("search_notes", {"query": m["q"]})),
        ]
