"""Client for WinAuto's built-in AI (adapters/local_ai): starts the engine when first needed."""

from __future__ import annotations

from typing import Any, Callable

from winauto.adapters.llm.openai_compat import OpenAICompatClient
from winauto.adapters.local_ai.manager import DOWNLOADING, ERROR, MISSING, LocalAI
from winauto.adapters.local_ai.server import EngineError
from winauto.core.llm import LLMError, LLMReply

# Long enough for an email or a rewritten page; stops a model that rambles from tying up the engine.
MAX_ANSWER_TOKENS = 1536


class BuiltinClient:
    def __init__(self, ai: LocalAI, temperature: float = 0.2, timeout: float = 180.0,
                 max_tokens: int = MAX_ANSWER_TOKENS):
        self.ai = ai
        self.temperature = temperature
        self.timeout = timeout
        self.max_tokens = max_tokens

    @property
    def model(self) -> str:
        return self.ai.model.name

    def _client(self) -> OpenAICompatClient:
        status = self.ai.status()
        if status.state == DOWNLOADING:
            raise LLMError(f"Your AI is still downloading ({int(status.fraction * 100)}%). "
                           "Quick commands like “open notepad” or “volume 30” work meanwhile.")
        if status.state == MISSING:
            raise LLMError("Your AI isn't downloaded yet: press Download on WinAuto's home screen. "
                           "Quick commands like “open notepad” work meanwhile.")
        try:
            server = self.ai.ensure_running()
        except EngineError as exc:
            raise LLMError(str(exc)) from exc
        return OpenAICompatClient(base_url=server.base_url, model="winauto", temperature=self.temperature,
                                  timeout=self.timeout, api_key=server.api_key, max_tokens=self.max_tokens)

    def chat(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]],
             on_token: Callable[[str], None] | None = None, model: str | None = None) -> LLMReply:
        # One model does both chat and images, so a requested vision model needs nothing special.
        # Always streamed: the time limit then applies between pieces of the answer (a slow PC that's
        # still writing isn't cut off), and giving up closes the connection, which stops the engine
        # working on an answer nobody will read.
        try:
            return self._client().chat(messages, tools, on_token=on_token or _ignore)
        except LLMError as exc:
            if "too long" in str(exc):
                raise LLMError("The AI took too long to answer. On a PC without a graphics card it runs on the "
                               "processor, which is slow for long requests: try a shorter one, or the small model "
                               "in Settings → AI model.") from exc
            raise

    def check(self) -> tuple[bool, str]:
        status = self.ai.status()
        if status.state in (MISSING, DOWNLOADING, ERROR):
            return False, status.message
        try:
            self.ai.ensure_running()
        except EngineError as exc:
            return False, str(exc)
        return True, f"Built-in AI ready ({self.model})."

    def close(self) -> None:
        self.ai.stop()


def _ignore(_text: str) -> None:
    pass
