"""Small JSON-over-HTTP helpers shared by the model clients."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any, Iterator

from winauto.core.llm import LLMError


def request(url: str, payload: dict[str, Any] | None, timeout: float, headers: dict[str, str] | None = None):
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(
        url, data=data, headers={"Content-Type": "application/json", **(headers or {})},
        method="POST" if payload is not None else "GET",
    )
    try:
        return urllib.request.urlopen(req, timeout=timeout)
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", "replace")
        raise LLMError(f"HTTP {exc.code}: {body[:500]}") from exc
    except urllib.error.URLError as exc:
        raise LLMError(f"Can't reach the AI server at {url} ({exc.reason}).") from exc
    except TimeoutError as exc:
        raise LLMError("The AI model took too long to answer.") from exc


def post_json(url: str, payload: dict[str, Any], timeout: float, headers: dict[str, str] | None = None) -> dict:
    try:
        with request(url, payload, timeout, headers) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except TimeoutError as exc:
        raise LLMError("The AI model took too long to answer.") from exc
    except ValueError as exc:
        raise LLMError("The AI server sent back something that isn't JSON.") from exc


def stream_lines(url: str, payload: dict[str, Any], timeout: float,
                  headers: dict[str, str] | None = None) -> Iterator[str]:
    try:
        with request(url, payload, timeout, headers) as resp:
            for raw in resp:
                line = raw.decode("utf-8", "replace").strip()
                if line:
                    yield line
    except TimeoutError as exc:
        raise LLMError("The AI model took too long to answer.") from exc
    except OSError as exc:
        raise LLMError(f"The connection to the AI server dropped ({exc}).") from exc


def get_json(url: str, timeout: float, headers: dict[str, str] | None = None) -> dict:
    req = urllib.request.Request(url, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise LLMError(f"HTTP {exc.code} from {url}") from exc
    except (urllib.error.URLError, TimeoutError, ValueError, OSError) as exc:
        raise LLMError(f"Can't reach the AI server at {url}.") from exc
