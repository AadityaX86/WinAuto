"""The agent: turns a request into tool calls and a reply.

Flow for each request:
1. Quick commands (offline, instant) if one clearly matches.
2. Otherwise ask the local model, run the tools it picks, feed results back,
   and repeat until it answers (or the tools' results already answer it).
Risky tools go through the Confirmer (the UI's Send / Cancel card) first.
"""

from __future__ import annotations

import json
import logging
import threading
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Protocol

from winauto.core.llm import LLMClient, LLMError, ToolCall
from winauto.core.quick import QuickMatcher
from winauto.core.registry import Registry
from winauto.core.skill import ArgumentError, Risk, Tool, ToolResult, fail

log = logging.getLogger(__name__)


@dataclass
class ConfirmRequest:
    tool: str
    title: str
    preview: str
    args: dict[str, Any]
    editable: tuple[str, ...] = ()
    confirm_label: str = "Approve"


@dataclass
class Decision:
    approved: bool
    args: dict[str, Any] | None = None  # edited arguments, if the user changed them


class Confirmer(Protocol):
    def confirm(self, request: ConfirmRequest) -> Decision: ...


def _parse_names(content: str) -> list[str] | None:
    import re

    m = re.search(r"\[[^\[\]]*\]", content or "")
    if not m:
        return None
    try:
        names = json.loads(m.group(0))
    except ValueError:
        return None
    return [str(n).strip().lower() for n in names] if isinstance(names, list) else None


class DenyAll:
    def confirm(self, request: ConfirmRequest) -> Decision:
        return Decision(False)


class ApproveAll:
    def confirm(self, request: ConfirmRequest) -> Decision:
        return Decision(True)


@dataclass
class Step:
    tool: str
    args: dict[str, Any]
    result: ToolResult


@dataclass
class AgentReply:
    text: str
    steps: list[Step] = field(default_factory=list)
    used_model: bool = False
    error: str | None = None


SYSTEM_PROMPT = """You are WinAuto, an assistant running on the user's Windows PC. You do everyday tasks for them by calling tools.

Now: {now}.{user}

Rules:
- If a request needs an action or the user's own data (apps, notes, todos, email, messages, files, settings), call a tool. Do it; don't just describe it.
- Only say something was done if a tool result says it worked. If a tool fails, say so briefly and suggest a fix.
- For anything that may have changed (news, prices, scores, weather, "latest"), call search_web and answer from the results, naming the source.
- Sending, deleting and shutting down automatically show the user an approval card, so call those tools directly; don't ask "should I?" in chat.
- If something essential is missing (who to email, what to say), ask one short question instead of guessing.
- When writing emails or messages for the user, write them in the user's voice, ready to send.
- Keep replies short: one to three sentences or a short list. No preamble.
{hints}"""


ROUTER_PROMPT = """Decide which tool groups a request to a Windows PC assistant needs.

Groups:
{groups}

Reply with only a JSON list of group names, e.g. ["apps"] or ["notes", "reminders"].
Reply [] if the request is just conversation or general knowledge."""

# Below this many tokens of tool definitions, just send them all.
ROUTING_THRESHOLD = 2500


