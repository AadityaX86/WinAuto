"""AI model clients. Add a new backend by writing a client with the
`winauto.core.llm.LLMClient` methods and adding it to `make_client`."""

from __future__ import annotations

from typing import Any

from winauto.adapters.llm.ollama import OllamaClient
from winauto.adapters.llm.openai_compat import OpenAICompatClient
from winauto.core.llm import LLMClient

__all__ = ["OllamaClient", "OpenAICompatClient", "make_client"]


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
