"""Ollama's native /api/chat (lets us set the context size and turn off "thinking")."""

from __future__ import annotations

import json
import logging
from typing import Any, Callable

from winauto.adapters.llm.http import get_json, post_json, stream_lines
from winauto.core.llm import (
    LLMError,
    LLMReply,
    TokenGate,
    ToolCall,
    extract_text_tool_calls,
    parse_arguments,
    schema_tool_names,
    strip_thinking,
)

log = logging.getLogger(__name__)


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
            if m.get("images"):
                msg["images"] = list(m["images"])  # base64 strings
            out.append(msg)
        return out

    def _friendly(self, exc: LLMError, model: str) -> LLMError:
        text = str(exc).lower()
        if "not found" in text and "model" in text:
            return LLMError(f"The model '{model}' isn't downloaded. Run: ollama pull {model}")
        if "can't reach" in text:
            return LLMError(
                "The AI model isn't running. Start Ollama (or run 'ollama serve'), then try again. "
                "Quick commands like 'open notepad' still work."
            )
        if "does not support tools" in text:
            return LLMError(f"The model '{model}' can't use tools. Pick one that can, e.g. qwen3:8b or llama3.1:8b.")
        return exc

    def chat(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]],
             on_token: Callable[[str], None] | None = None, model: str | None = None) -> LLMReply:
        model = model or self.model
        payload: dict[str, Any] = {
            "model": model,
            "messages": self._convert(messages),
            "stream": on_token is not None,
            "keep_alive": self.keep_alive,
            "options": {"num_ctx": self.num_ctx, "temperature": self.temperature},
        }
        if tools:
            payload["tools"] = tools
        if self._send_think:
            payload["think"] = False
        try:
            message = self._send(payload, on_token)
        except LLMError as exc:
            if self._send_think and "think" in str(exc).lower():
                log.info("Model rejected the 'think' option; retrying without it")
                self._send_think = False
                payload.pop("think", None)
                try:
                    message = self._send(payload, on_token)
                except LLMError as exc2:
                    raise self._friendly(exc2, model) from exc2
            else:
                raise self._friendly(exc, model) from exc
        content = strip_thinking(message.get("content", ""))
        calls = []
        for c in message.get("tool_calls") or []:
            fn = c.get("function") or {}
            if fn.get("name"):
                calls.append(ToolCall(name=fn["name"], arguments=parse_arguments(fn.get("arguments"))))
        if not calls:
            calls, content = extract_text_tool_calls(content, schema_tool_names(tools))
        return LLMReply(content=content, tool_calls=calls)

    def _send(self, payload: dict[str, Any], on_token: Callable[[str], None] | None) -> dict[str, Any]:
        url = f"{self.base_url}/api/chat"
        if not payload["stream"]:
            data = post_json(url, payload, self.timeout)
            if "error" in data:
                raise LLMError(str(data["error"]))
            return data.get("message") or {}
        gate = TokenGate(on_token)
        content, calls = "", []
        for line in stream_lines(url, payload, self.timeout):
            try:
                chunk = json.loads(line)
            except ValueError:
                continue
            if "error" in chunk:
                raise LLMError(str(chunk["error"]))
            msg = chunk.get("message") or {}
            delta = msg.get("content") or ""
            content += delta
            gate.feed(delta)
            calls += msg.get("tool_calls") or []
            if chunk.get("done"):
                break
        gate.finish()
        return {"content": content, "tool_calls": calls}

    def list_models(self) -> list[str]:
        data = get_json(f"{self.base_url}/api/tags", timeout=5)
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
