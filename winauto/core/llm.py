"""Talking to the local AI model.

Two backends:
- OllamaClient: Ollama's native /api/chat (lets us set the context size).
- OpenAICompatClient: any OpenAI-compatible local server (LM Studio, llama.cpp...).

Messages use one internal shape:
    {"role": "system"|"user"|"assistant"|"tool", "content": str,
     "tool_calls": [ToolCall, ...],            # assistant only
     "tool_name": str, "tool_call_id": str}    # tool only
"""

from __future__ import annotations

import json
import logging
import re
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass, field
from typing import Any, Protocol

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

    def chat(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]]) -> LLMReply: ...

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


def _parse_arguments(raw: Any) -> dict[str, Any]:
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
        calls.append(ToolCall(name=name, arguments=_parse_arguments(args)))
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


def _tool_names(tools: list[dict[str, Any]]) -> set[str]:
    return {t.get("function", {}).get("name", "") for t in tools}


def _post_json(url: str, payload: dict[str, Any], timeout: float, headers: dict[str, str] | None = None) -> dict:
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url, data=data, headers={"Content-Type": "application/json", **(headers or {})}, method="POST"
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", "replace")
        raise LLMError(f"HTTP {exc.code}: {body[:500]}") from exc
    except urllib.error.URLError as exc:
        raise LLMError(f"Can't reach the AI server at {url} ({exc.reason}).") from exc
    except TimeoutError as exc:
        raise LLMError("The AI model took too long to answer.") from exc
    except ValueError as exc:
        raise LLMError("The AI server sent back something that isn't JSON.") from exc


def _get_json(url: str, timeout: float, headers: dict[str, str] | None = None) -> dict:
    req = urllib.request.Request(url, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise LLMError(f"HTTP {exc.code} from {url}") from exc
    except (urllib.error.URLError, TimeoutError, ValueError, OSError) as exc:
        raise LLMError(f"Can't reach the AI server at {url}.") from exc


class OllamaClient:
    def __init__(
        self,
        base_url: str = "http://localhost:11434",
        model: str = "qwen3:8b",
        num_ctx: int = 8192,
        temperature: float = 0.2,
        keep_alive: str = "30m",
        timeout: float = 180.0,
    ):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.num_ctx = num_ctx
        self.temperature = temperature
        self.keep_alive = keep_alive
        self.timeout = timeout
        # Ollama >= 0.9 accepts "think": false, which stops thinking models
        # (qwen3, deepseek-r1...) from spending seconds reasoning on every command.
        self._send_think: bool = True

    @staticmethod
    def _convert(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        out = []
        for m in messages:
            msg: dict[str, Any] = {"role": m["role"], "content": m.get("content") or ""}
            if m.get("tool_calls"):
                msg["tool_calls"] = [
                    {"function": {"name": c.name, "arguments": c.arguments}} for c in m["tool_calls"]
                ]
            if m["role"] == "tool" and m.get("tool_name"):
                msg["tool_name"] = m["tool_name"]
            out.append(msg)
        return out

    def chat(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]]) -> LLMReply:
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": self._convert(messages),
            "stream": False,
            "keep_alive": self.keep_alive,
            "options": {"num_ctx": self.num_ctx, "temperature": self.temperature},
        }
        if tools:
            payload["tools"] = tools
        if self._send_think:
            payload["think"] = False
        try:
            data = _post_json(f"{self.base_url}/api/chat", payload, self.timeout)
        except LLMError as exc:
            text = str(exc).lower()
            if self._send_think and "think" in text:
                log.info("Model rejected the 'think' option; retrying without it")
                self._send_think = False
                payload.pop("think", None)
                data = _post_json(f"{self.base_url}/api/chat", payload, self.timeout)
            elif "not found" in text and "model" in text:
                raise LLMError(
                    f"The model '{self.model}' isn't downloaded. Run: ollama pull {self.model}"
                ) from exc
            elif "does not support tools" in text:
                raise LLMError(
                    f"The model '{self.model}' can't use tools. Pick one that can, e.g. qwen3:8b or llama3.1:8b."
                ) from exc
            else:
                raise
        if "error" in data:
            raise LLMError(str(data["error"]))
        message = data.get("message") or {}
        content = strip_thinking(message.get("content", ""))
        calls = []
        for c in message.get("tool_calls") or []:
            fn = c.get("function") or {}
            if fn.get("name"):
                calls.append(ToolCall(name=fn["name"], arguments=_parse_arguments(fn.get("arguments"))))
        if not calls:
            calls, content = extract_text_tool_calls(content, _tool_names(tools))
        return LLMReply(content=content, tool_calls=calls)

    def list_models(self) -> list[str]:
        data = _get_json(f"{self.base_url}/api/tags", timeout=5)
        return sorted(m.get("name", "") for m in data.get("models", []) if m.get("name"))

    def check(self) -> tuple[bool, str]:
        try:
            models = self.list_models()
        except LLMError:
            return False, (
                "Ollama isn't running. Install it from https://ollama.com, start it, "
                f"then run: ollama pull {self.model}"
            )
        wanted = self.model if ":" in self.model else self.model + ":latest"
        if wanted not in models and self.model not in models:
            return False, f"Ollama is running, but the model '{self.model}' isn't downloaded. Run: ollama pull {self.model}"
        return True, f"Connected to Ollama ({self.model})."


