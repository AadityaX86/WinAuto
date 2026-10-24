# Contributing

Thanks for helping. This page covers the conventions; the [development guide](docs/development.md) covers setup, and [Adding a skill](docs/adding-a-skill.md) walks through building a feature.

## Before you start

- For anything bigger than a fix, open an issue first to agree on the approach.
- Read [Architecture](docs/architecture.md). The layer rules are enforced by tests, so it's quicker to know them up front.

## Conventions

**Code**
- Python 3.11+, type hints on public functions, `from __future__ import annotations` at the top of modules.
- Features are skills in `winauto/skills/`. Anything that touches Windows, the network, the database driver or another program goes in `winauto/adapters/` and is injected so tests can fake it.
- The UI talks only to `core` types and `winauto/services/`.
- Keep functions small and names plain. Comments explain *why*, not what.
- `python -m ruff check .` must pass (unused imports, undefined names, import order).

**Behaviour**
- Anything that sends, deletes, runs commands or changes things outside WinAuto uses `risk=Risk.CONFIRM`.
- Messages to users are short, plain sentences: say what happened and what to do next. No jargon, no exclamation marks unless it's good news.
- Nothing leaves the PC unless the user asked for it. New online services must be free, keyless and listed in [Privacy](docs/privacy.md).
- Settings get sensible defaults; a missing setting must never break anything.

**Tests**
- Every tool gets a test, including its failure messages. Use the `ctx` fixture and fakes from `tests/fakes.py`.
- Windows-only behaviour gets a fake-backend test everywhere plus, where possible, a live check in `tests/test_windows_live.py` (runs on Windows CI).

**Docs**
- New or changed tools: run `python scripts/gen_skill_reference.py` (tests fail if `docs/skills.md` is stale).
- User-visible changes: update the [user guide](docs/user-guide.md) and add a line under "Unreleased" in [CHANGELOG.md](CHANGELOG.md).

## Commits and pull requests

- One logical change per commit, with a message that says what changed and why ("Add water tracker skill", not "updates").
- Pull requests describe what changed for the user and how it was tested. Screenshots for UI changes.

### Checklist

- [ ] `python -m pytest` passes
- [ ] `python -m ruff check .` passes
- [ ] New tools have tests, and risky ones use `Risk.CONFIRM`
- [ ] `docs/skills.md` regenerated if tools changed
- [ ] User guide and changelog updated for user-visible changes
- [ ] CI is green, including the Windows build and self-test
