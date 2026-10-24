"""Keeps the layers clean. If one of these fails, see docs/architecture.md.

    ui  ──►  services  ──►  core  ◄──  skills
                │            ▲           │
                └──► adapters ┘ ◄─────────┘

runtime.py, app.py, cli.py and selftest.py are the composition roots: they may
import anything, and nothing imports them.
"""

from __future__ import annotations

import ast
import importlib
import inspect
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1] / "winauto"

# Which winauto packages each layer may import (besides itself).
ALLOWED: dict[str, set[str]] = {
    "winauto.paths": set(),
    "winauto.log": {"winauto.paths"},
    "winauto.config": {"winauto.paths"},
    "winauto.core": {"winauto.config"},
    "winauto.adapters": {"winauto.core", "winauto.config", "winauto.paths", "winauto.log"},
    "winauto.skills.shared": {"winauto.core", "winauto.config"},
    "winauto.skills": {"winauto.core", "winauto.config", "winauto.adapters", "winauto.skills.shared"},
    "winauto.services": {"winauto.core", "winauto.config", "winauto.adapters", "winauto.paths"},
    "winauto.ui": {"winauto.core", "winauto.config", "winauto.services"},
}
COMPOSITION_ROOTS = {"winauto.runtime", "winauto.app", "winauto.cli", "winauto.selftest", "winauto.__main__"}

# Standard-library and third-party modules that only adapters (and the UI, for Qt) may use.
OUTSIDE_WORLD = {"ctypes", "winreg", "subprocess", "sqlite3", "smtplib", "imaplib", "socket", "webbrowser",
                 "urllib.request", "urllib.error", "http.client", "keyring", "psutil", "pycaw", "comtypes",
                 "send2trash", "PySide6"}
FORBIDDEN_OUTSIDE: dict[str, set[str]] = {
    "winauto.core": OUTSIDE_WORLD,
    "winauto.skills": OUTSIDE_WORLD,
    "winauto.services": OUTSIDE_WORLD,
}


def _modules() -> list[tuple[str, Path]]:
    out = []
    for path in sorted(ROOT.rglob("*.py")):
        parts = list(path.relative_to(ROOT.parent).with_suffix("").parts)
        if parts[-1] == "__init__":
            parts = parts[:-1]
        out.append((".".join(parts), path))
    return out


def _imports(module: str, path: Path) -> list[str]:
    """Every module imported anywhere in the file (including inside functions)."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    package = module if path.name == "__init__.py" else module.rsplit(".", 1)[0]
    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found += [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                base = package.split(".")
                base = base[: len(base) - (node.level - 1)]
                found.append(".".join(base + ([node.module] if node.module else [])))
            elif node.module:
                found.append(node.module)
    return found


def _layer(module: str) -> str | None:
    """The most specific layer a module belongs to."""
    best = None
    for layer in ALLOWED:
        if module == layer or module.startswith(layer + "."):
            if best is None or len(layer) > len(best):
                best = layer
    return best


def _within(name: str, prefix: str) -> bool:
    return name == prefix or name.startswith(prefix + ".")


MODULES = _modules()


@pytest.mark.parametrize("module, path", MODULES, ids=[m for m, _ in MODULES])
def test_layer_imports(module, path):
    layer = _layer(module)
    if module in COMPOSITION_ROOTS or layer is None:
        return
    allowed = ALLOWED[layer] | {layer}
    problems = []
    for name in _imports(module, path):
        if name in COMPOSITION_ROOTS or any(_within(name, r) for r in COMPOSITION_ROOTS):
            problems.append(f"imports composition root {name}")
            continue
        if _within(name, "winauto"):
            target = _layer(name)
            if name == "winauto" or target is None:
                continue  # the package root only holds constants (APP_NAME, __version__)
            if target not in allowed:
                problems.append(f"{layer} may not import {name}")
        for outer, banned in FORBIDDEN_OUTSIDE.items():
            if _within(module, outer) and any(_within(name, b) for b in banned):
                problems.append(f"{outer} may not use {name} directly (put it in winauto/adapters)")
    assert not problems, f"{module}: " + "; ".join(sorted(set(problems)))


SKILL_MODULES = [m for m, _ in MODULES if m.startswith("winauto.skills.") and not m.startswith("winauto.skills.shared")]


@pytest.mark.parametrize("module", SKILL_MODULES)
def test_skills_do_not_import_each_other(module):
    path = dict(MODULES)[module]
    others = [n for n in _imports(module, path)
              if _within(n, "winauto.skills") and not _within(n, "winauto.skills.shared") and n != "winauto.skills"]
    assert not others, f"{module} imports {others}; use winauto.skills.shared or ctx.skill(name) instead"


def test_skills_do_not_call_os_startfile():
    for module in SKILL_MODULES:
        source = dict(MODULES)[module].read_text(encoding="utf-8")
        assert "startfile" not in source, f"{module}: open things through winauto.adapters.winos.shell"


def test_every_skill_is_registered_and_described():
    from winauto.core.skill import Skill
    from winauto.skills import BUILTIN
    from winauto.ui.icons import PATHS

    registered = {(f"winauto.skills.{m}", c) for m, c in BUILTIN}
    names = set()
    for module in SKILL_MODULES:
        mod = importlib.import_module(module)
        for cls_name, cls in inspect.getmembers(mod, inspect.isclass):
            if not issubclass(cls, Skill) or cls is Skill or cls.__module__ != module:
                continue
            assert (module, cls_name) in registered, f"{module}.{cls_name} isn't listed in winauto/skills/__init__.py"
            assert cls.name not in names, f"two skills are called {cls.name!r}"
            names.add(cls.name)
            assert cls.description, f"{cls_name} needs a description (the model and Settings show it)"
            assert cls.icon in PATHS, f"{cls_name}.icon {cls.icon!r} isn't in winauto/ui/icons.py"
    assert len(names) == len(BUILTIN)


def test_tool_names_are_unique(ctx):
    from winauto.skills import build_registry

    registry = build_registry(ctx)
    seen: dict[str, str] = {}
    for tool in registry.tools:
        assert tool.name not in seen, f"{tool.name} is defined by both {seen[tool.name]} and {tool.skill}"
        seen[tool.name] = tool.skill