class OpenAICompatClient:
    def __init__(
        self,
        base_url: str = "http://localhost:1234/v1",
        model: str = "local-model",
        temperature: float = 0.2,
        timeout: float = 180.0,
        api_key: str = "",
    ):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.temperature = temperature
        self.timeout = timeout
        self.api_key = api_key

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}

    @staticmethod
    def _convert(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        out = []
        for m in messages:
            role = m["role"]
            if role == "tool":
                out.append({"role": "tool", "tool_call_id": m.get("tool_call_id", ""), "content": m.get("content", "")})
                continue
            msg: dict[str, Any] = {"role": role, "content": m.get("content") or ""}
            if m.get("tool_calls"):
                msg["tool_calls"] = [
                    {
                        "id": c.id,
                        "type": "function",
                        "function": {"name": c.name, "arguments": json.dumps(c.arguments)},
                    }
                    for c in m["tool_calls"]
                ]
            out.append(msg)
        return out

    def chat(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]]) -> LLMReply:
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": self._convert(messages),
            "temperature": self.temperature,
            "stream": False,
        }
        if tools:
            payload["tools"] = tools
        data = _post_json(f"{self.base_url}/chat/completions", payload, self.timeout, self._headers())
        try:
            message = data["choices"][0]["message"]
        except (KeyError, IndexError, TypeError) as exc:
            raise LLMError(f"Unexpected reply from the AI server: {str(data)[:300]}") from exc
        content = strip_thinking(message.get("content") or "")
        calls = []
        for c in message.get("tool_calls") or []:
            fn = c.get("function") or {}
            if fn.get("name"):
                calls.append(
                    ToolCall(
                        name=fn["name"],
                        arguments=_parse_arguments(fn.get("arguments")),
                        id=c.get("id") or ToolCall(name="").id,
                    )
                )
        if not calls:
            calls, content = extract_text_tool_calls(content, _tool_names(tools))
        return LLMReply(content=content, tool_calls=calls)

    def check(self) -> tuple[bool, str]:
        try:
            data = _get_json(f"{self.base_url}/models", timeout=5, headers=self._headers())
        except LLMError:
            return False, f"Can't reach the AI server at {self.base_url}. Is it running?"
        names = [m.get("id") for m in data.get("data", [])]
        if names and self.model not in names:
            return True, f"Connected, but '{self.model}' isn't listed. Available: {', '.join(names[:5])}"
        return True, f"Connected to {self.base_url} ({self.model})."


def make_client(cfg: Any) -> LLMClient:
    """Build a client from an LLMConfig."""
    if cfg.backend == "openai":
        return OpenAICompatClient(
            base_url=cfg.base_url, model=cfg.model, temperature=cfg.temperature,
            timeout=cfg.timeout, api_key=cfg.api_key,
        )
    return OllamaClient(
        base_url=cfg.base_url, model=cfg.model, num_ctx=cfg.num_ctx,
        temperature=cfg.temperature, keep_alive=cfg.keep_alive, timeout=cfg.timeout,
    )
