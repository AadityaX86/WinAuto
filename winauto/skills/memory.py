"""Long-term memory: facts you ask WinAuto to remember, used in every conversation."""

from __future__ import annotations


from winauto.core.matching import rank
from winauto.core.skill import QuickRule, Skill, ToolResult, fail, ok, tool
from winauto.adapters.storage.db import now_iso

MAX_IN_PROMPT = 25


class MemorySkill(Skill):
    name = "memory"
    description = "Facts about the user to remember across conversations."
    keywords = r"\b(remember|forget|memor(?:y|ies|ize)|you know about me|about me)\b"
    prompt_hint = (
        "Memory: when the user shares a lasting personal fact or preference (names, birthdays, likes, how they "
        "want things done), save it with remember_fact."
    )

    @property
    def db(self):
        return self.ctx.db

    def prompt_context(self) -> str:
        rows = self.db.query("SELECT fact FROM memories ORDER BY id DESC LIMIT ?", (MAX_IN_PROMPT,))
        if not rows:
            return ""
        return "Things the user asked you to remember:\n" + "\n".join(f"- {r['fact']}" for r in reversed(rows))

    @tool("Remember a fact about the user for future conversations.", params={"fact": "e.g. 'My sister's name is Sita'"})
    def remember_fact(self, fact: str) -> ToolResult:
        fact = fact.strip().rstrip(".")
        if not fact:
            return fail("What should I remember?")
        existing = [r["fact"].lower() for r in self.db.query("SELECT fact FROM memories")]
        if fact.lower() in existing:
            return ok("I already know that.")
        self.db.execute("INSERT INTO memories(fact, created_at) VALUES(?, ?)", (fact, now_iso()))
        return ok(f"Got it, I'll remember: {fact}.")

    @tool("Forget something you were told to remember.", params={"fact": "Words from the fact to forget"})
    def forget_fact(self, fact: str) -> ToolResult:
        rows = self.db.query("SELECT * FROM memories")
        if not rows:
            return fail("I'm not remembering anything yet.")
        needle = fact.strip().lower()
        hits = [r for r in rows if needle and needle in r["fact"].lower()]
        if not hits:
            best = rank(fact, [r["fact"] for r in rows], limit=1, cutoff=70)
            hits = [r for r in rows if best and r["fact"] == best[0][0]]
        if not hits:
            return fail(f"I don't remember anything about “{fact}”.")
        for r in hits:
            self.db.execute("DELETE FROM memories WHERE id = ?", (r["id"],))
        return ok("Forgotten: " + "; ".join(r["fact"] for r in hits))

    @tool("List everything you've been asked to remember.")
    def list_memories(self) -> ToolResult:
        rows = self.db.query("SELECT fact FROM memories ORDER BY id")
        if not rows:
            return ok("I'm not remembering anything yet. Try: remember that my sister's name is Sita")
        return ok("What I remember about you:\n" + "\n".join(f"- {r['fact']}" for r in rows))

    def quick_rules(self) -> list[QuickRule]:
        return [
            # Facts about the user go to memory; other "remember ..." stays a note.
            QuickRule(r"remember\s+(?:that\s+)?(?P<f>(?:i\b|i'm\b|i am\b|i've\b|my\b|me\b|mine\b).+)",
                      lambda m: ("remember_fact", {"fact": m["f"]}), priority=40),
            QuickRule(r"forget\s+(?:that\s+|about\s+)?(?P<f>.+)", lambda m: ("forget_fact", {"fact": m["f"]})),
            QuickRule(r"what\s+do\s+you\s+(?:know|remember)\s+about\s+me|(?:show|list)\s+(?:your\s+)?memor(?:y|ies)",
                      lambda m: ("list_memories", {})),
        ]
