# Architecture

WinAuto is built so that a new feature is one new file, the AI model and Windows can be swapped out in tests, and the rules that keep it that way are checked automatically.

## The layers

```
   app.py · runtime.py · cli.py · selftest.py      composition roots: build everything,
                       │                            plug adapters into the core's ports
                       ▼
   ui/ ──────────► services/ ──────────┐
    │                  │               │
    │                  ▼               ▼
    └────────────►   core/   ◄───── adapters/     Windows · SQLite · HTTP · AI servers
                       ▲               ▲          Gmail · Credential Manager · psutil
                       │               │
                       └── skills/ ────┘
```

Arrows point the way imports go. `core/` is in the middle and imports nothing but the settings model. Everything else depends on it, never the other way round.

| Package | What lives there | May import |
|---|---|---|
| `winauto/core/` | The engine and the contracts: `Skill`, `@tool`, `ToolResult`, `Suggestion`, `QuickRule`, `Widget`, the agent loop, tool registry, launcher ranking, quick-command matching, fuzzy matching, time parsing, and the **ports** (`Context`, `Store`, `Assistant`, `Host`, `LLMClient`). Plain Python. | `config` |
| `winauto/skills/` | Features. One module per skill (apps, notes, email…). Code more than one skill needs lives in `skills/shared/`. | `core`, `config`, `adapters`, `skills.shared` |
| `winauto/adapters/` | Everything that talks to the outside world: `winos/` (Windows APIs via ctypes, registry, PowerShell, SendInput), `storage/` (SQLite and migrations), `llm/` (built-in, Ollama and OpenAI-compatible clients), `local_ai/` (the built-in AI: pinned downloads, the llama.cpp server process), `http.py`, `gmail.py`, `secrets.py` (Credential Manager), `sysinfo.py` (psutil, sockets). | `core`, `config`, `paths`, `log` |
| `winauto/services/` | Application logic the UI needs: the home screen (`home.py`), command history, writing tools, voice, setting up the built-in AI (`ai_setup.py`), and the checks behind Settings. | `core`, `config`, `adapters`, `paths` |
| `winauto/ui/` | Qt windows and widgets: the popup and its views (`popup.py`, `chat.py`, `home.py`, `cards.py`, `textmode.py`), Settings, tray, theme and icons, and the `Controller` that connects the popup to the app. | `core`, `config`, `services` |
| `config.py`, `paths.py`, `log.py` | Settings model (dataclasses, saved as JSON), file locations, logging. | each other |
| `runtime.py`, `app.py`, `cli.py`, `selftest.py` | **Composition roots.** They build the objects and plug adapters into ports. Nothing imports them. | anything |

### Rules, enforced by tests

`tests/test_architecture.py` reads every module's imports (including ones inside functions) and fails if:

- a layer imports something outside its "May import" column above;
- `core/`, `skills/` or `services/` use the outside world directly (`ctypes`, `winreg`, `subprocess`, `sqlite3`, `smtplib`, `imaplib`, `socket`, `webbrowser`, `urllib.request`, `keyring`, `psutil`, `pycaw`, `send2trash`, `PySide6`…). Wrap it in an adapter instead;
- a skill module imports another skill module (use `skills/shared/` or `ctx.skill(name)`);
- a skill calls `os.startfile` (use `adapters.winos.shell`);
- a `Skill` subclass isn't registered in `skills/__init__.py`, has no description, or uses an icon that doesn't exist;
- two tools share a name.

`tests/test_docs.py` fails when [the skills reference](skills.md) is out of date, a doc links to a missing file, or the example in [Adding a skill](adding-a-skill.md) stops working.

## How a request flows

