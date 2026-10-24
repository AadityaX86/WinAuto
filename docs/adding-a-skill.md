# Adding a skill

A skill is one Python file that gives WinAuto new abilities. This guide builds a small one (counting glasses of water) and covers everything a real feature needs: tools for the AI, instant commands, launcher results, a home-screen card, storage, approval for risky actions, talking to Windows, and tests.

The finished example is [`docs/examples/water.py`](examples/water.py). `tests/test_docs.py` runs it, so the code below always works.

Read [Architecture](architecture.md) first if you want the big picture. You only need this page to add a feature.

## 1. Create the file

`winauto/skills/water.py`:

```python
from __future__ import annotations

from datetime import date
from typing import Callable

from winauto.core.context import Context
from winauto.core.skill import QuickRule, Risk, Skill, Suggestion, ToolResult, Widget, fail, ok, tool


class WaterSkill(Skill):
    name = "water"                      # unique, lower case
    icon = "target"                     # a name from winauto/ui/icons.py (PATHS)
    description = "Count glasses of water drunk today."   # shown to the model and in Settings
    keywords = r"\b(water|glass(?:es)?|hydrat\w*|drink)\b"  # when to offer these tools to the model
    prompt_hint = "Water: log_water adds glasses; water_today says how many so far."

    GOAL = 8

    def __init__(self, ctx: Context, today: Callable[[], date] = date.today):
        super().__init__(ctx)
        self.today = today              # injected so tests can pick the day
```

- `keywords` matters. Only skills whose keywords match a request (or the previous one) are offered to the model, which keeps small local models fast and accurate. Set `always = True` only for general tools like web search.
- Take anything that depends on time, the network or Windows as a constructor argument with a real default. Tests pass fakes.

## 2. Add tools

Each `@tool` method is an ability the AI can use. Its signature becomes the JSON schema the model sees:

```python
    def _key(self) -> str:
        return f"water:{self.today().isoformat()}"

    def count(self) -> int:
        return int(self.ctx.db.get_value(self._key()) or 0)

    @tool("Log glasses of water the user drank.", params={"glasses": "How many (default 1)"})
    def log_water(self, glasses: int = 1) -> ToolResult:
        if not 1 <= glasses <= 10:
            return fail("Log between 1 and 10 glasses at a time.")
        total = self.count() + glasses
        self.ctx.db.set_value(self._key(), str(total))
        return ok(f"💧 {total} of {self.GOAL} glasses today.", data={"today": total})

    @tool("How many glasses of water the user has had today.")
    def water_today(self) -> ToolResult:
        n = self.count()
        left = max(self.GOAL - n, 0)
        return ok(f"💧 {n} glasses today" + (f", {left} to go." if left else ". Goal reached!"))

    @tool("Reset today's water count to zero.", risk=Risk.CONFIRM, confirm_label="Reset")
    def reset_water(self) -> ToolResult:
        self.ctx.db.set_value(self._key(), "0")
        return ok("Water count reset.")
```

**Parameter types** the schema understands: `str`, `int`, `float`, `bool`, `list[str]` (and other lists), `Literal["a", "b"]` (becomes a choice list), and `X | None`. Parameters without a default are required. Describe each one in `params`. The model reads those descriptions.

**`@tool` options:**

| Option | Use it when |
|---|---|
| `risk=Risk.CONFIRM` | The tool sends, deletes, buys, shuts down or runs something. WinAuto shows an approval card first. The model can't skip it. |
| `editable=("body",)` | The user should be able to edit those arguments on the card (drafts). |
| `confirm_label="Send"` | The approve button's text. |
| `hides_popup=True` | The tool opens something on screen (an app, a website); the popup gets out of the way. |
| `final=False` | The result is raw data the model should turn into an answer. By default a successful result *is* the answer, which saves a slow second model call. |
| `name="..."` | The tool name should differ from the method name. |
| `title="Log {glasses} glasses"` | How the launcher names an instant command for this tool. `{arg}` is filled in, and arguments left at their default are dropped. It can also be a function of the arguments: `title=lambda a: "Mute" if a["mute"] else "Unmute"`. Without it the launcher shows "Log water: 2". |

Override `preview(tool_name, args)` to write a friendlier approval-card text.

**Results:** return `ok(message, data=None)` or `fail(message)`. The message is what the user sees, so write it as a short, plain sentence. To put buttons under the reply, add `data={"actions": [{"label": "Copy", "icon": "copy", "tool": "set_clipboard", "args": {"text": ...}}]}`.

For instant commands, `fail(..., fallback=True)` means "I couldn't find what you meant". The request then goes to the AI, which may understand it better (e.g. an app name with a typo).

## 3. Instant commands (optional)

Quick rules run without the AI, so they're instant and work offline. The regex must match the whole command (case doesn't matter; "please" and a trailing "?" are trimmed first):

```python
    def quick_rules(self) -> list[QuickRule]:
        return [
            QuickRule(r"(?:drank|had|log)\s+(?P<n>\d+)?\s*(?:glass(?:es)?\s+of\s+)?water",
                      lambda m: ("log_water", {"glasses": int(m["n"] or 1)})),
            QuickRule(r"how\s+much\s+water(?:\s+today)?", lambda m: ("water_today", {})),
        ]
```

- Return `None` from the handler to let the AI handle it after all.
- `priority` (default 50) orders rules across all skills; lower runs first. Use it when your pattern could steal another skill's commands (`open google` must open the website, not Google Chrome).
- Keep them narrow. Anything ambiguous should go to the model.

## 4. Launcher results (optional)

While the user types, every skill's `suggest()` is asked for results. It must be fast: no network calls and no slow disk scans.