class Agent:
    def __init__(
        self,
        registry: Registry,
        llm: LLMClient | None,
        confirmer: Confirmer,
        *,
        quick: QuickMatcher | None = None,
        history_turns: int = 6,
        max_steps: int = 6,
        user_name: str = "",
        on_status: Callable[[str], None] | None = None,
        clock: Callable[[], datetime] = datetime.now,
    ):
        self.registry = registry
        self.llm = llm
        self.confirmer = confirmer
        self.quick = quick
        self.history_turns = history_turns
        self.max_steps = max_steps
        self.user_name = user_name
        self.on_status = on_status or (lambda s: None)
        self.clock = clock
        self.history: list[dict[str, Any]] = []
        self._cancel = threading.Event()
        # Streams answer text as it's generated. "" means "a new answer starts here".
        self.on_token: Callable[[str], None] | None = None

    # ----- public -----

    def reset(self) -> None:
        self.history.clear()

    def cancel(self) -> None:
        self._cancel.set()

    def system_prompt(self, skills=None) -> str:
        now = self.clock()
        hints = self.registry.prompt_hints(skills)
        context = self.registry.prompt_contexts()
        return SYSTEM_PROMPT.format(
            now=now.strftime("%A %d %B %Y, %H:%M"),
            user=f" The user's name is {self.user_name}." if self.user_name else "",
            hints=("\nSkill notes:\n" + hints) if hints else "",
        ) + (("\n" + context) if context else "")

    def handle(self, text: str) -> AgentReply:
        self._cancel.clear()
        text = (text or "").strip()
        if not text:
            return AgentReply("")
        reply = self._handle(text)
        self._remember(text, reply)
        return reply

    # ----- internals -----

    def _handle(self, text: str) -> AgentReply:
        if self.quick:
            call = self.quick.match(text)
            if call:
                log.info("Quick command: %s %s", call.name, call.arguments)
                result = self.run_tool(call)
                step = Step(call.name, call.arguments, result)
                # A quick command that couldn't find its target (e.g. no app by that
                # name) gets a second chance with the model, which may know what was meant.
                if not (result.fallback and self.llm is not None):
                    return AgentReply(result.message, [step], error=None if result.ok or result.cancelled else "tool")
        if self.llm is None:
            return AgentReply(
                "The AI model isn't set up yet, so I can only do quick commands like "
                "\"open notepad\" or \"todo buy milk\". Open Settings to connect a model.",
                error="no-llm",
            )
        try:
            return self._run_model(text)
        except LLMError as exc:
            log.warning("LLM error: %s", exc)
            return AgentReply(str(exc), error="llm")

    def _run_model(self, text: str) -> AgentReply:
        assert self.llm is not None
        # Only offer tools that fit this request (and the previous one, for follow-ups
        # like "send it"); fewer tools means a faster, less confused local model.
        previous = next((m["content"] for m in reversed(self.history) if m["role"] == "user"), "")
        skills = self._choose_skills(text, previous)
        messages: list[dict[str, Any]] = [{"role": "system", "content": self.system_prompt(skills)}]
        messages += self.history
        messages.append({"role": "user", "content": text})
        schemas = self.registry.schemas(skills)
        steps: list[Step] = []
        seen_calls: set[str] = set()
        last_messages: list[str] = []

        for _ in range(self.max_steps):
            if self._cancel.is_set():
                return AgentReply("Stopped.", steps, True)
            self.on_status("Thinking…")
            if self.on_token:
                self.on_token("")
            reply = self.llm.chat(messages, schemas, on_token=self.on_token)
            if not reply.tool_calls:
                answer = reply.content.strip() or ("\n".join(last_messages) if last_messages else "Done.")
                return AgentReply(answer, steps, True)

            messages.append({"role": "assistant", "content": reply.content, "tool_calls": reply.tool_calls})
            results: list[tuple[Tool | None, ToolResult]] = []
            repeated = False
            for call in reply.tool_calls:
                key = call.name + json.dumps(call.arguments, sort_keys=True, default=str)
                repeated = repeated or key in seen_calls
                seen_calls.add(key)
                result = self.run_tool(call)
                steps.append(Step(call.name, call.arguments, result))
                results.append((self.registry.get(call.name), result))
                messages.append(
                    {
                        "role": "tool",
                        "tool_name": call.name,
                        "tool_call_id": call.id,
                        "content": result.for_model(),
                    }
                )
            last_messages = [r.message for _, r in results if r.message]

            if any(r.cancelled for _, r in results):
                return AgentReply("\n".join(last_messages) or "Cancelled.", steps, True)
            if all(t is not None and t.final and r.ok for t, r in results):
                return AgentReply("\n".join(last_messages), steps, True)
            if repeated:
                # The model is going in circles; show what we have.
                return AgentReply("\n".join(last_messages), steps, True)

        return AgentReply("\n".join(last_messages) or "I couldn't finish that one.", steps, True)

    def _choose_skills(self, text: str, previous: str) -> list:
        matched = self.registry.matched(text, previous)
        if matched:
            return self.registry.with_always(matched)
        everything = self.registry.skills
        if self.registry.schema_size() <= ROUTING_THRESHOLD:
            return everything
        # No keyword matched and all tools won't fit comfortably in a local model's
        # context: a quick, tool-free call picks the groups instead.
        self.on_status("Thinking…")
        groups = "\n".join(f"- {s.name}: {s.description}" for s in everything)
        reply = self.llm.chat(
            [{"role": "system", "content": ROUTER_PROMPT.format(groups=groups)}, {"role": "user", "content": text}],
            [],
        )
        names = _parse_names(reply.content)
        if names is None:
            log.info("Router reply not understood (%r); offering every tool", reply.content[:200])
            return everything
        chosen = [s for s in everything if s.name in names]
        log.info("Router picked %s", [s.name for s in chosen])
        return self.registry.with_always(chosen)

    def run_tool(self, call: ToolCall) -> ToolResult:
        tool = self.registry.get(call.name)
        if tool is None:
            return fail(f"There's no tool called '{call.name}'.")
        try:
            args = tool.coerce_args(call.arguments)
        except ArgumentError as exc:
            return fail(f"Bad input for {tool.name}: {exc}")
        if tool.risk is Risk.CONFIRM:
            request = ConfirmRequest(
                tool=tool.name,
                title=tool.name.replace("_", " ").capitalize() + "?",
                preview=tool.describe_call(args),
                args=dict(args),
                editable=tool.editable,
                confirm_label=tool.confirm_label,
            )
            self.on_status("Waiting for your OK…")
            decision = self.confirmer.confirm(request)
            if not decision.approved:
                return ToolResult(False, "Cancelled.", cancelled=True)
            if decision.args:
                try:
                    args = tool.coerce_args({**args, **decision.args})
                except ArgumentError as exc:
                    return fail(f"Bad input for {tool.name}: {exc}")
        self.on_status(f"Running {tool.name.replace('_', ' ')}…")
        try:
            return tool.run(args)
        except Exception as exc:  # a broken tool must not crash the app
            log.exception("Tool %s failed", tool.name)
            return fail(f"{tool.name.replace('_', ' ')} failed: {exc}")

    def _remember(self, text: str, reply: AgentReply) -> None:
        if not reply.text:
            return
        summary = reply.text
        if reply.steps and not reply.used_model:
            summary = f"[{reply.steps[0].tool}] {reply.text}"
        self.history += [{"role": "user", "content": text}, {"role": "assistant", "content": summary}]
        keep = self.history_turns * 2
        if len(self.history) > keep:
            self.history = self.history[-keep:]
