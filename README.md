# WinAuto

A private assistant and launcher for your Windows PC. Press **Ctrl+Alt+Space** and start typing: apps, settings and commands appear as you type, like Raycast or PowerToys Run. Or ask anything in plain English and it gets done: it opens apps, writes your emails and messages, keeps your todos and notes, reads your calendar, controls your PC, and more.

The AI runs **on your own PC** (via [Ollama](https://ollama.com)), so your requests don't go to anyone's cloud. Everyday commands like `open spotify` or `volume 30` don't even need the AI; they run instantly.

| Launcher | Results as you type |
|---|---|
| ![Home screen](docs/images/home.png) | ![Live results](docs/images/results.png) |
| **Writing tools on any selected text** | **Chat, with approval before anything is sent** |
| ![Writing tools](docs/images/writing-tools.png) | ![Chat](docs/images/chat.png) |

## What it does

| | Try |
|---|---|
| Apps and windows | `open spotify` · `close chrome` · `snap chrome left` · `take a screenshot` |
| Todos, notes, reminders | `todo call mom tomorrow 6pm` · `remind me to stretch in 20 minutes` · `pasta timer 8 min` |
| Email and messages | `email Ram that the meeting moved to 3pm` · `whatsapp mom: reached home` · `discord didi: on tonight?` |
| Calendar and your day | `what's my next meeting` · `good morning` (daily briefing) · `focus for 50 minutes` |
| Web and answers | `who won the match yesterday?` · `what's the weather` · `100 usd to npr` · `define serendipity` |
| Writing tools | select text in any app, press **Ctrl+Alt+T**: fix grammar, rewrite, summarize, translate, reply |
| Your screen | `what's on my screen?` · `explain this error` · `read the text on my screen` |
| PC controls | `volume 30` · `dark mode on` · `turn off bluetooth` · `shut down in 30 minutes` · `battery` |
| Files and clipboard | `find my resume pdf` · `organize my downloads` · `clipboard history` |
| Your shortcuts | quick links, text snippets, routines (`work mode` opens your apps and sets the volume) |

Anything that sends, deletes or shuts down shows an approval card first, and drafts can be edited before sending. See the [user guide](docs/user-guide.md) for everything, or the [skills reference](docs/skills.md) for all 122 tools.

## Get started

1. Install [Ollama](https://ollama.com/download) and run `ollama pull qwen3:8b` (6–8 GB graphics card; [other sizes](docs/ai-models.md)).
2. Download the **[latest release](https://github.com/AadityaX86/WinAuto/releases/latest)**: the zip (unzip, then run `WinAuto.exe`) or the single `WinAuto-<version>.exe`. Or run from source: `pip install -e .` then `python -m winauto`.
3. Press **Ctrl+Alt+Space**.

Full steps: [Getting started](docs/getting-started.md). Gmail, WhatsApp, Discord and calendar: [Connect your accounts](docs/connect-accounts.md).

## Documentation

- [Getting started](docs/getting-started.md) · [User guide](docs/user-guide.md) · [Connect your accounts](docs/connect-accounts.md) · [AI models](docs/ai-models.md)
- [Settings reference](docs/configuration.md) · [Troubleshooting](docs/troubleshooting.md) · [Privacy and security](docs/privacy.md)
- For developers: [Architecture](docs/architecture.md) · [Adding a skill](docs/adding-a-skill.md) · [Development guide](docs/development.md) · [Contributing](CONTRIBUTING.md) · [Changelog](CHANGELOG.md)

## Privacy in one paragraph

Your requests, notes, todos, contacts and history stay in `%APPDATA%\WinAuto` on your PC, and the AI runs locally. WinAuto only goes online when you ask for something online (a web search, the weather, exchange rates, email), and only sends the words you looked up. Your Gmail app password is kept in Windows Credential Manager. Details: [Privacy and security](docs/privacy.md).

## For developers

```
pip install -e ".[dev]"
python -m pytest              # about 450 tests, ~10 s (set QT_QPA_PLATFORM=offscreen on a headless machine)
python -m ruff check .
python -m winauto --cli       # chat in the terminal
```

Features are **skills**: one file in `winauto/skills/`, where each `@tool` method becomes something the AI can do. The engine (`core/`), features (`skills/`), outside-world code (`adapters/`), app services (`services/`) and the Qt UI (`ui/`) are separate layers, and `tests/test_architecture.py` keeps them that way. Start with [Architecture](docs/architecture.md) and [Adding a skill](docs/adding-a-skill.md).
