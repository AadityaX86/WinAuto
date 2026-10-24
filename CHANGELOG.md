# Changelog

All notable changes to WinAuto. Dates are when the change reached `main`.

## Unreleased

## 0.2.1 (2026-10-24)

Fixes and polish from using WinAuto the way a new user would, on a real Windows PC with the built-in AI.

### Easier to start
- A **Welcome** card on the home screen replaces the long first-run chat message, which used to hide the AI download progress. It has **Start with Windows**, **Show examples** and **Got it**.
- A Windows notification says when the built-in AI has finished downloading.
- New **Help**: type `help`, `what can you do` or `help email` for examples. Works instantly, without the AI.
- **Fill-in results**: typing `rem`, `timer`, `todo`, `note`, `email`, `whatsapp`, `discord`, `search`, `volume` or `brightness` offers the start of the command ("Remind me to…") with an example, and puts it in the box for you to finish.

### Clearer results
- Instant commands say what will happen ("Set volume to 50%", "Shut down in 10 min", "Search YouTube for “lofi”") instead of repeating what you typed.
- No more duplicate rows: a result that does exactly what the instant command does takes its place, and sites with two names (WhatsApp / WhatsApp Web) show once.
- `google cats` and `search cats` search for "cats", ranked first.
- `volume`, `vol 50`, `vol up`, `brightness` show Volume up/down and Brightness up/down; `mail` and `inbox` show Check my email; `wifi` shows Wi-Fi on/off.
- Reminders no longer start with "to" ("call mom", not "to call mom").
- Home suggestions use plain words ("The AI looks at your screen and explains it", not "Ask the vision model").

### Popup
- Hides when you click another window (except while it's working or waiting for your approval). Turn this off in Settings → General.
- Opening it again a few minutes after a chat starts at the search box instead of the old conversation.
- Approval cards fit their text, and a new card scrolls so its title is in view.
- No approval card for something that can't work: if Gmail isn't set up yet, or a WhatsApp contact is unknown, WinAuto says so straight away (and keeps the email draft) instead of after you press Send.
- A shortcut already taken by another app now says where to change it, and that the tray icon still opens WinAuto.
- Settings records shortcuts by pressing them, instead of typing "ctrl+alt+space"; Backspace turns the writing-tools shortcut off.

### Under the hood
- `@tool(title=...)` names instant commands in the launcher; `core.launcher.template()` and `starts()` make fill-in results.
- `scripts/user_journey.py` and the **User journey** workflow walk through WinAuto on a real Windows machine with the built-in AI, and print every result.

## 0.2.0 (2026-10-24)

### Nothing else to install
- **Built-in AI.** WinAuto now runs its own AI engine (llama.cpp) with a Qwen3-VL model, so Ollama is no longer needed. Download WinAuto, run it, done.
- On first run WinAuto checks your graphics card and downloads the right model once: **Qwen3-VL 8B** (5.8 GB) for 8 GB cards and up, **Qwen3-VL 4B** (3.0 GB) otherwise. A card on the home screen shows progress, speed and time left, with Pause and Continue. Downloads resume after a restart and are checked against pinned checksums.
- One model does chat, tools and screenshots, so "what's on my screen?" works without a separate vision model.
- Uses NVIDIA, AMD and Intel graphics cards through Vulkan, and falls back to the processor when it has to. The engine listens only on this PC, with a random key, and stops with WinAuto (even after a crash).
- Settings → AI model: choose **Built-in (recommended)**, Ollama or an OpenAI-compatible server; switch between the standard and small model.
- Upgrading from 0.1: if Ollama is installed and running, WinAuto keeps using it; otherwise it switches to the built-in AI.

### Under the hood
- `adapters/local_ai` (pinned catalog, resumable verified downloads, engine process), `services/ai_setup.py` (first-run setup), `ui/setup.py` (progress card).
- CI downloads the real engine and a small model and makes a real tool call on Windows and Linux on every run.

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
- Releases on GitHub with the app as a zip and as a single-file exe, built and self-tested by a release workflow.
- Full documentation in [docs/](docs/README.md).
