# Privacy and security

WinAuto is built to keep your requests and data on your PC.

## What stays on your PC

- **Your requests and the AI's answers.** The model runs locally in Ollama (or another server you choose). Nothing is sent to an AI company.
- **Your notes, todos, contacts, reminders, routines, calendar events, memories and command history.** These live in `winauto.db` in `%APPDATA%\WinAuto`.
- **Screenshots** for "what's on my screen". They go only to your local vision model and are never saved to disk.
- **Clipboard history.** It's kept in memory and disappears when WinAuto quits.
- **Selected text for writing tools.** WinAuto copies the selection, then puts back whatever was on your clipboard before.

## What goes online, and only when you ask

Only the words you look up are sent:

| When you… | WinAuto contacts |
|---|---|
| Ask something that needs a web search | DuckDuckGo |
| Ask about the weather (also the home screen card, at most hourly) | wttr.in |
| Convert currencies | open.er-api.com |
| Define a word | dictionaryapi.dev |
| Ask for a Wikipedia summary | wikipedia.org |
| Ask for news (and the daily briefing) | Google News RSS |
| Play music | youtube.com, to find the top result |
| Ask for your IP address | api.ipify.org |
| Read a web page | that page |
| Use email | Gmail, directly from your PC (SMTP/IMAP over TLS) |
| Have calendar links set | your calendar provider, to download the read-only feed (cached for 10 minutes) |

Opening websites and web searches happen in your normal browser, under that browser's privacy settings. WinAuto has no analytics, telemetry or update checks.

## Your accounts and passwords

- **Gmail** uses an app password stored in **Windows Credential Manager**, protected by your Windows sign-in. It's never written to WinAuto's files or logs. Revoke it any time at https://myaccount.google.com/apppasswords.
- **WhatsApp and Discord** are used through their own apps on your PC; WinAuto never sees your login.
- **Calendar** links are read-only. Anyone with the private link can read the calendar, so keep it to yourself.

## Safety checks

- Anything that **sends** (email, WhatsApp, Discord), **deletes** (notes, todos, contacts, files to the Recycle Bin, temp files, emptying the Recycle Bin), **runs a terminal command**, **force-closes an app** or **shuts down / restarts** shows an approval card first. Nothing happens until you press the button. The AI can't skip this, because the check belongs to the tool, not to what the AI says.
- Drafts and commands can be edited on the card before you approve them.
- Some processes (Explorer, Windows system processes, WinAuto itself) can't be closed through WinAuto.
- File cleanup only touches your Temp folder and files older than a day; organising Downloads only moves files, never deletes them.

## The log file

`logs\winauto.log` records what WinAuto did (requests, tools run, errors) to help with troubleshooting. It stays on your PC; check it before sharing it with anyone.

## Deleting your data

Quit WinAuto (tray → Quit), then delete the `%APPDATA%\WinAuto` folder, and the `WinAuto` entry in Credential Manager (Windows Credentials). Turn off **Start with Windows** first, or delete the `WinAuto` value under `HKCU\Software\Microsoft\Windows\CurrentVersion\Run`.
