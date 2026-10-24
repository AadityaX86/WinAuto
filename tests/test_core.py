from __future__ import annotations

import json
import threading
from datetime import datetime
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Literal

import pytest
from fakes import RecordingConfirmer, ScriptedLLM

from winauto.adapters.llm import OllamaClient, OpenAICompatClient
from winauto.adapters.storage.db import Database
from winauto.config import Config, load_config, save_config
from winauto.core.agent import Agent
from winauto.core.llm import LLMError, ToolCall, extract_text_tool_calls, strip_thinking
from winauto.core.matching import best, normalize, score
from winauto.core.quick import QuickMatcher, clean_command, is_simple
from winauto.core.registry import Registry
from winauto.core.skill import QuickRule, Risk, Skill, fail, ok, tool


class Demo(Skill):
    name = "demo"
    prompt_hint = "Demo hint."

    def __init__(self, ctx=None):
        super().__init__(ctx)
        self.sent = []

    @tool("Say hi to someone.", params={"who": "Person to greet"})
    def greet(self, who: str, times: int = 1, loud: bool = False) -> object:
        return ok(("HI " if loud else "hi ") + who + "!" * times)

    @tool("Send a message.", risk=Risk.CONFIRM, editable=("body",), confirm_label="Send")
    def send(self, to: str, body: str):
        self.sent.append((to, body))
        return ok(f"Sent to {to}.")

    @tool("Look something up.", final=False)
    def lookup(self, query: str, kind: Literal["fact", "news"] = "fact"):
        return ok(f"Found stuff about {query}", data={"kind": kind})

    @tool("Always breaks.")
    def broken(self):
        raise RuntimeError("boom")

    @tool("Fails politely.")
    def nope(self, thing: str):
        return fail(f"No {thing} here.", fallback=True)

    @tool("Fails for good.")
    def broken_for_good(self):
        return fail("Only works on Windows.")

    def preview(self, tool_name, args):
        if tool_name == "send":
            return f"To: {args['to']}\n\n{args['body']}"
        return None

    def quick_rules(self):
        return [QuickRule(r"greet (?P<who>\w+)", lambda m: ("greet", {"who": m["who"]})),
                QuickRule(r"windows thing", lambda m: ("broken_for_good", {})),
                QuickRule(r"find (?P<t>\w+)", lambda m: ("nope", {"thing": m["t"]}))]


def make_agent(llm=None, confirmer=None, quick=True):
    reg = Registry()
    skill = Demo()
    reg.add(skill)
    agent = Agent(reg, llm, confirmer or RecordingConfirmer(), quick=QuickMatcher(reg) if quick else None,
                  clock=lambda: datetime(2026, 10, 24, 14, 5))
    return agent, skill


# ---------- skills / schemas ----------

def test_schema_from_signature():
    reg = Registry()
    reg.add(Demo())
    s = reg.get("greet").schema()["function"]
    assert s["parameters"]["required"] == ["who"]
    props = s["parameters"]["properties"]
    assert props["who"] == {"type": "string", "description": "Person to greet"}
    assert props["times"]["type"] == "integer"
    assert props["loud"]["type"] == "boolean"
    assert reg.get("lookup").schema()["function"]["parameters"]["properties"]["kind"]["enum"] == ["fact", "news"]


def test_argument_coercion():
    reg = Registry()
    reg.add(Demo())
    t = reg.get("greet")
    assert t.coerce_args({"who": "Sam", "times": "3", "loud": "yes", "junk": 1}) == {"who": "Sam", "times": 3, "loud": True}
    with pytest.raises(ValueError):
        t.coerce_args({})
    assert reg.get("lookup").coerce_args({"query": "x", "kind": "NEWS"})["kind"] == "news"


# ---------- agent ----------

def test_quick_command_skips_model():
    llm = ScriptedLLM()
    agent, _ = make_agent(llm)
    reply = agent.handle("please greet Sam")
    assert reply.text == "hi Sam!"
    assert not reply.used_model and llm.calls == []


def test_failed_quick_command_falls_back_to_model():
    llm = ScriptedLLM("I couldn't find it either.")
    agent, _ = make_agent(llm)
    reply = agent.handle("find keys")
    assert reply.used_model and reply.text == "I couldn't find it either."


