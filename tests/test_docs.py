"""Keeps the documentation honest: generated reference up to date, links valid, guide code working."""

from __future__ import annotations

import importlib.util
import re
import sys
from datetime import date
from pathlib import Path

import pytest
from fakes import RecordingConfirmer

ROOT = Path(__file__).resolve().parents[1]
DOCS = [ROOT / "README.md", ROOT / "CONTRIBUTING.md", ROOT / "CHANGELOG.md", *sorted((ROOT / "docs").glob("*.md"))]


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def test_skill_reference_is_up_to_date():
    gen = _load(ROOT / "scripts" / "gen_skill_reference.py", "gen_skill_reference")
    current = (ROOT / "docs" / "skills.md").read_text(encoding="utf-8")
    assert current == gen.render(), "docs/skills.md is stale: run  python scripts/gen_skill_reference.py"


@pytest.mark.parametrize("doc", DOCS, ids=lambda p: str(p.relative_to(ROOT)))
def test_relative_links_exist(doc):
    text = doc.read_text(encoding="utf-8")
    text = re.sub(r"```.*?```", "", text, flags=re.S)  # ignore code blocks
    broken = []
    for target in re.findall(r"\]\(([^)\s]+)\)", text):
        if re.match(r"[a-z]+:", target) or target.startswith("#"):
            continue  # web links and same-page anchors
        path = (doc.parent / target.split("#")[0]).resolve()
        if not path.exists():
            broken.append(target)
    assert not broken, f"{doc.name} links to missing files: {broken}"


def test_adding_a_skill_example_works(ctx):
    from winauto.core.agent import Agent
    from winauto.core.quick import QuickMatcher
    from winauto.core.registry import Registry

    water = _load(ROOT / "docs" / "examples" / "water.py", "water_example")
    skill = water.WaterSkill(ctx, today=lambda: date(2026, 10, 24))
    registry = Registry()
    registry.add(skill)
    confirmer = RecordingConfirmer()
    agent = Agent(registry, None, confirmer, quick=QuickMatcher(registry))

    assert agent.handle("drank 2 glasses of water").text == "💧 2 of 8 glasses today."
    assert agent.handle("had water").text == "💧 3 of 8 glasses today."
    assert agent.handle("how much water today").text == "💧 3 glasses today, 5 to go."
    assert skill.widgets()[0].text == "3/8 glasses"
    assert skill.suggest("wat")[0].tool == "log_water"
    assert not skill.log_water(50).ok
    reset = agent.run_tool(type("Call", (), {"name": "reset_water", "arguments": {}})())
    assert reset.ok and confirmer.requests[0].tool == "reset_water"
    assert skill.count() == 0
    names = {t["function"]["name"] for t in registry.schemas()}
    assert names == {"log_water", "water_today", "reset_water"}
