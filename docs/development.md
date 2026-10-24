# Development guide

How to set up, run, test and package WinAuto from source.

## Set up

You need Python 3.11 or newer (3.12 is what CI and the packaged app use) and Git.

**Windows** (PowerShell or Command Prompt):

```
git clone https://github.com/AadityaX86/WinAuto
cd WinAuto
py -3.12 -m venv .venv
.venv\Scripts\activate
pip install -e ".[dev]"
```

**Linux or macOS** (for working on everything except the Windows-only parts):

```
python3.12 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

On a Linux machine without a desktop, Qt needs a few system libraries (`libegl1 libgl1 libxkbcommon0 libfontconfig1 libdbus-1-3`) and `QT_QPA_PLATFORM=offscreen`.

## Run it

| Command | What it does |
|---|---|
| `python -m winauto` | The desktop app (tray icon, hotkeys, popup). |
| `python -m winauto --background` | Starts hidden in the tray (what "Start with Windows" uses). |
| `python -m winauto --cli` | Chat in the terminal, with approvals as y/N prompts. Quickest way to try a skill. |
| `python -m winauto --selftest` | Checks skills, database, Windows APIs, Credential Manager and the popup, and writes a report. |

Set `WINAUTO_HOME` to a scratch folder to keep your real notes and settings out of the way:

```
set WINAUTO_HOME=%TEMP%\winauto-dev        (Windows)
export WINAUTO_HOME=/tmp/winauto-dev       (Linux/macOS)
```

Logs go to `<data folder>\logs\winauto.log`. Most problems show up there first.

## Test

```
python -m pytest              # whole suite, about 10 seconds
python -m pytest tests/test_notes.py -k todo
python -m ruff check .        # lint: unused imports, undefined names, import order
python -m ruff check . --fix  # fix what it can
```

What the suite covers:

| Tests | What |
|---|---|
| `test_core.py`, `test_timeparse.py` | Agent loop, approvals, tool schemas, quick commands, LLM parsing, time parsing, settings |
| `test_apps.py` … `test_productivity.py` | Each skill, with fake backends |
| `test_launcher.py` | Live results ranking |
| `test_ui.py` | The real Qt popup, controller and settings, run offscreen |
| `test_services.py` | Home screen, history, writing tools, voice, settings checks, context ports |
| `test_windows_live.py` | Real Windows API calls (skipped elsewhere; runs on Windows CI) |
| `test_local_ai.py` | Built-in AI: downloads, install, engine start and CPU fallback, first-run setup (with fakes) |
| `test_engine_live.py` | The real engine and a small model, end to end (only with `WINAUTO_ENGINE_TEST=1`; downloads about 700 MB) |
| `test_architecture.py` | Layer rules and skill registration (see [Architecture](architecture.md)) |
| `test_docs.py` | The skills reference is current, doc links work, the guide's example skill runs |

Fakes live in `tests/fakes.py`: `ScriptedLLM` replays model replies and tool calls; `RecordingConfirmer` approves or denies cards and records them. The `ctx` fixture in `tests/conftest.py` gives a `Context` with an in-memory database.

### Testing with a real model

With Ollama running, `python -m winauto --cli` uses your configured model. Useful requests to try after changing the agent or prompts: a quick command ("volume 30"), a tool the model must pick ("remind me to call mom when I get home at 6"), a follow-up ("actually make it 7"), something risky ("email Ram that I'm late"), and plain chat ("tell me a joke").

## Keep the docs current

- `docs/skills.md` is generated: run `python scripts/gen_skill_reference.py` after adding or changing a tool. The tests fail if you forget.
- User-facing changes go in [the user guide](user-guide.md) and [CHANGELOG.md](../CHANGELOG.md).
- Screenshots in `docs/images/` come from the real widgets rendered offscreen. Re-take them if the UI changes noticeably.

## Build the Windows app

CI does this on every push. To build locally on Windows:

```
pip install ".[dev]"            # not -e: PyInstaller can't follow editable installs
python packaging/make_icon.py
pyinstaller --noconfirm --clean --windowed --name WinAuto --icon packaging/winauto.ico ^
  --paths . --collect-submodules winauto --collect-submodules keyring --collect-submodules win32ctypes ^
  --hidden-import pycaw.pycaw --hidden-import comtypes.stream packaging/launcher.py
dist\WinAuto\WinAuto.exe --selftest
```

`packaging/launcher.py` is the exe's entry point. If the app crashes before logging starts, it writes `%TEMP%\winauto-crash.txt` instead of showing a dialog (a dialog would hang CI).

## Continuous integration

`.github/workflows/ci.yml` runs on every push and pull request:

1. **Tests** on Ubuntu (with lint) and Windows, and **Built-in AI**: the real llama.cpp engine and a small model downloaded (cached between runs), started, and asked to call a tool, on Windows and Linux.
2. **Build WinAuto.exe** on Windows, then run the packaged app's `--selftest` (it must finish within 3 minutes and report OK).
3. **Upload** the `WinAuto-windows` artifact (kept 30 days).

A newer push to the same branch cancels the older run. Packaging and the self-test live in one place, `.github/actions/build-exe/action.yml`, used by both CI and releases.

## Releasing

1. Update the version in `pyproject.toml` and `winauto/__init__.py`, and move the "Unreleased" notes in `CHANGELOG.md` under a new `## <version> (<date>)` heading. `tests/test_docs.py` checks that these agree.
2. Merge to `main` and wait for CI to go green.
3. On GitHub: **Actions → Release → Run workflow**, enter the version (e.g. `0.2.0`) and run it. Pushing a tag like `v0.2.0` does the same.

`.github/workflows/release.yml` then:
- checks the version against `pyproject.toml`, `winauto/__init__.py` and `CHANGELOG.md`;
- runs the tests on Windows;
- builds the app folder and a single-file exe, self-testing each;
- publishes release `v<version>` with `WinAuto-<version>-windows.zip`, `WinAuto-<version>.exe` and `SHA256SUMS.txt`.

The release notes come from that version's `CHANGELOG.md` section plus download instructions (`scripts/release_notes.py`; run it locally to preview).

## Project layout

```
winauto/
  __main__.py        entry point (app, --cli or --selftest)
  app.py             desktop composition root: Qt app, tray, hotkeys, popup, settings
  runtime.py         engine composition root: config, database, skills, AI client, agent, services
  cli.py, selftest.py
  config.py, paths.py, log.py
  core/              engine and contracts (no Qt, no Windows, no I/O)
  skills/            features, one module each; skills/shared/ for common helpers
  services/          what the UI asks of the app
  adapters/          Windows APIs, SQLite, HTTP, AI servers, Gmail, Credential Manager, system info
  ui/                Qt popup, views, settings, tray, theme, icons
tests/               pytest suite (fakes.py, conftest.py)
docs/                user and developer documentation; examples/ has runnable guide code
scripts/             developer scripts (skills reference generator)
packaging/           PyInstaller entry point and icon
```
