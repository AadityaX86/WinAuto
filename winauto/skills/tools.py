"""Handy tools: passwords, emoji, colours, network info, terminal commands, temp cleanup."""

from __future__ import annotations

import colorsys
import logging
import os
import re
import secrets
import string
import sys
import time
from pathlib import Path
from typing import Any, Callable

from winauto.adapters import sysinfo
from winauto.adapters.http import FetchError, fetch
from winauto.adapters.winos import NotOnWindows, run_hidden
from winauto.core.context import Context
from winauto.core.skill import (
    QuickRule,
    Risk,
    Skill,
    Suggestion,
    ToolResult,
    fail,
    ok,
    tool,
)
from winauto.skills.shared.format import human_size

log = logging.getLogger(__name__)

# name: (emoji, extra search words)
EMOJI = {
    "grinning": ("😀", "smile happy"), "joy": ("😂", "laugh tears lol"), "rofl": ("🤣", "laugh rolling"),
    "smile": ("😊", "happy blush"), "wink": ("😉", ""), "heart eyes": ("😍", "love"), "kiss": ("😘", "love"),
    "thinking": ("🤔", "hmm"), "neutral": ("😐", "meh"), "eye roll": ("🙄", ""), "smirk": ("😏", ""),
    "relieved": ("😌", ""), "sleeping": ("😴", "tired zzz"), "sunglasses": ("😎", "cool"),
    "nerd": ("🤓", "geek"), "party": ("🥳", "celebrate birthday"), "pleading": ("🥺", "please puppy"),
    "cry": ("😢", "sad tear"), "sob": ("😭", "crying sad"), "angry": ("😠", "mad"), "rage": ("😡", "angry mad"),
    "scream": ("😱", "shock scared"), "sweat smile": ("😅", "nervous"), "upside down": ("🙃", ""),
    "shush": ("🤫", "quiet secret"), "facepalm": ("🤦", ""), "shrug": ("🤷", "dunno"), "clown": ("🤡", ""),
    "skull": ("💀", "dead lol"), "ghost": ("👻", "boo"), "poop": ("💩", ""), "alien": ("👽", ""),
    "robot": ("🤖", "bot"), "thumbs up": ("👍", "like yes ok"), "thumbs down": ("👎", "dislike no"),
    "ok hand": ("👌", "perfect"), "clap": ("👏", "applause"), "wave": ("👋", "hi hello bye"),
    "pray": ("🙏", "please thanks namaste"), "muscle": ("💪", "strong flex"), "point up": ("☝️", ""),
    "point right": ("👉", ""), "raised hands": ("🙌", "hooray"), "handshake": ("🤝", "deal"),
    "fingers crossed": ("🤞", "luck"), "victory": ("✌️", "peace"), "eyes": ("👀", "look"),
    "brain": ("🧠", "smart"), "heart": ("❤️", "love red"), "orange heart": ("🧡", ""), "yellow heart": ("💛", ""),
    "green heart": ("💚", ""), "blue heart": ("💙", ""), "purple heart": ("💜", ""), "black heart": ("🖤", ""),
    "broken heart": ("💔", "sad"), "sparkling heart": ("💖", ""), "fire": ("🔥", "lit hot"),
    "sparkles": ("✨", "shiny new"), "star": ("⭐", ""), "glowing star": ("🌟", ""), "boom": ("💥", "explosion"),
    "100": ("💯", "hundred perfect"), "check": ("✅", "done yes tick"), "cross": ("❌", "no wrong x"),
    "warning": ("⚠️", "caution"), "question": ("❓", ""), "exclamation": ("❗", ""), "zzz": ("💤", "sleep"),
    "rocket": ("🚀", "launch ship"), "tada": ("🎉", "party celebrate congrats"), "gift": ("🎁", "present birthday"),
    "balloon": ("🎈", "party"), "cake": ("🎂", "birthday"), "trophy": ("🏆", "win"), "medal": ("🥇", "first gold"),
    "soccer": ("⚽", "football"), "cricket": ("🏏", ""), "basketball": ("🏀", ""), "game": ("🎮", "gaming controller"),
    "music": ("🎵", "note song"), "headphones": ("🎧", "music"), "camera": ("📷", "photo"), "phone": ("📱", "mobile"),
    "laptop": ("💻", "computer"), "keyboard": ("⌨️", ""), "bulb": ("💡", "idea"), "book": ("📖", "read"),
    "pencil": ("✏️", "write"), "memo": ("📝", "note"), "calendar": ("📅", "date"), "pin": ("📌", ""),
    "paperclip": ("📎", "attach"), "lock": ("🔒", "secure"), "key": ("🔑", ""), "bell": ("🔔", "notification"),
    "mail": ("📧", "email"), "package": ("📦", "box delivery"), "money": ("💰", "cash bag"), "dollar": ("💵", "cash"),
    "chart up": ("📈", "growth stocks"), "chart down": ("📉", ""), "clock": ("⏰", "alarm time"),
    "hourglass": ("⏳", "wait time"), "coffee": ("☕", "tea hot"), "tea": ("🍵", ""), "pizza": ("🍕", "food"),
    "burger": ("🍔", "food"), "momo": ("🥟", "dumpling food"), "beer": ("🍺", "drink cheers"), "cheers": ("🥂", "toast"),
    "apple": ("🍎", "fruit"), "sun": ("☀️", "sunny weather"), "cloud": ("☁️", "weather"), "rain": ("🌧️", "weather"),
    "snow": ("❄️", "cold weather"), "rainbow": ("🌈", ""), "moon": ("🌙", "night"), "earth": ("🌍", "world globe"),
    "mountain": ("🏔️", "himalaya"), "tree": ("🌳", "nature"), "flower": ("🌸", "blossom"), "rose": ("🌹", "love"),
    "dog": ("🐶", "puppy"), "cat": ("🐱", "kitty"), "monkey": ("🙈", "see no evil"), "unicorn": ("🦄", ""),
    "car": ("🚗", ""), "plane": ("✈️", "flight travel"), "house": ("🏠", "home"), "flag nepal": ("🇳🇵", "nepal"),
    "flag india": ("🇮🇳", "india"), "flag usa": ("🇺🇸", "america us"), "flag uk": ("🇬🇧", "britain"),
    "white check": ("✔️", "tick"), "arrow right": ("➡️", ""), "recycle": ("♻️", ""), "infinity": ("♾️", ""),
}


