"""What the engine needs from an AI model, independent of any server.

The agent only knows the `LLMClient` protocol below. The actual clients
(Ollama, OpenAI-compatible servers) live in `winauto.adapters.llm`.

Messages use one internal shape:
    {"role": "system"|"user"|"assistant"|"tool", "content": str,
     "tool_calls": [ToolCall, ...],            # assistant only
     "tool_name": str, "tool_call_id": str,    # tool only
     "images": [base64 PNG, ...]}              # user only, for vision models
"""

from __future__ import annotations

import json
import logging
import re
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Protocol

log = logging.getLogger(__name__)


class LLMError(Exception):
    """The model could not be reached or returned something unusable."""


@dataclass
class ToolCall:
    name: str
    arguments: dict[str, Any] = field(default_factory=dict)
    id: str = field(default_factory=lambda: "call_" + uuid.uuid4().hex[:12])


@dataclass
class LLMReply:
    content: str
    tool_calls: list[ToolCall] = field(default_factory=list)


class LLMClient(Protocol):
    model: str

    def chat(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]],
             on_token: Callable[[str], None] | None = None, model: str | None = None) -> LLMReply: ...

    def check(self) -> tuple[bool, str]: ...


_THINK_RE = re.compile(r"<think>.*?</think>", re.S | re.I)
_TOOL_TAG_RE = re.compile(r"<tool_call>\s*(.*?)\s*</tool_call>", re.S | re.I)
_CODE_BLOCK_RE = re.compile(r"```(?:json)?\s*(\{.*?\}|\[.*?\])\s*```", re.S)


def strip_thinking(text: str) -> str:
    text = _THINK_RE.sub("", text or "")
    # An unclosed <think> means the model ran out of room while thinking.
    if "<think>" in text.lower():
        text = text[: text.lower().index("<think>")]
    return text.strip()


def parse_arguments(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        raw = raw.strip()
        if not raw:
            return {}
        try:
            parsed = json.loads(raw)
        except ValueError:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def _as_calls(obj: Any, tool_names: set[str]) -> list[ToolCall]:
    items = obj if isinstance(obj, list) else [obj]
    calls = []
    for item in items:
        if not isinstance(item, dict):
            return []
        if "function" in item and isinstance(item["function"], dict):
            item = item["function"]
        name = item.get("name") or item.get("tool")
        if not isinstance(name, str) or name not in tool_names:
            return []
        args = item.get("arguments", item.get("parameters", item.get("args", {})))
        calls.append(ToolCall(name=name, arguments=parse_arguments(args)))
    return calls


def extract_text_tool_calls(content: str, tool_names: set[str]) -> tuple[list[ToolCall], str]:
    """Some small models write tool calls as text instead of using the API field.

    Recognises <tool_call>{...}</tool_call>, ```json {...}``` blocks, or a reply
    that is just a JSON object. Only names of real tools are accepted.
    """
    if not content or not tool_names:
        return [], content
    calls: list[ToolCall] = []
    for chunk in _TOOL_TAG_RE.findall(content):
        try:
            calls.extend(_as_calls(json.loads(chunk), tool_names))
        except ValueError:
            continue
    if calls:
        return calls, _TOOL_TAG_RE.sub("", content).strip()
    for chunk in _CODE_BLOCK_RE.findall(content):
        try:
            found = _as_calls(json.loads(chunk), tool_names)
        except ValueError:
            continue
        if found:
            return found, _CODE_BLOCK_RE.sub("", content).strip()
    stripped = content.strip()
    if stripped[:1] in "{[":
        try:
            found = _as_calls(json.loads(stripped), tool_names)
        except ValueError:
            found = []
        if found:
            return found, ""
    return [], content


def schema_tool_names(tools: list[dict[str, Any]]) -> set[str]:
    return {t.get("function", {}).get("name", "") for t in tools}


class TokenGate:
    """Streams answer text to the screen, but holds back tool calls a model writes as text."""

    def __init__(self, on_token: Callable[[str], None] | None):
        self.on_token = on_token
        self.buffer = ""
        self.state = "undecided"  # -> "show" or "hide"

    def feed(self, delta: str) -> None:
        if not self.on_token or not delta or self.state == "hide":
            return
        if self.state == "show":
            self.on_token(delta)
            return
        self.buffer += delta
        head = self.buffer.lstrip()
        if not head:
            return
        if head[0] in "{[" or head.startswith(("```", "<tool", "<think", "<|")):
            self.state = "hide"
            return
        if head[0] == "<" and len(head) < 12:
            return
        if len(head) >= 6 or "\n" in head:
            self.state = "show"
            self.on_token(self.buffer)
            self.buffer = ""

    def finish(self) -> None:
        if self.on_token and self.state == "undecided" and self.buffer.strip():
            head = self.buffer.lstrip()
            if not (head[:1] in "{[<" or head.startswith("```")):
                self.on_token(self.buffer)

