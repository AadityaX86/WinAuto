"""End to end with the real engine: download (pinned + verified), start, tool call, streaming.

Downloads about 700 MB, so it only runs when WINAUTO_ENGINE_TEST=1 (CI's "Built-in AI" job).
WINAUTO_ENGINE_DIR keeps the downloads between runs.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from winauto.adapters.llm.builtin import BuiltinClient
from winauto.adapters.local_ai import catalog
from winauto.adapters.local_ai.manager import INSTALLED, READY, LocalAI

pytestmark = pytest.mark.skipif(os.environ.get("WINAUTO_ENGINE_TEST") != "1",
                                reason="downloads ~700 MB; set WINAUTO_ENGINE_TEST=1")

SET_VOLUME = {"type": "function", "function": {
    "name": "set_volume", "description": "Set the PC's sound volume.",
    "parameters": {"type": "object", "properties": {"level": {"type": "integer", "description": "0 to 100"}},
                   "required": ["level"]}}}


def test_builtin_ai_end_to_end(tmp_path):
    root = Path(os.environ.get("WINAUTO_ENGINE_DIR") or tmp_path)
    ai = LocalAI(root, catalog.TEST_MODEL.id)
    ai.install()
    assert ai.installed() and ai.status().state == INSTALLED

    client = BuiltinClient(ai)
    ok, message = client.check()
    print(message)
    assert ok, message + "\n" + (root / "logs" / "engine.log").read_text(errors="replace")[-3000:]
    assert ai.status().state == READY

    reply = client.chat([{"role": "system", "content": "You control the user's PC. Use the tools."},
                         {"role": "user", "content": "Set the volume to 30 percent."}], [SET_VOLUME])
    print(reply)
    assert reply.tool_calls and reply.tool_calls[0].name == "set_volume"
    assert int(reply.tool_calls[0].arguments.get("level")) == 30

    tokens: list[str] = []
    streamed = client.chat([{"role": "user", "content": "Reply with one short greeting."}], [], on_token=tokens.append)
    print(streamed.content)
    assert streamed.content.strip() and "".join(tokens).strip()

    client.close()
    assert ai.status().state == INSTALLED
