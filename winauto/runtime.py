"""The engine's composition root: builds config, database, skills, AI client and agent, and wires them.

It also implements the `Assistant` port (winauto.core.context) that skills use to
reach the engine, so skills never import this module.
"""

from __future__ import annotations

import logging
from typing import Callable

from winauto.adapters.llm import make_client
from winauto.adapters.storage.db import Database
from winauto.config import Config, load_config, save_config
from winauto.core.agent import Agent, Confirmer
from winauto.core.context import Context
from winauto.core.launcher import Launcher
from winauto.core.llm import LLMClient, ToolCall
from winauto.core.quick import QuickMatcher
from winauto.core.skill import ToolResult
from winauto.paths import data_dir, db_path
from winauto.services.home import HomeService
from winauto.services.voice import VoiceService
from winauto.services.writing import WritingTools
from winauto.skills import build_registry

log = logging.getLogger(__name__)


class Runtime:
    def __init__(
        self,
        confirmer: Confirmer,
        config: Config | None = None,
        notify: Callable[[str, str], None] | None = None,
        on_status: Callable[[str], None] | None = None,
        db: Database | None = None,
        llm: LLMClient | None = None,
    ):
        self.config = config or load_config()
        self.db = db or Database(db_path())
        self.ctx = Context(config=self.config, db=self.db, data_dir=data_dir())
        if notify:
            self.ctx.notify = notify
        self.registry = build_registry(self.ctx)
        self.ctx.skills = {s.name: s for s in self.registry.skills}
        self.llm = llm or make_client(self.config.llm)
        self.agent = Agent(
            self.registry,
            self.llm,
            confirmer,
            quick=QuickMatcher(self.registry) if self.config.use_quick_commands else None,
            history_turns=self.config.history_turns,
            max_steps=self.config.max_steps,
            user_name=self.config.user_name,
            on_status=on_status,
        )
        self._matcher = QuickMatcher(self.registry)
        self.launcher = Launcher(self.registry, self._matcher)
        self.ctx.assistant = self
        # Application services for the UI (winauto/services).
        self.home = HomeService(self.ctx, self.registry)
        self.writing = WritingTools(self.ctx)
        self.voice = VoiceService(self.ctx)

    # ----- Assistant port (used by skills through ctx.assistant) -----

    def match_command(self, text: str) -> ToolCall | None:
        return self._matcher.match(text)

    def run_tool(self, call: ToolCall) -> ToolResult:
        return self.agent.run_tool(call)

    def complete(self, system: str, user: str, images: list[str] | None = None,
                 model: str | None = None, stream: bool = False) -> str:
        """One-off question to the model, without tools. Streams to the popup if asked."""
        message: dict = {"role": "user", "content": user}
        if images:
            message["images"] = images
        on_token = self.agent.on_token if stream else None
        if on_token:
            on_token("")
        reply = self.llm.chat([{"role": "system", "content": system}, message], [], on_token=on_token, model=model)
        return reply.content

    def start(self) -> None:
        for skill in self.registry.skills:
            try:
                skill.start()
            except Exception:
                log.exception("Skill %s failed to start", skill.name)

    def stop(self) -> None:
        for skill in self.registry.skills:
            try:
                skill.stop()
            except Exception:
                log.exception("Skill %s failed to stop", skill.name)
        self.db.close()

    def apply_config(self, cfg: Config) -> None:
        """Save new settings and use them right away."""
        save_config(cfg)
        self.config = cfg
        self.ctx.config = cfg
        self.llm = make_client(cfg.llm)
        self.agent.llm = self.llm
        self.agent.quick = QuickMatcher(self.registry) if cfg.use_quick_commands else None
        self.agent.history_turns = cfg.history_turns
        self.agent.max_steps = cfg.max_steps
        self.agent.user_name = cfg.user_name