def search_emoji(query: str, limit: int = 8) -> list[tuple[str, str]]:
    q = query.strip().lower().strip(":")
    if not q:
        return []
    scored = []
    for name, (char, extra) in EMOJI.items():
        words = (name + " " + extra).split()
        if name.startswith(q):
            scored.append((0, name, char))
        elif any(w.startswith(q) for w in words):
            scored.append((1, name, char))
        elif q in name:
            scored.append((2, name, char))
    scored.sort()
    return [(name, char) for _, name, char in scored[:limit]]


def parse_color(text: str) -> tuple[int, int, int] | None:
    t = text.strip().lower()
    m = re.fullmatch(r"#?([0-9a-f]{3}|[0-9a-f]{6})", t)
    if m and (t.startswith("#") or re.search(r"[a-f]", t) or len(m.group(1)) == 6):
        h = m.group(1)
        if len(h) == 3:
            h = "".join(c * 2 for c in h)
        return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    m = re.fullmatch(r"rgba?\(\s*(\d{1,3})\s*,\s*(\d{1,3})\s*,\s*(\d{1,3})\s*(?:,\s*[\d.]+\s*)?\)", t)
    if m:
        r, g, b = (min(255, int(x)) for x in m.groups())
        return r, g, b
    m = re.fullmatch(r"hsla?\(\s*([\d.]+)\s*,\s*([\d.]+)%\s*,\s*([\d.]+)%\s*(?:,\s*[\d.]+\s*)?\)", t)
    if m:
        h, s, light = float(m.group(1)) / 360, float(m.group(2)) / 100, float(m.group(3)) / 100
        r, g, b = colorsys.hls_to_rgb(h, light, s)
        return round(r * 255), round(g * 255), round(b * 255)
    return None


def color_formats(rgb: tuple[int, int, int]) -> dict[str, str]:
    r, g, b = rgb
    h, light, s = colorsys.rgb_to_hls(r / 255, g / 255, b / 255)
    return {
        "hex": f"#{r:02X}{g:02X}{b:02X}",
        "rgb": f"rgb({r}, {g}, {b})",
        "hsl": f"hsl({round(h * 360)}, {round(s * 100)}%, {round(light * 100)}%)",
    }


def make_password(length: int = 16, symbols: bool = True) -> str:
    length = max(8, min(length, 128))
    alphabet = string.ascii_letters + string.digits + ("!@#$%^&*-_=+?" if symbols else "")
    while True:
        pw = "".join(secrets.choice(alphabet) for _ in range(length))
        # Make sure every kind of character is there.
        if (any(c.islower() for c in pw) and any(c.isupper() for c in pw) and any(c.isdigit() for c in pw)
                and (not symbols or any(not c.isalnum() for c in pw))):
            return pw


