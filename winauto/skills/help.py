"""Help: what WinAuto can do, with examples to type. Works offline, without the AI."""

from __future__ import annotations

from winauto.core.launcher import starts
from winauto.core.skill import QuickRule, Skill, Suggestion, ToolResult, ok, tool

# topic -> (heading, examples). The first two examples also appear in the overview.
TOPICS: dict[str, tuple[str, list[str]]] = {
    "apps": ("Apps and windows", [
        "open spotify", "close notepad", "what apps are open", "snap left", "minimize all",
    ]),
    "todos": ("Todos and notes", [
        "todo buy milk tomorrow", "show my todos", "note the wifi password is on the router",
        "complete todo 2", "show my notes",
    ]),
    "reminders": ("Reminders and timers", [
        "remind me to call mom at 6pm", "timer 10 minutes", "show my reminders", "cancel the timer",
        "remind me to drink water every day at 10am",
    ]),
    "email": ("Email (Gmail)", [
        "check my email", "email ram that the meeting moved to 3pm", "emails from sita",
        "search my email for invoice",
    ]),
    "messages": ("WhatsApp and Discord", [
        "whatsapp ram: on my way", "discord sam: game at 8?", "open chat with mom",
    ]),
    "pc": ("PC controls", [
        "volume 30", "dark mode on", "wifi off", "battery", "brightness 60", "why is my laptop so slow",
        "lock", "take a screenshot",
    ]),
    "web": ("Web and answers", [
        "weather in kathmandu", "google best laptops 2026", "youtube lofi", "100 usd to npr",
        "define serendipity", "news about cricket", "who won the world cup in 2022?",
    ]),
    "files": ("Files", [
        "find my resume pdf", "open downloads", "organize my downloads",
    ]),
    "writing": ("Writing and selected text", [
        "fix the grammar (with text selected)", "what's on my screen?", "translate this to nepali",
        "clipboard history",
    ]),
    "quick": ("Quick tools", [
        "12*7", "10 km to miles", "time in tokyo", "generate a password", ":smile (emoji)",
    ]),
}

ALIASES = {
    "app": "apps", "window": "apps", "windows": "apps", "todo": "todos", "notes": "todos", "note": "todos",
    "tasks": "todos", "reminder": "reminders", "timer": "reminders", "timers": "reminders", "alarm": "reminders",
    "mail": "email", "gmail": "email", "emails": "email", "whatsapp": "messages", "discord": "messages",
    "message": "messages", "chat": "messages", "system": "pc", "volume": "pc", "settings": "pc", "computer": "pc",
    "search": "web", "internet": "web", "weather": "web", "file": "files", "folder": "files", "text": "writing",
    "grammar": "writing", "translate": "writing", "screen": "writing", "calculator": "quick", "tools": "quick",
}


class HelpSkill(Skill):
    name = "help"
    icon = "help"
    description = "What WinAuto can do, with examples to type."
    keywords = r"\b(help|what can you do|how do i use|examples?|commands)\b"

    @tool("Show what WinAuto can do, with examples the user can type.",
          params={"topic": "Optional: apps, todos, reminders, email, messages, pc, web, files, writing or quick"},
          title=lambda a: f"Help: {a['topic']}" if a.get("topic") else "What can WinAuto do?")
    def show_help(self, topic: str = "") -> ToolResult:
        key = topic.strip().lower()
        key = ALIASES.get(key, key)
        if key in TOPICS:
            heading, examples = TOPICS[key]
            lines = [f"**{heading}**: try typing"] + [f"- {e}" for e in examples]
            return ok("\n".join(lines), data={"topic": key, "examples": examples})
        hotkey = self.ctx.config.hotkey.replace("+", " + ").title()
        text_hotkey = self.ctx.config.text_hotkey.replace("+", " + ").title()
        lines = [
            f"Press **{hotkey}** anywhere to open WinAuto, then type. Short commands run instantly; "
            "anything else goes to the AI. Some things you can type:",
            "",
        ]
        for heading, examples in TOPICS.values():
            lines.append(f"- **{heading}**: {examples[0]} · {examples[1]}")
        lines += [
            "",
            f"Select text in any app and press **{text_hotkey}** for writing tools. "
            "Type **help email** (or apps, pc, web…) for more examples.",
        ]
        return ok("\n".join(lines), data={"topics": list(TOPICS)})

    def suggest(self, query: str) -> list[Suggestion]:
        if not starts(query, "help", "what can you do", "how do i use this", "examples"):
            return []
        return [Suggestion(title="What can WinAuto do?", subtitle="Examples of things to type", tool="show_help",
                           args={}, kind="Help", icon="help", score=93)]

    def quick_rules(self) -> list[QuickRule]:
        topic = r"(?:\s+(?:with\s+|on\s+|for\s+|about\s+)?(?P<t>[a-z ]+?))?"
        return [
            QuickRule(r"(?:help|show\s+help|get\s+help)" + topic,
                      lambda m: ("show_help", {"topic": (m["t"] or "").strip()})
                      if not m["t"] or ALIASES.get(m["t"].strip(), m["t"].strip()) in TOPICS else None),
            QuickRule(r"what\s+(?:can|else\s+can)\s+(?:you|winauto)\s+do|how\s+do\s+i\s+use\s+(?:this|you|winauto)"
                      r"|what\s+(?:commands|can\s+i\s+(?:type|say|ask))|(?:show\s+)?(?:some\s+)?examples",
                      lambda m: ("show_help", {})),
        ]
