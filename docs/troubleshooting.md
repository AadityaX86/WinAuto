# Troubleshooting

## First steps

1. **Check the status dot** at the bottom left of the popup: green means the AI is ready, grey means it's downloading or loading, red means there's a problem (the card on the home screen or a message in the chat explains it).
2. **Look at the log:** tray icon → **Open log file**. The last lines usually say what went wrong.
3. **Run the self-test:** `WinAuto.exe --selftest` (or `python -m winauto --selftest`). It checks every skill, the database, Windows features, Credential Manager and the popup, and writes a report to your temp folder.

## The built-in AI

| Problem | Fix |
|---|---|
| The download is slow or stopped | Press **Pause**, then **Continue**: it picks up where it stopped. A restart of WinAuto does too. Downloads come from Hugging Face (the model) and GitHub (the engine); a VPN or firewall that blocks those sites stops it. |
| "Not enough free disk space" | The standard model needs about 6 GB on the drive with your user profile (usually C:). Free some space and press **Try again**, or choose the small model (3 GB) in Settings → AI model. |
| "The downloaded file was damaged" | Press **Try again**. If it keeps happening, something on your network is changing downloads (some antivirus "web shields" do); pause it while WinAuto downloads. |
| "The AI couldn't be set up" / "couldn't start" | Update your graphics drivers, then press **Try again**. The details are in `%LOCALAPPDATA%\WinAuto\ai\logs\engine.log`. If the graphics card can't be used, WinAuto falls back to the processor by itself. |
| Antivirus quarantined `llama-server.exe` | It's llama.cpp's open-source engine. Restore it and add an exception for `%LOCALAPPDATA%\WinAuto\ai`, or delete that folder so WinAuto downloads it again. |
| Answers are slow | The first answer after starting takes a few seconds while the model loads. If every answer is slow, your graphics card may be too small for the model: switch to the small one in Settings → AI model, and close games or video editors. |
| The AI does the wrong thing or says it can't | Be specific ("email Ram…" rather than "tell Ram…" if you mean email). Start a new chat (**＋**) if an earlier conversation confuses it. |

## Ollama or another server

| Problem | Fix |
|---|---|
| "Ollama isn't running" | Start Ollama from the Start menu, or run `ollama serve` in Command Prompt. WinAuto tries to start it for you. |
| "The model … isn't downloaded" | Run `ollama pull qwen3:8b` (or the model named in Settings → AI model). |
| "What's on my screen" says the model isn't downloaded | Run `ollama pull qwen2.5vl:7b`, or choose another vision model in Settings → AI model. |
| LM Studio / other server doesn't connect | Check the address ends in `/v1` and a model is loaded; press **Test connection**. |

## Shortcuts and the popup

| Problem | Fix |
|---|---|
| Ctrl+Alt+Space does nothing | Another app already uses it (the chat shows "Hotkey problem"). Pick another in Settings → General, e.g. `ctrl+shift+space`. |
| Popup doesn't appear over a full-screen game | Games in exclusive full-screen mode can cover other windows; switch the game to borderless or windowed mode. |
| Writing tools say "select some text first" | Select the text, then press Ctrl+Alt+T. Some apps (password fields, some games) block copying. |
| "Replace selection" pasted in the wrong place | WinAuto pastes into the window you were in before opening it. Click back into the text box and try again, or use **Copy**. |

## Apps, PC and files

| Problem | Fix |
|---|---|
| "I can't find an app called …" | Say the name as it appears in the Start menu, or add your own name in `app_aliases` ([settings](configuration.md#settings-only-in-configjson)). New installs are picked up within a minute. |
| Brightness doesn't change | Only built-in laptop screens can be controlled; external monitors usually can't. |
| Bluetooth / Wi-Fi toggles fail | Some PCs only allow it from Settings; WinAuto opens the right Settings page instead. |
| A file search misses something | WinAuto searches your usual folders (Desktop, Documents, Downloads, Pictures, Videos, Music, OneDrive), not system folders or other drives. |

## Email, messages and calendar

| Problem | Fix |
|---|---|
| Gmail "rejected the sign-in" | Make a new app password ([how](connect-accounts.md#gmail)) and paste it in Settings. Your normal password won't work. |
| WhatsApp message typed but not sent | Keep WhatsApp signed in. If another window jumped in front, WinAuto doesn't press Enter; press it yourself. |
| Message went to the wrong Discord chat | Save the exact Discord username in the contact (`update contact Sita discord sita_k`), or turn off **Press Send in Discord** to check first. |
| "Which Ram? I have Ram Sharma, Ram Thapa." | Use the full name or a nickname (`update contact Ram Thapa nickname dai`). |
| Calendar is empty | Check the link in Settings → Accounts. It must be the *secret/private* iCal address, not the public or embed link. |

## WinAuto won't start

- If nothing happens, look for `%TEMP%\winauto-crash.txt`; it has the error.
- Windows SmartScreen ("Windows protected your PC"): click **More info → Run anyway**. The app isn't code-signed.
- Antivirus quarantined it: packaged Python apps are sometimes flagged by mistake, the single-file exe more often than the zip. Use the zip, or restore it and add an exception, or [run from source](getting-started.md#option-b-run-from-source).
- Two copies: starting WinAuto again just shows the running one.

## Reporting a problem

Open an issue on GitHub with:

- what you typed and what happened,
- the last 30 lines of the log file,
- the self-test report if WinAuto won't start properly,
- your Windows version and the model you use.

Remove anything private from the log first (it may contain your requests).