```
Ctrl+Alt+Space (adapters/winos/hotkey.py, its own thread)
  └─► app.py remembers the window you were in (ctx.host.last_window), shows the popup
        └─► you type ─► ui/controller.py ─► runtime.launcher.search()  (every skill's suggest(), 35 ms debounce)
              └─► Enter on a result ─► agent.run_tool(call)
              └─► Enter on a sentence ─► agent.handle(text)          (worker thread)
                    1. QuickMatcher: does a QuickRule match? ──► run that tool, done (no AI)
                    2. else pick the skills whose `keywords` match (or ask the model to pick groups)
                    3. LLM chat with those tools ──► model asks for tool calls
                    4. Agent.run_tool(): coerce arguments ─► Risk.CONFIRM? ─► Confirmer shows a card and waits
                    5. tool runs ─► ToolResult back to the model ─► repeat (max_steps) or answer
              ◄── AgentReply (text + steps) via a Qt signal ─► chat bubble, action chips, maybe auto-hide
```

### Threads

- The **UI thread** owns every widget. Other threads talk to it only through Qt signals (`Controller.reply_ready`, `token`, `home_data`; `QtConfirmer.requested`; `ctx.host.show_popup` / `hide_popup` emit signals too).
- **Agent work** runs on a short-lived worker thread per request, one at a time (`Controller._agent_lock`). Stop and New chat bump a generation counter so late replies are dropped.
- **Approval cards** block the worker thread on a `threading.Event` until you press a button; the card lives on the UI thread.
- **Skills** may start their own background threads in `start()` (reminders, focus) and must stop them in `stop()`.
- **Hotkeys** listen on their own Win32 message-loop thread.

## The skill contract

A skill is a class in `winauto/skills/<name>.py`, listed in `BUILTIN` in `winauto/skills/__init__.py`:

| Part | Purpose |
|---|---|
| `name`, `icon`, `description` | Identity. The description is shown to the model (tool routing) and in Settings. |
| `keywords` | Regex. When a request matches, this skill's tools are offered to the model. Keeps local models fast. |
| `always` | Offer these tools for every request (web search, maths). |
| `prompt_hint` | One line added to the system prompt when the skill's tools are offered. |
| `@tool` methods | Abilities. The signature becomes the JSON schema the model sees. Options: `risk=Risk.CONFIRM`, `editable=(...)`, `confirm_label`, `final`, `hides_popup`, `name`. |
| `quick_rules()` | Regexes for instant commands that skip the AI. Lower `priority` wins across skills. |
| `suggest(query)` | Live launcher results while typing. Must be fast. |
| `widgets()` | Cards on the home screen. Runs off the UI thread. |
| `prompt_context()` | Text added to every request (memory uses this for facts about you). |
| `preview(tool, args)` | Friendly text for approval cards. |
| `start()` / `stop()` | Background work. |

Tools return `ok(message, data)` or `fail(message, fallback=False)`. `message` is shown to the user and the model; `data` is extra detail for the model and can carry `"actions"` (buttons under the reply, each running a tool).

### What a skill gets: the `Context`

Skills never import the UI, the runtime or each other. Everything comes in through `self.ctx` (`winauto/core/context.py`):

| Port | Is | Filled in by |
|---|---|---|
| `ctx.config` | The user's settings (`winauto/config.py`) | runtime |
| `ctx.db` | `Store`: `execute`, `query`, `one`, `get_value`, `set_value` | runtime (SQLite) / tests (in-memory) |
| `ctx.data_dir` | Folder for the skill's own files | runtime |
| `ctx.notify(title, message)` | Desktop notification | app (tray balloon) |
| `ctx.host` | `Host`: `hide()`, `show()`, `last_window`, `selection` | app (popup signals); headless defaults otherwise |
| `ctx.assistant` | `Assistant`: `complete()` (ask the model, optionally with images), `run_tool()`, `match_command()` | runtime; `None` in unit tests |
| `ctx.skill(name)` | Another loaded skill, or `None` if it's turned off | runtime |

Because these are ports, a test builds a `Context` with an in-memory database and fakes, and the same skill runs in the desktop app, the terminal (`--cli`) and the self-test.

## Choosing tools for the model

Local models get slower and less accurate with many tools. For each request the agent:

1. offers the skills whose `keywords` match this message or the previous one (for follow-ups like "send it"), plus `always` skills;
2. if nothing matches and all tool definitions together are bigger than about 2,500 tokens, asks the model in a quick tool-free call which skill groups are needed (`ROUTER_PROMPT` in `core/agent.py`);
3. otherwise offers everything.