def test_failed_quick_command_without_fallback_stays_quick():
    llm = ScriptedLLM("should not be asked")
    agent, _ = make_agent(llm)
    reply = agent.handle("windows thing")
    assert reply.text == "Only works on Windows." and llm.calls == []


def test_final_tool_ends_without_second_model_call():
    llm = ScriptedLLM(("greet", {"who": "Ana"}))
    agent, _ = make_agent(llm)
    reply = agent.handle("say hello to ana")
    assert reply.text == "hi Ana!"
    assert len(llm.calls) == 1


def test_non_final_tool_feeds_result_back():
    llm = ScriptedLLM(("lookup", {"query": "moon"}), "The moon is far.")
    agent, _ = make_agent(llm)
    reply = agent.handle("how far is the moon")
    assert reply.text == "The moon is far."
    tool_msg = llm.calls[1]["messages"][-1]
    assert tool_msg["role"] == "tool" and json.loads(tool_msg["content"])["ok"] is True


def test_confirmation_approve_with_edit():
    conf = RecordingConfirmer(True, {"body": "edited"})
    llm = ScriptedLLM(("send", {"to": "bo", "body": "draft"}))
    agent, skill = make_agent(llm, conf)
    reply = agent.handle("tell bo hi")
    assert skill.sent == [("bo", "edited")]
    assert conf.requests[0].preview == "To: bo\n\ndraft"
    assert conf.requests[0].confirm_label == "Send"
    assert reply.text == "Sent to bo."


def test_confirmation_cancel():
    llm = ScriptedLLM(("send", {"to": "bo", "body": "draft"}))
    agent, skill = make_agent(llm, RecordingConfirmer(False))
    reply = agent.handle("tell bo hi")
    assert skill.sent == [] and reply.text == "Cancelled."


def test_broken_tool_and_unknown_tool_reported_to_model():
    llm = ScriptedLLM([("broken", {}), ("ghost", {})], "Sorry, that failed.")
    agent, _ = make_agent(llm)
    reply = agent.handle("do it")
    assert reply.text == "Sorry, that failed."
    contents = [json.loads(m["content"]) for m in llm.calls[1]["messages"] if m["role"] == "tool"]
    assert "boom" in contents[0]["message"] and "no tool" in contents[1]["message"].lower()


def test_repeated_call_stops_loop():
    llm = ScriptedLLM(("lookup", {"query": "a"}), ("lookup", {"query": "a"}), "never")
    agent, _ = make_agent(llm)
    reply = agent.handle("loop")
    assert len(llm.calls) == 2 and "Found stuff" in reply.text


def test_history_and_system_prompt():
    llm = ScriptedLLM("one", "two")
    agent, _ = make_agent(llm)
    agent.user_name = "Aaditya"
    agent.handle("first")
    agent.handle("second")
    msgs = llm.calls[1]["messages"]
    assert "Saturday 24 October 2026" in msgs[0]["content"] and "Aaditya" in msgs[0]["content"]
    assert "Demo hint." in msgs[0]["content"]
    assert [m["content"] for m in msgs[1:]] == ["first", "one", "second"]


def test_llm_error_message():
    llm = ScriptedLLM(LLMError("Ollama isn't running."))
    agent, _ = make_agent(llm)
    assert agent.handle("hello").text == "Ollama isn't running."


def test_no_llm_still_runs_quick_commands():
    agent, _ = make_agent(None)
    assert agent.handle("greet Max").text == "hi Max!"
    assert "isn't set up" in agent.handle("what's up").text


# ---------- quick helpers ----------

def test_clean_command():
    assert clean_command("Hey WinAuto, can you please open spotify for me?") == "open spotify"
    assert clean_command("pls volume up thanks!") == "volume up"
    assert is_simple("google chrome") and not is_simple("spotify and play music")


# ---------- text tool calls / thinking ----------