class ToolsSkill(Skill):
    name = "tools"
    icon = "tool"
    description = "Passwords, emoji, colours, network info, terminal commands, temp cleanup."
    keywords = r"\b(password|emoji|colou?r|hex|rgb|ip address|my ip|network|wifi name|command|terminal|cmd|powershell|temp files|clean ?up)\b|^>"

    def __init__(self, ctx: Context, clipboard: Any = None, fetcher: Callable[..., tuple[str, str]] | None = None):
        super().__init__(ctx)
        self._clipboard = clipboard
        self._fetch = fetcher or fetch

    def clipboard(self):
        if self._clipboard is None:
            from winauto.adapters.winos.clipboard import WindowsClipboard

            self._clipboard = WindowsClipboard()
        return self._clipboard

    def _copy(self, text: str) -> bool:
        try:
            self.clipboard().set_text(text)
            return True
        except (NotOnWindows, OSError):
            return False

    @tool("Generate a strong random password and copy it.",
          params={"length": "How many characters (default 16)", "symbols": "Include symbols (default true)"})
    def generate_password(self, length: int = 16, symbols: bool = True) -> ToolResult:
        pw = make_password(length, symbols)
        copied = self._copy(pw)
        return ok(f"`{pw}`" + (" (copied)" if copied else ""), data={"length": len(pw)})

    @tool("Find an emoji by name and copy it.", params={"name": "e.g. 'party', 'thumbs up', 'fire'"})
    def find_emoji(self, name: str) -> ToolResult:
        found = search_emoji(name, 6)
        if not found:
            return fail(f"No emoji for “{name}”.")
        self._copy(found[0][1])
        others = "  ".join(f"{c} {n}" for n, c in found[1:])
        return ok(f"{found[0][1]} copied." + (f"  Others: {others}" if others else ""))

    @tool("Convert a colour between hex, rgb and hsl.", params={"color": "e.g. '#ff8800', 'rgb(255, 136, 0)'"})
    def convert_color(self, color: str) -> ToolResult:
        rgb = parse_color(color)
        if not rgb:
            return fail(f"“{color}” isn't a colour I understand. Try #ff8800 or rgb(255, 136, 0).")
        f = color_formats(rgb)
        return ok(f"{f['hex']} · {f['rgb']} · {f['hsl']}", data=f)

    @tool("Pick the colour under the mouse pointer after a short delay, and copy its hex code.",
          params={"delay_seconds": "Seconds to wait so you can point at the colour (default 3)"})
    def pick_color(self, delay_seconds: int = 3) -> ToolResult:
        self.ctx.host.hide()
        time.sleep(max(0, min(delay_seconds, 10)))
        try:
            from winauto.adapters.winos.screen import color_under_cursor

            rgb = color_under_cursor()
        except (NotOnWindows, OSError) as exc:
            return fail(str(exc))
        f = color_formats(rgb)
        self._copy(f["hex"])
        self.ctx.notify("Colour picked", f"{f['hex']} copied · {f['rgb']}")
        return ok(f"Picked {f['hex']} (copied) · {f['rgb']} · {f['hsl']}", data=f)

    @tool("Show this PC's network details: local IP, public IP, Wi-Fi network name.")
    def network_info(self) -> ToolResult:
        ip = sysinfo.local_ip()
        lines = [f"Local IP: {ip}" if ip else "Local IP: not connected"]
        try:
            public, _ = self._fetch("https://api.ipify.org", timeout=6)
            lines.append(f"Public IP: {public.strip()}")
        except FetchError:
            lines.append("Public IP: couldn't check (offline?)")
        wifi = sysinfo.wifi_network()
        if wifi:
            name, signal = wifi
            lines.append(f"Wi-Fi: {name}" + (f" ({signal} signal)" if signal else ""))
        lines.append(f"PC name: {sysinfo.hostname()}")
        return ok("\n".join(lines))

    @tool(
        "Run a command in the terminal (cmd, or PowerShell if it starts with 'ps ') and show its output.",
        params={"command": "The command to run"},
        risk=Risk.CONFIRM, editable=("command",), confirm_label="Run",
    )
    def run_command(self, command: str) -> ToolResult:
        command = command.strip().lstrip(">").strip()
        if not command:
            return fail("Which command?")
        if sys.platform != "win32":
            return fail("Running commands only works on Windows.")
        if command.lower().startswith("ps "):
            args = ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", command[3:]]
        else:
            args = ["cmd.exe", "/c", command]
        try:
            r = run_hidden(args, timeout=60)
        except Exception as exc:  # timeout etc.
            return fail(f"The command didn't finish: {exc}")
        output = (r.stdout + ("\n" + r.stderr if r.stderr.strip() else "")).strip() or "(no output)"
        if len(output) > 3000:
            output = output[:3000] + "\n…(cut)"
        status = "✓" if r.returncode == 0 else f"✗ exit code {r.returncode}"
        return ok(f"{status}\n```\n{output}\n```", data={"exit_code": r.returncode})

    def _temp_candidates(self) -> list[Path]:
        temp = Path(os.environ.get("TEMP") or os.environ.get("TMP") or "/tmp")
        cutoff = time.time() - 86400
        out = []
        try:
            for p in temp.iterdir():
                try:
                    if p.is_file() and p.stat().st_mtime < cutoff:
                        out.append(p)
                except OSError:
                    continue
        except OSError:
            pass
        return out

    @tool("Delete temporary files older than a day to free up space.", risk=Risk.CONFIRM, confirm_label="Clean up")
    def clean_temp_files(self) -> ToolResult:
        freed = removed = 0
        for p in self._temp_candidates():
            try:
                size = p.stat().st_size
                p.unlink()
                freed += size
                removed += 1
            except OSError:
                continue  # in use
        return ok(f"Removed {removed} temporary file(s), freeing {human_size(freed)}.")

    def preview(self, tool_name: str, args: dict[str, Any]) -> str | None:
        if tool_name == "run_command":
            return "Run this command? Commands can change your PC, so check it first."
        if tool_name == "clean_temp_files":
            files = self._temp_candidates()
            total = sum(p.stat().st_size for p in files if p.exists())
            return f"Delete {len(files)} temporary file(s) ({human_size(total)}) older than a day? Files in use are skipped."
        return None

    # ----- launcher & quick commands -----

    def suggest(self, query: str) -> list[Suggestion]:
        q = query.strip()
        out: list[Suggestion] = []
        if q.startswith(">") and len(q) > 1:
            out.append(Suggestion(title=q[1:].strip(), subtitle="Run in terminal", tool="run_command",
                                  args={"command": q[1:].strip()}, kind="Terminal", icon="terminal", score=99))
            return out
        emoji_q = re.match(r"^(?::|emoji\s+)(.+)$", q, re.I)
        if emoji_q:
            for name, char in search_emoji(emoji_q.group(1)):
                out.append(Suggestion(title=f"{char}  {name}", subtitle="Copy emoji", tool="set_clipboard",
                                      args={"text": char}, kind="Emoji", icon="smile", score=96))
            return out
        rgb = parse_color(q)
        if rgb and (q.startswith("#") or q.lower().startswith(("rgb", "hsl"))):
            for label, value in color_formats(rgb).items():
                out.append(Suggestion(title=value, subtitle=f"Copy as {label}", tool="set_clipboard", args={"text": value},
                                      kind="Colour", icon=f"swatch:{color_formats(rgb)['hex']}", score=97))
        if re.fullmatch(r"(?:generate\s+(?:a\s+)?)?(?:strong\s+)?pass(?:word)?", q, re.I):
            pw = make_password()
            out.append(Suggestion(title=pw, subtitle="New strong password · Enter copies", tool="set_clipboard",
                                  args={"text": pw}, kind="Copy", icon="key", score=96))
        return out

    def quick_rules(self) -> list[QuickRule]:
        return [
            QuickRule(r">\s*(?P<c>.+)", lambda m: ("run_command", {"command": m["c"]}), priority=10),
            QuickRule(r"(?:generate|make|create|give me)\s+(?:a\s+)?(?:new\s+|strong\s+|random\s+)*password(?:\s+(?:of|with)\s+(?P<n>\d+)(?:\s+(?:chars?|characters))?)?",
                      lambda m: ("generate_password", {"length": int(m["n"] or 16)})),
            QuickRule(r"(?:pick|grab|get)\s+(?:a\s+|the\s+)?colou?r(?:\s+(?:from|on)\s+(?:the\s+)?screen)?|colou?r\s+picker",
                      lambda m: ("pick_color", {})),
            QuickRule(r"(?:what(?:'s| is)\s+)?my\s+(?:public\s+|local\s+)?ip(?:\s+address)?|network\s+(?:info|details|status)|what\s+wi-?fi\s+am\s+i\s+on",
                      lambda m: ("network_info", {})),
            QuickRule(r"(?:clean\s+up|delete|clear|remove)\s+(?:my\s+|the\s+)?temp(?:orary)?\s+files", lambda m: ("clean_temp_files", {})),
            QuickRule(r"emoji\s+(?:for\s+)?(?P<n>.+)", lambda m: ("find_emoji", {"name": m["n"]})),
        ]
