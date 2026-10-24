# Settings reference

Most settings are in the **Settings** window (sliders button in the popup, or the tray menu). They're saved to `config.json` in your data folder; a few advanced ones live only in that file.

## Where WinAuto keeps things

| What | Where |
|---|---|
| Data folder | `%APPDATA%\WinAuto` (paste it into File Explorer's address bar), or **Settings → About → Open data folder** |
| Settings | `config.json` in the data folder |
| Notes, todos, contacts, reminders, routines, events, memories, history | `winauto.db` (SQLite) in the data folder |
| Logs | `logs\winauto.log` in the data folder (tray → **Open log file**), rotated at 1 MB, 3 kept |
| Gmail app password | Windows Credential Manager, entry `WinAuto` |
| Start with Windows | Registry: `HKCU\Software\Microsoft\Windows\CurrentVersion\Run`, value `WinAuto` |
| Crash report (if it can't start) | `%TEMP%\winauto-crash.txt` |

Set the environment variable `WINAUTO_HOME` to use a different data folder (handy for testing or keeping two profiles).

## Settings window

| Page | Setting | `config.json` key | Default |
|---|---|---|---|
| General | Your name | `user_name` | empty |
| | Appearance (Match Windows, Dark, Light) | `theme` | `system` |
| | Open WinAuto shortcut | `hotkey` | `ctrl+alt+space` |
| | Writing tools shortcut | `text_hotkey` | `ctrl+alt+t` |
| | Start with Windows | `start_with_windows` | off |
| | Instant commands | `use_quick_commands` | on |
| | Morning briefing | `morning_briefing` | on |
| | Read answers aloud | `speak_replies` | off |
| | Browser searches (google, bing, duckduckgo) | `search_engine` | `google` |
| | Play music with (youtube, spotify) | `music_service` | `youtube` |
| | Weather location (empty = guess from your connection) | `weather_location` | empty |
| AI model | Server (Ollama or OpenAI-compatible) | `llm.backend` | `ollama` |
| | Server address | `llm.base_url` | `http://localhost:11434` |
| | Chat model | `llm.model` | `qwen3:8b` |
| | Vision model | `llm.vision_model` | `qwen2.5vl:7b` |
| | Context size | `llm.num_ctx` | `8192` |
| | Stream answers | `llm.stream` | on |
| Accounts | Gmail address | `email.address` | empty |
| | App password | Credential Manager | |
| | Signature | `email.signature` | empty |
| | Your country code | `messaging.default_country_code` | empty |
| | Press Send in WhatsApp | `messaging.whatsapp_auto_send` | on |
| | Press Send in Discord | `messaging.discord_auto_send` | on |
| | Calendar links | `calendar_urls` | none |
| Focus | Apps to keep away | `focus_block_apps` | discord, steam, whatsapp, telegram |
| Skills | On/off per skill | `disabled_skills` | none (all on) |

Shortcuts are written like `ctrl+alt+space`, `ctrl+shift+k` or `alt+f1`: one or more of `ctrl`, `alt`, `shift`, `win`, then one key. Turning skills on or off and changing the theme take effect after restarting WinAuto; other changes apply right away.

## Settings only in `config.json`

Close WinAuto (tray → Quit) before editing `config.json` by hand, or your changes may be overwritten. Unknown keys are ignored and missing keys get their defaults, so a typo can't break anything.

| Key | Default | What it does |
|---|---|---|
| `llm.temperature` | `0.2` | Lower is more predictable; higher is more creative. |
| `llm.keep_alive` | `"30m"` | How long Ollama keeps the model in memory after a request. |
| `llm.timeout` | `180` | Seconds to wait for the model before giving up. |
| `llm.api_key` | `""` | For OpenAI-compatible servers that need one. |
| `email.display_name` | `""` | Name on sent emails (defaults to your name). |
| `history_turns` | `6` | How many past exchanges the AI remembers in a chat. |
| `max_steps` | `6` | Most tool rounds the AI may take for one request. |
| `extra_sites` | `{}` | Your own website names for "open …", e.g. `{"bank": "https://mybank.com"}` |
| `app_aliases` | `{}` | Your own app names, e.g. `{"editor": "Visual Studio Code", "music": "Spotify"}` |

Example:

```json
{
  "user_name": "Aaditya",
  "weather_location": "Pokhara",
  "extra_sites": {"bank": "https://mybank.com", "uni": "https://portal.example.edu"},
  "app_aliases": {"editor": "Visual Studio Code"},
  "llm": {"model": "qwen3:14b", "keep_alive": "2h"}
}
```

## Command-line options

| Command | What it does |
|---|---|
| `WinAuto.exe` / `python -m winauto` | Start normally (or show the running copy) |
| `--background` | Start hidden in the tray |
| `--selftest` | Check that everything loads and works, then exit (writes a report to your temp folder) |
| `--cli` | Chat in a terminal window instead of the popup |

## Starting over

- **Reset settings:** quit WinAuto and delete `config.json`. Defaults are recreated on the next start.
- **Delete all your data:** quit WinAuto and delete the data folder, and the `WinAuto` entry in Credential Manager.
