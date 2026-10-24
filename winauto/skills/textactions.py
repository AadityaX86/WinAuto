"""Writing tools for any app: select text, press Ctrl+Alt+T, then fix, rewrite, shorten, translate...

Like Windows "Click to Do" text actions, but with your local model.
"""

from __future__ import annotations

import time
from typing import Any, Literal

from winauto.core.skill import QuickRule, Skill, ToolResult, fail, ok, tool
from winauto.winos import NotOnWindows

ACTIONS: dict[str, tuple[str, str, str]] = {
    # key: (button label, icon, instruction)
    "fix": ("Fix grammar", "check", "Fix spelling, grammar and punctuation. Keep the meaning, tone and language. Change as little as possible."),
    "formal": ("Make formal", "briefcase", "Rewrite it in a clear, polite, professional tone."),
    "casual": ("Make casual", "smile", "Rewrite it in a relaxed, friendly tone."),
    "shorter": ("Shorter", "minimize", "Make it about half as long while keeping the key points."),
    "longer": ("Expand", "maximize", "Expand it with a little more detail, keeping the same tone."),
    "summarize": ("Summarize", "list", "Summarize it in 2 to 4 short sentences."),
    "bullets": ("Bullet points", "list", "Turn it into a concise bulleted list."),
    "translate": ("Translate", "languages", "Translate it into {language}. Keep the formatting."),
    "explain": ("Explain", "help", "Explain what it means simply, in a few sentences."),
    "reply": ("Draft a reply", "reply", "Write a reply to this message in the user's voice. Short and natural."),
}
REPLACEABLE = {"fix", "formal", "casual", "shorter", "longer", "bullets", "translate"}
SYSTEM = ("You transform text for the user. Output only the resulting text: no preamble, no quotes, "
          "no explanations unless asked to explain.")


class TextActionsSkill(Skill):
    name = "textactions"
    description = "Rewrite, fix, shorten, translate, summarize or explain text."
    keywords = (r"\b(rewrite|rephrase|proofread|grammar|spelling|shorter|longer|formal|casual|polite|translate|"
                r"summari[sz]e|bullet|explain this|selected text|selection)\b")
    prompt_hint = ("Text: to change text the user selected or copied, call transform_text (leave text empty to use "
                   "their selection or clipboard).")

    def __init__(self, ctx: Any, clipboard: Any = None, paste: Any = None):
        super().__init__(ctx)
        self._clipboard = clipboard
        self._paste = paste

    def clipboard(self):
        if self._clipboard is None:
            from winauto.winos.clipboard import WindowsClipboard

            self._clipboard = WindowsClipboard()
        return self._clipboard

    def _source_text(self, text: str) -> str:
        if text.strip():
            return text
        selected = self.ctx.services.get("selection") or ""
        if selected.strip():
            return selected
        try:
            return self.clipboard().get_text() or ""
        except (NotOnWindows, OSError):
            return ""

    @tool(
        "Transform text: fix grammar, make formal/casual/shorter/longer, summarize, bullet points, translate, "
        "explain, or draft a reply. Leave text empty to use the user's selected or copied text.",
        params={"action": "fix, formal, casual, shorter, longer, summarize, bullets, translate, explain, reply, or custom",
                "text": "The text (optional)", "instruction": "For 'custom': what to do with the text",
                "language": "For 'translate': target language"},
    )
    def transform_text(self, action: Literal["fix", "formal", "casual", "shorter", "longer", "summarize", "bullets",
                                             "translate", "explain", "reply", "custom"] = "fix",
                       text: str = "", instruction: str = "", language: str = "English") -> ToolResult:
        source = self._source_text(text).strip()
        if not source:
            return fail("Select or copy some text first, then try again.")
        complete = self.ctx.services.get("complete")
        if not callable(complete):
            return fail("The AI model isn't available.")
        if action == "custom":
            if not instruction.strip():
                return fail("What should I do with the text?")
            task = instruction.strip()
        else:
            task = ACTIONS[action][2].format(language=language or "English")
        if len(source) > 12000:
            source = source[:12000]
        try:
            result = complete(SYSTEM, f"{task}\n\nText:\n\"\"\"\n{source}\n\"\"\"", stream=True).strip()
        except Exception as exc:  # LLMError and friends
            return fail(str(exc))
        result = result.strip().strip('"').strip()
        actions = [{"label": "Copy", "icon": "copy", "tool": "set_clipboard", "args": {"text": result}}]
        if action in REPLACEABLE or action == "custom" or action == "reply":
            actions.insert(0, {"label": "Replace selection" if action != "reply" else "Paste", "icon": "replace",
                               "tool": "replace_selection", "args": {"text": result}})
        return ok(result, data={"text": result, "actions": actions})

    @tool("Paste text over the selection in the app the user was using.", params={"text": "The new text"},
          hides_popup=True)
    def replace_selection(self, text: str) -> ToolResult:
        try:
            self.clipboard().set_text(text)
        except (NotOnWindows, OSError) as exc:
            return fail(str(exc))
        if self._paste is not None:
            self._paste()
            return ok("Replaced.")
        hwnd = self.ctx.services.get("last_window")
        if not hwnd:
            return ok("Copied. Press Ctrl+V where you want it.")
        hide = self.ctx.services.get("hide_popup")
        if callable(hide):
            hide()
        try:
            from winauto.winos.apps import focus_window
            from winauto.winos.keyboard import press

            time.sleep(0.25)
            if not focus_window(hwnd):
                return ok("Copied. Press Ctrl+V where you want it.")
            time.sleep(0.15)
            press("ctrl+v")
        except (NotOnWindows, OSError) as exc:
            return fail(str(exc))
        return ok("Replaced.")

    def quick_rules(self) -> list[QuickRule]:
        def act(name: str, **extra):
            return lambda m: ("transform_text", {"action": name, **extra})

        target = r"(?:\s+(?:this|that|it|the\s+(?:selected\s+)?text|my\s+selection|what\s+i\s+(?:copied|selected)))?"
        return [
            QuickRule(r"(?:fix|correct|proofread)(?:\s+the)?(?:\s+(?:grammar|spelling))?(?:\s+(?:in|of))?" + target, act("fix")),
            QuickRule(r"(?:make|rewrite)" + target + r"\s+(?:more\s+)?(?:formal|professional|polite)", act("formal")),
            QuickRule(r"(?:make|rewrite)" + target + r"\s+(?:more\s+)?(?:casual|friendly|relaxed)", act("casual")),
            QuickRule(r"(?:make|rewrite)" + target + r"\s+shorter|shorten" + target, act("shorter")),
            QuickRule(r"summari[sz]e" + target, act("summarize")),
            QuickRule(r"(?:turn|make)" + target + r"\s+into\s+bullet(?:\s+point)?s|bullet\s+points", act("bullets")),
            QuickRule(r"translate" + target + r"(?:\s+(?:in)?to\s+(?P<lang>[a-z]+))?",
                      lambda m: ("transform_text", {"action": "translate", "language": (m["lang"] or "English").title()})),
            QuickRule(r"explain" + r"(?:\s+(?:this|that|it|what\s+i\s+(?:copied|selected)))", act("explain")),
        ]