Small models sometimes write tool calls as text instead of using the API; `core/llm.py` recognises those (`extract_text_tool_calls`) and `TokenGate` keeps them out of the streamed answer.

## The built-in AI

WinAuto ships without a model and gets one on first run, so users install nothing else:

```
app.py ──► AISetup (services/ai_setup.py) ── picks a model for the GPU, runs the download thread,
              │                                turns status into a SetupView for the popup card
              ▼
           LocalAI (adapters/local_ai/manager.py) ── engine + model files in %LOCALAPPDATA%\WinAuto\ai
              │   catalog.py   pinned URLs, sizes, SHA-256 (llama.cpp build, Qwen3-VL GGUF files)
              │   download.py  resumable, verified downloads
              │   server.py    llama-server on 127.0.0.1, random API key, GPU via --fit, CPU fallback
              ▼
           BuiltinClient (adapters/llm/builtin.py) ── the agent's LLMClient; starts the engine when needed
```

- `Runtime` owns the `LocalAI` and stops it on quit; `adapters/winos/jobs.py` puts the engine in a Windows Job Object so it can't outlive WinAuto.
- Status flows one way: `LocalAI` → listeners → `AISetup.view()` → `Controller.setup_status` (Qt signal) → `ui/setup.py`. The UI never sees engine states, only the view.
- `tests/test_local_ai.py` covers downloads, installs and the setup flow with fakes. `tests/test_engine_live.py` (CI only) downloads the real engine and a tiny model and makes a real tool call on Windows and Linux.

## Storage

One SQLite file (`%APPDATA%\WinAuto\winauto.db`). The schema is versioned with `PRAGMA user_version`; `MIGRATIONS` in `adapters/storage/db.py` is an append-only list. To add a table, append a new migration. Never edit an old one. Small values and caches go in the `kv` table through `ctx.db.get_value` / `set_value`.

Settings are JSON (`config.json`). Unknown keys are ignored and missing ones get defaults, so adding a setting is adding a dataclass field. Secrets (the Gmail app password) go to Windows Credential Manager through `adapters/secrets.py`, never into `config.json`.

## Adapters and testing

Platform code sits behind small classes or functions with the same shape everywhere: the skill takes an optional backend in its constructor and defaults to the real one, so tests pass a fake:

```python
class WhatsAppSkill(Skill):
    def __init__(self, ctx: Context, backend=None):
        super().__init__(ctx)
        self.backend = backend or WhatsAppDesktop()   # adapters/winos/whatsapp.py
```

On anything but Windows, `adapters/winos` functions raise `NotOnWindows`, which skills turn into a friendly message. The test suite runs on Linux and Windows in CI; `tests/test_windows_live.py` exercises the real Windows calls there, and the packaged `.exe` runs `--selftest` before it's uploaded.

## The UI

- `ui/controller.py` connects the popup to the runtime: debounced launcher search, running results and requests on worker threads, approval cards, streaming tokens, auto-hide after actions that open something.
- `ui/popup.py` is the window (search box, stacked views, footer, keys, animation). Views: `home.py`, `chat.py`, `cards.py` (approval cards), `textmode.py` (writing tools); shared helpers in `parts.py`; list and toggle widgets in `widgets.py`.
- `ui/theme.py` holds the light and dark palettes and the stylesheet. `ui/icons.py` holds the line icons (SVG paths) and real app icons.
- The UI reaches the rest of the app only through the runtime's agent and launcher and the `services/` objects.

## Design decisions

- **Quick commands first.** Most everyday commands ("open spotify", "volume 30") are matched by regex and run instantly without the model. The AI is for everything else.
- **Approval for anything that sends, deletes or shuts down**, with editable drafts. The model can't skip it: the risk level belongs to the tool, not the prompt.
- **No unofficial APIs for personal accounts.** Discord and WhatsApp are driven like a person would (deep links, the app's own search, then Enter after approval), because automating personal accounts through their APIs breaks their terms.
- **Read-only calendar via iCal links** instead of OAuth apps: no sign-in, no tokens to store.
- **PowerShell for WinRT features** (media session, radios, speech), base64-encoded so quoting can't break.
