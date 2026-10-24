"""Keeps track of every loaded skill and tool."""

from __future__ import annotations

import logging
import re
from typing import Iterable

from winauto.core.skill import Skill, Tool

log = logging.getLogger(__name__)


class Registry:
    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}
        self._skills: dict[str, Skill] = {}

    def add(self, skill: Skill) -> None:
        self._skills[skill.name] = skill
        for t in skill.tools():
            if t.name in self._tools:
                log.warning("Tool %s from %s replaces one from %s", t.name, skill.name, self._tools[t.name].skill)
            self._tools[t.name] = t

    def extend(self, skills: Iterable[Skill]) -> None:
        for s in skills:
            self.add(s)

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def skill(self, name: str) -> Skill | None:
        return self._skills.get(name)

    @property
    def skills(self) -> list[Skill]:
        return list(self._skills.values())

    @property
    def tools(self) -> list[Tool]:
        return list(self._tools.values())

    def schemas(self, skills: Iterable[Skill] | None = None) -> list[dict]:
        if skills is None:
            return [t.schema() for t in self._tools.values()]
        names = {s.name for s in skills}
        return [t.schema() for t in self._tools.values() if t.skill in names]

    def select(self, *texts: str) -> list[Skill]:
        """Skills a request probably needs. Falls back to all of them when unsure."""
        joined = " ".join(t for t in texts if t)
        matched = [
            s for s in self._skills.values()
            if s.keywords and re.search(s.keywords, joined, re.I)
        ]
        if not matched:
            return list(self._skills.values())
        always = [s for s in self._skills.values() if s.always and s not in matched]
        return matched + always

    def prompt_hints(self, skills: Iterable[Skill] | None = None) -> str:
        chosen = list(skills) if skills is not None else list(self._skills.values())
        return "\n".join(f"- {s.prompt_hint}" for s in chosen if s.prompt_hint)
