"""Any OpenAI-compatible local server (LM Studio, llama.cpp server, vLLM...)."""

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


class OpenAICompatClient:
    def __init__(
        self,
        base_url: str = "http://localhost:1234/v1",
        model: str = "local-model",
        temperature: float = 0.2,
        timeout: float = 180.0,
        api_key: str = "",
        max_tokens: int | None = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.temperature = temperature
        self.timeout = timeout
        self.api_key = api_key
        self.max_tokens = max_tokens  # a cap on the answer's length, so a rambling model can't run for minutes

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
            content: Any = m.get("content") or ""
            if m.get("images"):
                content = [{"type": "text", "text": content}] + [
                    {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{img}"}} for img in m["images"]
                ]
            msg: dict[str, Any] = {"role": role, "content": content}
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

    def chat(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]],
             on_token: Callable[[str], None] | None = None, model: str | None = None) -> LLMReply:
        payload: dict[str, Any] = {
            "model": model or self.model,
            "messages": self._convert(messages),
            "temperature": self.temperature,
            "stream": on_token is not None,
        }
        if self.max_tokens:
            payload["max_tokens"] = self.max_tokens
        if tools:
            payload["tools"] = tools
        url = f"{self.base_url}/chat/completions"
        if on_token is None:
            data = post_json(url, payload, self.timeout, self._headers())
            try:
                message = data["choices"][0]["message"]
            except (KeyError, IndexError, TypeError) as exc:
                raise LLMError(f"Unexpected reply from the AI server: {str(data)[:300]}") from exc
            raw_calls = message.get("tool_calls") or []
            content = message.get("content") or ""
        else:
            content, raw_calls = self._stream(url, payload, on_token)
        content = strip_thinking(content)
        calls = []
        for c in raw_calls:
            fn = c.get("function") or {}
            if fn.get("name"):
                calls.append(
                    ToolCall(
                        name=fn["name"],
                        arguments=parse_arguments(fn.get("arguments")),
                        id=c.get("id") or ToolCall(name="").id,
                    )
                )
        if not calls:
            calls, content = extract_text_tool_calls(content, schema_tool_names(tools))
        return LLMReply(content=content, tool_calls=calls)

    def _stream(self, url: str, payload: dict[str, Any], on_token: Callable[[str], None]) -> tuple[str, list[dict]]:
        gate = TokenGate(on_token)
        content = ""
        calls: dict[int, dict[str, Any]] = {}
        for line in stream_lines(url, payload, self.timeout, self._headers()):
            if not line.startswith("data:"):
                continue
            body = line[5:].strip()
            if body == "[DONE]":
                break
            try:
                chunk = json.loads(body)
                delta = chunk["choices"][0].get("delta") or {}
            except (ValueError, KeyError, IndexError, TypeError):
                continue
            text = delta.get("content") or ""
            content += text
            gate.feed(text)
            for tc in delta.get("tool_calls") or []:
                slot = calls.setdefault(tc.get("index", 0), {"id": "", "function": {"name": "", "arguments": ""}})
                if tc.get("id"):
                    slot["id"] = tc["id"]
                fn = tc.get("function") or {}
                slot["function"]["name"] += fn.get("name") or ""
                slot["function"]["arguments"] += fn.get("arguments") or ""
        gate.finish()
        return content, [calls[i] for i in sorted(calls)]

    def check(self) -> tuple[bool, str]:
        try:
            data = get_json(f"{self.base_url}/models", timeout=5, headers=self._headers())
        except LLMError:
            return False, f"Can't reach the AI server at {self.base_url}. Is it running?"
        names = [m.get("id") for m in data.get("data", [])]
        if names and self.model not in names:
            return True, f"Connected, but '{self.model}' isn't listed. Available: {', '.join(names[:5])}"
        return True, f"Connected to {self.base_url} ({self.model})."
