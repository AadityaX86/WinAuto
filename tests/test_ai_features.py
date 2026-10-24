from __future__ import annotations

import json

import pytest

from fakes import RecordingConfirmer, ScriptedLLM
from test_phase3 import FakeClipboard
from winauto.core.llm import OllamaClient, TokenGate
from winauto.skills.memory import MemorySkill
from winauto.skills.textactions import TextActionsSkill
from winauto.skills.vision import VisionSkill, encode_image


@pytest.fixture
def runtime(ctx):
    from winauto.runtime import Runtime

    return Runtime(RecordingConfirmer(), db=ctx.db, llm=ScriptedLLM())


# ---------- streaming ----------

def test_token_gate_shows_text_and_hides_tool_json():
    shown = []
    gate = TokenGate(shown.append)
    for piece in ["Hel", "lo there", ", friend"]:
        gate.feed(piece)
    assert "".join(shown) == "Hello there, friend"
    hidden = []
    gate = TokenGate(hidden.append)
    for piece in ['{"na', 'me": "open_app"}']:
        gate.feed(piece)
    gate.finish()
    assert hidden == []
    short = []
    gate = TokenGate(short.append)
    gate.feed("Hi")
    gate.finish()
    assert short == ["Hi"]


def test_ollama_streaming(monkeypatch):
    lines = [json.dumps({"message": {"content": "Sure, "}, "done": False}),
             json.dumps({"message": {"content": "here you go."}, "done": False}),
             json.dumps({"message": {"content": "", "tool_calls": [{"function": {"name": "x", "arguments": {}}}]}, "done": True})]
    import winauto.core.llm as llm

    monkeypatch.setattr(llm, "_stream_lines", lambda url, payload, timeout, headers=None: iter(lines))
    tokens = []
    reply = OllamaClient().chat([{"role": "user", "content": "hi"}], [{"type": "function", "function": {"name": "x"}}],
                                on_token=tokens.append)
    assert "".join(tokens) == "Sure, here you go." and reply.tool_calls[0].name == "x"


def test_agent_streams_and_marks_new_answers(runtime):
    tokens = []
    runtime.agent.on_token = tokens.append
    runtime.agent.llm.replies += ["[]", "Paris is the capital."]  # router call, then the answer
    reply = runtime.agent.handle("what is the capital of france")
    assert reply.text == "Paris is the capital."
    assert "" in tokens and "".join(tokens).strip() == "Paris is the capital."


def test_images_are_sent_to_ollama():
    msgs = OllamaClient._convert([{"role": "user", "content": "what?", "images": ["AAA"]}])
    assert msgs[0]["images"] == ["AAA"]
    from winauto.core.llm import OpenAICompatClient

    msgs = OpenAICompatClient._convert([{"role": "user", "content": "what?", "images": ["AAA"]}])
    assert msgs[0]["content"][1]["image_url"]["url"] == "data:image/png;base64,AAA"


# ---------- memory ----------

def test_memory(runtime):
    mem = runtime.ctx.services["skills"]["memory"]
    assert mem.remember_fact("My sister's name is Sita.").ok
    assert mem.remember_fact("my sister's name is sita").message == "I already know that."
    assert "My sister's name is Sita" in runtime.agent.system_prompt()
    assert "Sita" in mem.list_memories().message
    assert mem.forget_fact("sister").ok
    assert "Sita" not in runtime.agent.system_prompt()


def test_memory_routing(runtime):
    m = runtime.ctx.services["quick_match"]
    assert m("remember that my birthday is on 5 May").name == "remember_fact"
    assert m("remember the car is on level 3").name == "add_note"
    assert m("what do you know about me").name == "list_memories"


# ---------- text actions ----------

def test_transform_text_uses_selection_and_offers_replace(runtime):
    cb = FakeClipboard()
    pasted = []
    skill = TextActionsSkill(runtime.ctx, clipboard=cb, paste=lambda: pasted.append(cb.text))
    runtime.ctx.services["selection"] = "i has went to the shop"
    runtime.agent.llm.replies.append("I went to the shop.")
    r = skill.transform_text("fix")
    assert r.ok and r.message == "I went to the shop."
    prompt = runtime.agent.llm.calls[-1]["messages"][1]["content"]
    assert "i has went to the shop" in prompt and "spelling" in prompt
    labels = [a["label"] for a in r.data["actions"]]
    assert labels == ["Replace selection", "Copy"]
    assert skill.replace_selection("I went to the shop.").ok and pasted == ["I went to the shop."]
    runtime.agent.llm.replies.append("Summary.")
    assert [a["label"] for a in skill.transform_text("summarize").data["actions"]] == ["Copy"]


def test_transform_text_needs_text(ctx):
    skill = TextActionsSkill(ctx, clipboard=FakeClipboard())
    assert not skill.transform_text("fix").ok


def test_text_quick_rules(runtime):
    m = runtime.ctx.services["quick_match"]
    assert m("fix the grammar").arguments == {"action": "fix"}
    assert m("translate this to nepali").arguments == {"action": "translate", "language": "Nepali"}
    assert m("make it more formal").arguments == {"action": "formal"}
    assert m("summarize this").arguments == {"action": "summarize"}


# ---------- vision ----------

def test_vision(runtime):
    from PIL import Image

    img = Image.new("RGB", (3200, 1800), "white")
    assert len(encode_image(img)) > 10
    runtime.config.llm.vision_model = "gemma3:4b"
    skill = VisionSkill(runtime.ctx, grabber=lambda hwnd: img)
    runtime.agent.llm.replies.append("A blank white screen.")
    r = skill.ask_about_screen("what's this?")
    assert r.ok and r.message == "A blank white screen."
    call = runtime.agent.llm.calls[-1]
    assert call["model"] == "gemma3:4b" and call["messages"][1]["images"]
    assert runtime.ctx.services["quick_match"]("what's on my screen").name == "ask_about_screen"