```python
    def suggest(self, query: str) -> list[Suggestion]:
        if "water".startswith(query.strip().lower()) and len(query.strip()) >= 2:
            return [Suggestion("Log a glass of water", "log_water", {"glasses": 1},
                               subtitle=f"{self.count()} so far today", kind="Command", score=80)]
        return []
```

`score` (0–100) orders results across skills: about 90 for an exact match, 70–85 for a good guess, below 50 for fallbacks. Choosing a result runs the tool through the normal path, approval cards included.

A **fill-in** result doesn't run anything: it types the start of a command into the search box for the user to finish. Use one when your command needs details the user hasn't typed yet:

```python
from winauto.core.launcher import starts, template

    def suggest(self, query: str) -> list[Suggestion]:
        if starts(query, "drank water", "log water"):  # "dra", "log w", ...
            return [template("Log water…", "drank ", "Type how many glasses, e.g. 2", "water")]
        return []
```

## 5. A home-screen card (optional)

```python
    def widgets(self) -> list[Widget]:
        n = self.count()
        return [Widget(self.icon, f"{n}/{self.GOAL} glasses", order=60)] if n else []
```

Widgets are collected on a background thread, so a short network call is fine. Cache it (see `WebSkill.widgets` for the weather card). Return nothing when there's nothing useful to show.

## 6. Register it

Add a line to `BUILTIN` in `winauto/skills/__init__.py`:

```python
    ("water", "WaterSkill"),
```

Order matters a little: earlier skills get the first try at quick commands with the same priority. Users can turn your skill off in Settings → Skills.

## 7. Test it

Use the `ctx` fixture (an in-memory database and default settings) and fakes for anything external:

```python
from datetime import date

from fakes import RecordingConfirmer
from winauto.core.agent import Agent
from winauto.core.quick import QuickMatcher
from winauto.core.registry import Registry
from winauto.skills.water import WaterSkill


def test_water(ctx):
    skill = WaterSkill(ctx, today=lambda: date(2026, 10, 24))
    registry = Registry()
    registry.add(skill)
    agent = Agent(registry, None, RecordingConfirmer(), quick=QuickMatcher(registry))

    assert agent.handle("drank 2 glasses of water").text == "💧 2 of 8 glasses today."
    assert skill.widgets()[0].text == "2/8 glasses"
```

To test what the model does, use `ScriptedLLM` from `tests/fakes.py`: it replays tool calls and answers you give it.

Then run:

```
python -m pytest
python -m ruff check .
python scripts/gen_skill_reference.py     # updates docs/skills.md
```

`tests/test_architecture.py` checks that the skill is registered, described, has a real icon and doesn't reuse a tool name.

## Going further

### Storing more than a few values

`ctx.db.get_value` / `set_value` are for small values and caches. For real data, add a table: append a migration to `MIGRATIONS` in `winauto/adapters/storage/db.py` (never edit an existing one), then use `ctx.db.execute`, `query` and `one`:

```python
    """
    CREATE TABLE water_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        glasses INTEGER NOT NULL,
        logged_at TEXT NOT NULL
    );
    """,
```

Store times with `now_iso()` from `winauto.core.timeparse`. To understand "tomorrow 5pm" or "in 10 minutes", use `find_when`, `parse_when` and `parse_duration` from the same module.

### Talking to Windows, the network or another program

Skills don't call `ctypes`, `subprocess`, `winreg`, `socket` or similar directly (the architecture test enforces this). Instead:

1. Look in `winauto/adapters/` first: `winos/` has apps, windows, keyboard, clipboard, folders, media keys, screen capture, speech and opening links (`winos/shell.py`); `http.py` fetches web pages and JSON; `sysinfo.py` has battery, memory and network facts.
2. If what you need isn't there, add a small function or class to the right adapter module. On non-Windows systems, raise `NotOnWindows` (`require_windows("Feature name")`) and catch it in the skill to return a friendly `fail(...)`.
3. Take the adapter as a constructor argument with the real one as the default, so tests can pass a fake.

### Using the AI model, the popup or other skills

Through the context, never by importing:

| Need | Use |
|---|---|
| Ask the model something (rewrite text, describe an image) | `self.ctx.assistant.complete(system, user, images=[b64], stream=True)`. Check `self.ctx.assistant is None` first (unit tests, CLI without a model). |
| Run another tool, with its approval card | `self.ctx.assistant.run_tool(ToolCall("set_volume", {"level": 20}))` |
| Hide the popup before acting on the screen | `if self.ctx.host.hide(): time.sleep(0.4)` |
| The window the user was in / the selected text | `self.ctx.host.last_window`, `self.ctx.host.selection` |
| Another skill's data | `cal = self.ctx.skill("calendar")`, which may be `None` if it's turned off |
| A desktop notification | `self.ctx.notify("Title", "Message")` |
| Settings | `self.ctx.config` (add new ones as fields in `winauto/config.py` and controls in `ui/settings.py`) |

Code that several skills need (like the contact book) goes in `winauto/skills/shared/`.

### Background work

Start threads in `start()` and stop them in `stop()` (see `RemindersSkill` and `FocusSkill`). Use `self.ctx.notify` to tell the user something happened.

## Checklist

- [ ] `name`, `icon`, `description`, `keywords` set; tool descriptions and `params` written for the model
- [ ] Anything that sends, deletes or changes things outside WinAuto uses `risk=Risk.CONFIRM`
- [ ] Windows, network and other external calls go through `winauto/adapters/`, injectable for tests
- [ ] Registered in `BUILTIN`
- [ ] Tests for tools, quick commands and failure messages
- [ ] `python -m pytest` and `python -m ruff check .` pass
- [ ] `python scripts/gen_skill_reference.py` run; user-facing changes added to [the user guide](user-guide.md) and [CHANGELOG.md](../CHANGELOG.md)
