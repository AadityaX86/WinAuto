"""Test doubles."""
from __future__ import annotations

from winauto.core.llm import LLMReply, ToolCall


class ScriptedLLM:
    """Returns pre-written replies in order and records what it was sent."""

    model = "scripted"

    def __init__(self, *replies):
        self.replies = list(replies)
        self.calls = []

    def chat(self, messages, tools):
        self.calls.append({"messages": [dict(m) for m in messages], "tools": tools})
        if not self.replies:
            return LLMReply("(script ended)")
        r = self.replies.pop(0)
        if isinstance(r, Exception):
            raise r
        if isinstance(r, str):
            return LLMReply(r)
        if isinstance(r, tuple):  # (name, args)
            return LLMReply("", [ToolCall(r[0], r[1])])
        if isinstance(r, list):
            return LLMReply("", [ToolCall(n, a) for n, a in r])
        return r

    def check(self):
        return True, "ok"


class RecordingConfirmer:
    def __init__(self, answer=True, edit=None):
        self.answer = answer
        self.edit = edit
        self.requests = []

    def confirm(self, request):
        from winauto.core.agent import Decision
        self.requests.append(request)
        return Decision(self.answer, self.edit)