def test_extract_text_tool_calls():
    names = {"open_app"}
    calls, rest = extract_text_tool_calls('<tool_call>{"name": "open_app", "arguments": {"name": "x"}}</tool_call>', names)
    assert calls[0].name == "open_app" and calls[0].arguments == {"name": "x"} and rest == ""
    calls, _ = extract_text_tool_calls('```json\n{"name": "open_app", "parameters": {"name": "y"}}\n```', names)
    assert calls[0].arguments == {"name": "y"}
    calls, rest = extract_text_tool_calls('{"name": "other", "arguments": {}}', names)
    assert calls == []
    assert strip_thinking("<think>hmm</think> Hello") == "Hello"
    assert strip_thinking("Okay, the user wants a greeting.\n</think>\n\nHi!") == "Hi!"  # opening tag was in the prompt


# ---------- Ollama client against a fake server ----------

class FakeOllama(BaseHTTPRequestHandler):
    requests: list = []
    reject_think = False

    def log_message(self, *a):
        pass

    def do_GET(self):
        body = json.dumps({"models": [{"name": "qwen3:8b"}]}).encode()
        self.send_response(200)
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        data = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        FakeOllama.requests.append(data)
        if FakeOllama.reject_think and "think" in data:
            self.send_response(400)
            self.end_headers()
            self.wfile.write(b'{"error":"invalid option think"}')
            return
        last = data["messages"][-1]
        if last["role"] == "user":
            msg = {"role": "assistant", "content": "", "tool_calls": [
                {"function": {"name": "greet", "arguments": {"who": "Zed"}}}]}
        else:
            msg = {"role": "assistant", "content": "<think>x</think>All done."}
        self.send_response(200)
        self.end_headers()
        self.wfile.write(json.dumps({"message": msg, "done": True}).encode())


@pytest.fixture
def ollama_server():
    FakeOllama.requests = []
    FakeOllama.reject_think = False
    server = HTTPServer(("127.0.0.1", 0), FakeOllama)
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    yield f"http://127.0.0.1:{server.server_port}"
    server.shutdown()


def test_ollama_client_roundtrip(ollama_server):
    client = OllamaClient(base_url=ollama_server, model="qwen3:8b", timeout=5)
    assert client.check()[0]
    reply = client.chat([{"role": "user", "content": "hi"}], [{"type": "function", "function": {"name": "greet"}}])
    assert reply.tool_calls[0].name == "greet" and reply.tool_calls[0].arguments == {"who": "Zed"}
    req = FakeOllama.requests[0]
    assert req["think"] is False and req["options"]["num_ctx"] == 8192 and req["stream"] is False
    reply2 = client.chat(
        [{"role": "user", "content": "hi"},
         {"role": "assistant", "content": "", "tool_calls": reply.tool_calls},
         {"role": "tool", "tool_name": "greet", "content": "{}"}], [])
    assert reply2.content == "All done."
    sent = FakeOllama.requests[1]["messages"]
    assert sent[1]["tool_calls"][0]["function"]["name"] == "greet" and sent[2]["tool_name"] == "greet"


def test_ollama_retries_without_think(ollama_server):
    FakeOllama.reject_think = True
    client = OllamaClient(base_url=ollama_server, timeout=5)
    reply = client.chat([{"role": "user", "content": "hi"}], [])
    assert reply.tool_calls and "think" not in FakeOllama.requests[-1]


def test_ollama_unreachable():
    client = OllamaClient(base_url="http://127.0.0.1:9", timeout=2)
    ok_, msg = client.check()
    assert not ok_ and "ollama.com" in msg
    with pytest.raises(LLMError):
        client.chat([{"role": "user", "content": "x"}], [])


def test_openai_message_conversion():
    msgs = OpenAICompatClient._convert([
        {"role": "assistant", "content": "", "tool_calls": [ToolCall("greet", {"who": "a"}, id="c1")]},
        {"role": "tool", "tool_call_id": "c1", "tool_name": "greet", "content": "{}"},
    ])
    assert msgs[0]["tool_calls"][0]["function"]["arguments"] == '{"who": "a"}'
    assert msgs[1] == {"role": "tool", "tool_call_id": "c1", "content": "{}"}


# ---------- matching ----------

