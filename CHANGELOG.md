# Changelog

All notable changes to WinAuto. Dates are when the change reached `main`.

## Unreleased

## 0.1.0 (2026-10-24)

The first version: a private assistant and launcher for Windows that runs on a local AI model.

### Launcher and interface
- **Ctrl+Alt+Space** opens a launcher. Results appear as you type: apps with their real icons, Settings pages, websites, files, calculations, emoji, colours, clipboard items, quick links and snippets.
- Home screen with a greeting, today's cards (todos due, next reminder or meeting, weather), suggestions and recent commands.
- Chat with answers that appear as they're written, step ticks, action buttons under replies, and a typing indicator.
- Approval cards for anything that sends, deletes, runs commands or shuts down, with editable drafts.
- Settings in a Windows 11 style: General, AI model, Accounts, Focus, Skills, About. Light and dark themes.
- Tray icon, start with Windows, single instance, voice typing button.

### Abilities (25 skills, 122 tools)
- **Apps and windows:** open, close, force close, switch, list; snap, maximize, side by side, show desktop; screenshots and snips.
- **Notes, todos, reminders, timers**, with plain-English dates ("tomorrow 6pm", "every weekday at 9").
- **Email (Gmail):** send, check, search, read, reply.
- **WhatsApp and Discord** messages through their desktop apps; a contact book with Google Contacts import.
- **Web:** open sites, search, answer from the web, read pages, weather.
- **Info:** live currency rates, dictionary, Wikipedia, news headlines, unit conversion, world clock, calculator.
- **Calendar** from Google, Outlook or iCloud private links, plus local events with reminders.
- **Daily briefing**, shown on your first open each morning.
- **Focus sessions** (Pomodoro) that keep distracting apps minimised.
- **Writing tools** for selected text in any app (**Ctrl+Alt+T**): fix, rewrite, shorten, summarize, translate, explain, reply.
- **Screen questions** with a local vision model; read text on screen; ask about image files.
- **Memory** of facts about you, used in every conversation.
- **PC controls:** volume, brightness, dark mode, Wi-Fi, Bluetooth, lock, sleep, restart, shutdown timers, battery and PC health, Recycle Bin, Settings pages.
- **Files:** open folders, find and open files, tidy Downloads, find what's taking up space.
- **Clipboard history, quick links, snippets, routines**, media controls and music, password generator, colour picker, network info, terminal commands, temp file cleanup, read aloud.

### Under the hood
- Instant offline commands for common requests; the AI handles the rest with only the relevant tools.
- Works with Ollama or any OpenAI-compatible local server.
- Clean architecture with typed ports between layers, enforced by tests ([Architecture](docs/architecture.md)).
- CI on Windows and Linux; every build packages `WinAuto.exe` and runs its self-test.
- Full documentation in [docs/](docs/README.md).