def test_matching():
    apps = ["Google Chrome", "Chrome Remote Desktop", "Visual Studio Code", "Spotify", "Word", "WordPad", "Notepad++", "Notepad"]
    assert best("chrome", apps) == "Google Chrome"
    assert best("vs code", apps) is None or best("vsc", apps) == "Visual Studio Code"
    assert best("visual studio", apps) == "Visual Studio Code"
    assert best("spotfy", apps) == "Spotify"
    assert best("word", apps) == "Word"
    assert best("notepad", apps) == "Notepad"
    assert best("notepad++", apps) == "Notepad++"
    assert best("zzz", apps) is None
    assert normalize("Paint.NET.exe") == "paint.net"
    assert score("whatsapp", "WhatsApp") == 100


# ---------- storage / config ----------

def test_database_migrations_and_kv(tmp_path):
    db = Database(tmp_path / "t.db")
    assert db.version >= 1
    nid = db.execute("INSERT INTO notes(title, body, created_at, updated_at) VALUES('t','b','x','x')")
    assert nid == 1 and db.one("SELECT body FROM notes WHERE id=1")["body"] == "b"
    db.set_value("a", "1")
    db.set_value("a", "2")
    assert db.get_value("a") == "2"
    db.close()
    assert Database(tmp_path / "t.db").get_value("a") == "2"


def test_config_roundtrip_and_bad_values(tmp_path):
    p = tmp_path / "c.json"
    cfg = load_config(p)
    assert p.exists() and cfg.llm.model == "qwen3:8b"
    cfg.llm.model = "llama3.1:8b"
    save_config(cfg, p)
    assert load_config(p).llm.model == "llama3.1:8b"
    p.write_text(json.dumps({"llm": {"num_ctx": "4096", "bogus": 1}, "hotkey": "ctrl+space", "nope": 2}))
    cfg = load_config(p)
    assert cfg.llm.num_ctx == 4096 and cfg.hotkey == "ctrl+space" and cfg.llm.model == "qwen3:8b"
    p.write_text("{broken")
    assert isinstance(load_config(p), Config)


def test_tool_selection_narrows_and_falls_back(ctx):
    from winauto.runtime import Runtime

    rt = Runtime(RecordingConfirmer(), db=ctx.db, llm=ScriptedLLM())
    names = lambda skills: sorted(s.name for s in skills)  # noqa: E731
    assert names(rt.registry.select("turn the volume down a bit")) == ["system", "utils", "web"]
    assert "notes" in names(rt.registry.select("add milk to my list"))
    assert names(rt.registry.select("tell me a joke")) == sorted(s.name for s in rt.registry.skills)
    assert "whatsapp" in names(rt.registry.select("tell ram I'm running late"))
    # A follow-up keeps the previous request's skills.
    assert "notes" in names(rt.registry.select("make it due friday", "todo pay rent"))


def test_router_picks_groups_for_unmatched_requests(ctx):
    from winauto.runtime import Runtime

    llm = ScriptedLLM('["media"]', "Here's something relaxing.")
    rt = Runtime(RecordingConfirmer(), db=ctx.db, llm=llm)
    rt.agent.handle("I need something relaxing in my ears")
    router_call, main_call = llm.calls
    assert router_call["tools"] == [] and "- media:" in router_call["messages"][0]["content"]
    offered = {t["function"]["name"] for t in main_call["tools"]}
    assert "play_music" in offered and "search_web" in offered and "add_todo" not in offered


def test_router_bad_reply_offers_everything(ctx):
    from winauto.runtime import Runtime

    llm = ScriptedLLM("no idea", "ok")
    rt = Runtime(RecordingConfirmer(), db=ctx.db, llm=llm)
    rt.agent.handle("hmm hmm")
    assert len(llm.calls[1]["tools"]) == len(rt.registry.tools)


def test_keyword_match_skips_router(ctx):
    from winauto.runtime import Runtime

    llm = ScriptedLLM("done")
    rt = Runtime(RecordingConfirmer(), db=ctx.db, llm=llm)
    rt.agent.handle("email ram about friday's lunch plans")
    assert len(llm.calls) == 1 and "send_email" in {t["function"]["name"] for t in llm.calls[0]["tools"]}
