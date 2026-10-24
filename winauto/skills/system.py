"""Volume, brightness, dark mode, Wi-Fi/Bluetooth, power, battery and PC health."""

from __future__ import annotations

import logging
import re
from typing import Any, Literal

from winauto.core.skill import QuickRule, Risk, Skill, Suggestion, ToolResult, fail, ok, tool
from winauto.adapters.winos import NotOnWindows

log = logging.getLogger(__name__)

SETTINGS_PAGES = {
    "wifi": "ms-settings:network-wifi", "network": "ms-settings:network", "bluetooth": "ms-settings:bluetooth",
    "display": "ms-settings:display", "sound": "ms-settings:sound", "notifications": "ms-settings:notifications",
    "battery": "ms-settings:batterysaver", "power": "ms-settings:powersleep", "storage": "ms-settings:storagesense",
    "apps": "ms-settings:appsfeatures", "default apps": "ms-settings:defaultapps", "startup apps": "ms-settings:startupapps",
    "windows update": "ms-settings:windowsupdate", "update": "ms-settings:windowsupdate",
    "background": "ms-settings:personalization-background", "personalization": "ms-settings:personalization",
    "colors": "ms-settings:colors", "themes": "ms-settings:themes", "mouse": "ms-settings:mousetouchpad",
    "touchpad": "ms-settings:devices-touchpad", "keyboard": "ms-settings:keyboard", "printers": "ms-settings:printers",
    "privacy": "ms-settings:privacy", "accounts": "ms-settings:yourinfo", "time": "ms-settings:dateandtime",
    "date and time": "ms-settings:dateandtime", "language": "ms-settings:regionlanguage", "vpn": "ms-settings:network-vpn",
    "hotspot": "ms-settings:network-mobilehotspot", "night light": "ms-settings:nightlight",
    "focus": "ms-settings:focus", "do not disturb": "ms-settings:notifications", "about": "ms-settings:about",
    "microphone": "ms-settings:privacy-microphone", "camera": "ms-settings:privacy-webcam",
}


def _human_bytes(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{n:.0f} {unit}" if unit in ("B", "KB") else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"


def _human_duration(seconds: float) -> str:
    seconds = int(seconds)
    days, rem = divmod(seconds, 86400)
    hours, rem = divmod(rem, 3600)
    minutes = rem // 60
    parts = []
    if days:
        parts.append(f"{days} day{'s' if days != 1 else ''}")
    if hours:
        parts.append(f"{hours} h")
    if minutes and not days:
        parts.append(f"{minutes} min")
    return " ".join(parts) or "under a minute"


class SystemSkill(Skill):
    name = "system"
    description = "PC controls: volume, brightness, theme, Wi-Fi, Bluetooth, power, battery, health."
    keywords = (r"\b(volume|sound|mute|unmute|louder|quieter|brightness|bright|dim|screen|dark|light mode|wi-?fi|"
                r"bluetooth|lock|sleep|shut ?down|restart|reboot|sign out|log ?out|battery|cpu|ram|memory|disk|"
                r"slow|recycle|trash|settings?|pc|computer|laptop|hotspot|night light)\b")

    def __init__(self, ctx: Any, backend: Any = None):
        super().__init__(ctx)
        if backend is None:
            from winauto.adapters.winos.system import WindowsSystem

            backend = WindowsSystem()
        self.backend = backend

    def _run(self, fn, *args, success: str) -> ToolResult:
        try:
            fn(*args)
        except NotOnWindows as exc:
            return fail(str(exc))
        except Exception as exc:
            log.warning("system action failed: %s", exc)
            return fail(str(exc))
        return ok(success)

    # ----- volume -----

    @tool("Set the volume to a level from 0 to 100.", params={"level": "0-100"})
    def set_volume(self, level: int) -> ToolResult:
        level = max(0, min(100, level))
        return self._run(self.backend.set_volume, level, success=f"Volume set to {level}%.")

    @tool("Turn the volume up or down by some amount.", params={"change": "Percent to change, negative for down (e.g. 10 or -10)"})
    def change_volume(self, change: int = 10) -> ToolResult:
        try:
            current, _ = self.backend.get_volume()
        except NotOnWindows as exc:
            return fail(str(exc))
        except Exception:
            current = 50
        level = max(0, min(100, current + change))
        return self._run(self.backend.set_volume, level, success=f"Volume {'up' if change > 0 else 'down'} to {level}%.")

    @tool("Mute or unmute the sound.", params={"mute": "true to mute, false to unmute"})
    def mute(self, mute: bool = True) -> ToolResult:
        return self._run(self.backend.set_mute, mute, success="Muted." if mute else "Sound is back on.")

    # ----- display -----

    @tool("Set screen brightness (laptop screens) from 0 to 100.", params={"level": "0-100"})
    def set_brightness(self, level: int) -> ToolResult:
        level = max(0, min(100, level))
        return self._run(self.backend.set_brightness, level, success=f"Brightness set to {level}%.")

    @tool("Make the screen brighter or dimmer.", params={"change": "Percent to change, negative for dimmer"})
    def change_brightness(self, change: int = 15) -> ToolResult:
        try:
            current = self.backend.get_brightness()
        except NotOnWindows as exc:
            return fail(str(exc))
        except Exception as exc:
            return fail(str(exc))
        level = max(0, min(100, current + change))
        return self._run(self.backend.set_brightness, level, success=f"Brightness {level}%.")

    @tool("Switch Windows between dark mode and light mode.", params={"on": "true for dark mode, false for light mode"})
    def dark_mode(self, on: bool = True) -> ToolResult:
        return self._run(self.backend.set_dark_mode, on, success="Dark mode on." if on else "Light mode on.")

    # ----- radios / settings -----

    @tool("Turn Wi-Fi on or off.", params={"on": "true for on, false for off"})
    def wifi(self, on: bool) -> ToolResult:
        result = self._run(self.backend.set_radio, "WiFi", on, success=f"Wi-Fi {'on' if on else 'off'}.")
        if not result.ok and "only works on Windows" not in result.message:
            self.open_settings("wifi")
            result.message += " I opened Wi-Fi settings for you."
        return result

    @tool("Turn Bluetooth on or off.", params={"on": "true for on, false for off"})
    def bluetooth(self, on: bool) -> ToolResult:
        result = self._run(self.backend.set_radio, "Bluetooth", on, success=f"Bluetooth {'on' if on else 'off'}.")
        if not result.ok and "only works on Windows" not in result.message:
            self.open_settings("bluetooth")
            result.message += " I opened Bluetooth settings for you."
        return result

    @tool(
        "Open a page of Windows Settings.",
        params={"page": "e.g. wifi, bluetooth, display, sound, battery, windows update, background, storage, apps"},
        hides_popup=True,
    )
    def open_settings(self, page: str = "") -> ToolResult:
        key = re.sub(r"\s+settings?$", "", page.strip().lower())
        uri = SETTINGS_PAGES.get(key, "ms-settings:")
        label = f"{key} settings" if key in SETTINGS_PAGES else "Settings"
        return self._run(self.backend.open_uri, uri, success=f"Opened {label}.")

    # ----- power -----

    @tool("Lock the PC.")
    def lock_pc(self) -> ToolResult:
        return self._run(self.backend.lock, success="Locked.")

    @tool("Put the PC to sleep.", risk=Risk.CONFIRM, confirm_label="Sleep")
    def sleep_pc(self) -> ToolResult:
        return self._run(self.backend.sleep, success="Going to sleep.")

    @tool("Shut down, restart or sign out of the PC.",
          params={"action": "shutdown, restart or signout", "minutes": "Delay in minutes (0 = now)"},
          risk=Risk.CONFIRM, confirm_label="Yes, do it")
    def power_off(self, action: Literal["shutdown", "restart", "signout"] = "shutdown", minutes: int = 0) -> ToolResult:
        minutes = max(0, minutes)
        when = f" in {minutes} minute{'s' if minutes != 1 else ''}" if minutes else " now"
        verb = {"shutdown": "Shutting down", "restart": "Restarting", "signout": "Signing out"}[action]
        tail = " Say 'cancel shutdown' to stop it." if minutes and action != "signout" else ""
        return self._run(self.backend.shutdown, action, minutes * 60, success=f"{verb}{when}.{tail}")

    @tool("Cancel a scheduled shutdown or restart.")
    def cancel_shutdown(self) -> ToolResult:
        try:
            done = self.backend.cancel_shutdown()
        except NotOnWindows as exc:
            return fail(str(exc))
        return ok("Cancelled the shutdown.") if done else ok("There was no shutdown scheduled.")

    def preview(self, tool_name: str, args: dict[str, Any]) -> str | None:
        if tool_name == "power_off":
            action = args.get("action", "shutdown")
            minutes = args.get("minutes", 0)
            what = {"shutdown": "Shut down", "restart": "Restart", "signout": "Sign out of"}[action]
            when = f" in {minutes} minutes" if minutes else " now"
            return f"{what} the PC{when}? Save your work first."
        if tool_name == "sleep_pc":
            return "Put the PC to sleep now?"
        if tool_name == "empty_recycle_bin":
            try:
                count, size = self.backend.recycle_bin()
                return f"Permanently delete {count} item(s) ({_human_bytes(size)}) from the Recycle Bin?"
            except Exception:
                return "Permanently delete everything in the Recycle Bin?"
        return None

    # ----- status -----

    @tool("Battery level and whether it's charging.")
    def battery_status(self) -> ToolResult:
        import psutil

        battery = psutil.sensors_battery()
        if battery is None:
            return ok("This PC has no battery (it's on mains power).")
        state = "charging" if battery.power_plugged else "on battery"
        left = ""
        if not battery.power_plugged and battery.secsleft not in (psutil.POWER_TIME_UNLIMITED, psutil.POWER_TIME_UNKNOWN):
            left = f", about {_human_duration(battery.secsleft)} left"
        return ok(f"Battery at {battery.percent:.0f}% ({state}{left}).")

    @tool("PC health: CPU, memory, disk space, uptime, and what's using the most memory.")
    def pc_status(self) -> ToolResult:
        import psutil

        cpu = psutil.cpu_percent(interval=0.5)
        mem = psutil.virtual_memory()
        root = "C:\\" if self._is_windows() else "/"
        disk = psutil.disk_usage(root)
        procs = []
        for p in psutil.process_iter(["name", "memory_info"]):
            try:
                procs.append((p.info["memory_info"].rss, p.info["name"]))
            except (TypeError, AttributeError):
                continue
        totals: dict[str, int] = {}
        for rss, name in procs:
            key = (name or "?").removesuffix(".exe")
            totals[key] = totals.get(key, 0) + rss
        top = sorted(totals.items(), key=lambda x: -x[1])[:5]
        try:
            uptime = _human_duration(self.backend.uptime_seconds())
        except Exception:
            uptime = "unknown"
        lines = [
            f"CPU {cpu:.0f}% · Memory {mem.percent:.0f}% ({_human_bytes(mem.used)} of {_human_bytes(mem.total)})",
            f"Disk {root} {_human_bytes(disk.free)} free of {_human_bytes(disk.total)}",
            f"Up for {uptime}",
            "Using the most memory: " + ", ".join(f"{n} ({_human_bytes(b)})" for n, b in top),
        ]
        return ok("\n".join(lines))

    @staticmethod
    def _is_windows() -> bool:
        import sys

        return sys.platform == "win32"

    @tool("Empty the Recycle Bin (permanent).", risk=Risk.CONFIRM, confirm_label="Empty it")
    def empty_recycle_bin(self) -> ToolResult:
        return self._run(self.backend.empty_recycle_bin, success="Recycle Bin emptied.")

    # ----- launcher -----

    COMMANDS = [
        ("Lock PC", "lock_pc", {}, "lock", "lock screen"),
        ("Sleep", "sleep_pc", {}, "moon", "suspend standby"),
        ("Shut down", "power_off", {"action": "shutdown"}, "power", "shutdown power off turn off"),
        ("Restart", "power_off", {"action": "restart"}, "refresh", "reboot"),
        ("Sign out", "power_off", {"action": "signout"}, "log-out", "log out logoff"),
        ("Empty Recycle Bin", "empty_recycle_bin", {}, "trash", "trash bin"),
        ("Dark mode", "dark_mode", {"on": True}, "moon", "theme night"),
        ("Light mode", "dark_mode", {"on": False}, "sun", "theme day"),
        ("Mute", "mute", {"mute": True}, "volume-x", "silence sound"),
        ("Unmute", "mute", {"mute": False}, "volume", "sound on"),
        ("Battery status", "battery_status", {}, "battery", "charge"),
        ("PC health", "pc_status", {}, "activity", "cpu ram memory disk status slow"),
        ("Wi-Fi on", "wifi", {"on": True}, "wifi", "wireless internet"),
        ("Wi-Fi off", "wifi", {"on": False}, "wifi", "wireless internet"),
        ("Bluetooth on", "bluetooth", {"on": True}, "bluetooth", ""),
        ("Bluetooth off", "bluetooth", {"on": False}, "bluetooth", ""),
    ]

    def suggest(self, query: str) -> list[Suggestion]:
        from winauto.core.matching import normalize, score

        q = normalize(query)
        if len(q) < 2:
            return []
        out = []
        for title, tool_name, args, icon, extra in self.COMMANDS:
            best = max(score(q, title), *(score(q, w) for w in extra.split()) if extra else [0])
            if best >= 80:
                out.append(Suggestion(title=title, subtitle="System command", tool=tool_name, args=args,
                                      kind="Command", icon=icon, score=best - 2))
        for page in SETTINGS_PAGES:
            sc = score(q.removesuffix(" settings"), page)
            if sc >= 80 or (len(q) >= 3 and page.startswith(q)):
                out.append(Suggestion(title=f"{page.title()} settings", subtitle="Windows Settings", tool="open_settings",
                                      args={"page": page}, kind="Setting", icon="settings", score=min(sc, 95) - 5))
        return sorted(out, key=lambda x: -x.score)[:4]

    # ----- quick commands -----

    def quick_rules(self) -> list[QuickRule]:
        pc = r"(?:\s+(?:the\s+|my\s+)?(?:pc|computer|laptop|system|windows))?"

        def radio(m):
            name = (m["r"] or "").lower().replace("-", "")
            state = (m["s"] or "").lower()
            tool_name = "wifi" if "wifi" in name else "bluetooth"
            return tool_name, {"on": state in ("on", "enable", "start")}

        def vol_dir(m):
            d = m["d"].lower()
            n = int(m["n"]) if m["n"] else 10
            return "change_volume", {"change": n if d in ("up", "louder", "increase", "raise") else -n}

        def bright_dir(m):
            d = m["d"].lower()
            return "change_brightness", {"change": 15 if d in ("up", "brighter", "increase") else -15}

        radios = r"(?P<r>wi-?fi|bluetooth)"
        states = r"(?P<s>on|off|enable|disable|start|stop)"
        return [
            QuickRule(r"(?:set\s+)?(?:the\s+)?(?:volume|sound)\s+(?:to\s+|at\s+)?(?P<n>\d{1,3})\s*%?(?:\s+percent)?",
                      lambda m: ("set_volume", {"level": int(m["n"])})),
            QuickRule(r"(?:turn\s+(?:the\s+)?)?(?:volume|sound)\s+(?P<d>up|down)(?:\s+(?:by\s+)?(?P<n>\d{1,2})\s*%?)?", vol_dir),
            QuickRule(r"(?:turn\s+(?:it|the\s+volume|the\s+sound)\s+)(?P<d>up|down)(?:\s+(?:by\s+)?(?P<n>\d{1,2})\s*%?)?", vol_dir),
            QuickRule(r"(?:(?:make\s+it|a\s+bit|bit)\s+)?(?P<d>louder|quieter)(?P<n>)", vol_dir),
            QuickRule(r"(?:mute|silence)(?:\s+(?:the\s+)?(?:volume|sound|audio|pc|computer|speakers))?",
                      lambda m: ("mute", {"mute": True})),
            QuickRule(r"unmute(?:\s+(?:the\s+)?(?:volume|sound|audio|pc|computer|speakers))?",
                      lambda m: ("mute", {"mute": False})),
            QuickRule(r"(?:set\s+)?(?:the\s+)?(?:screen\s+)?brightness\s+(?:to\s+)?(?P<n>\d{1,3})\s*%?",
                      lambda m: ("set_brightness", {"level": int(m["n"])})),
            QuickRule(r"(?:turn\s+)?(?:the\s+)?(?:screen\s+)?brightness\s+(?P<d>up|down)|make\s+(?:the\s+)?screen\s+(?P<d2>brighter|dimmer)|(?P<d3>dim)\s+(?:the\s+)?screen",
                      lambda m: bright_dir({"d": m["d"] or m["d2"] or "down"})),
            QuickRule(r"(?:turn\s+|switch\s+)?(?:on\s+|enable\s+)?dark\s+mode(?:\s+on)?|(?:switch|go)\s+to\s+dark\s+mode",
                      lambda m: ("dark_mode", {"on": True})),
            QuickRule(r"(?:turn\s+|switch\s+)?(?:off\s+|disable\s+)dark\s+mode|dark\s+mode\s+off|(?:turn\s+on\s+|switch\s+to\s+|go\s+to\s+)?light\s+mode(?:\s+on)?",
                      lambda m: ("dark_mode", {"on": False})),
            QuickRule(rf"(?:turn\s+)?{states}\s+(?:the\s+)?{radios}", radio),
            QuickRule(rf"(?:turn\s+)?(?:the\s+)?{radios}\s+{states}", radio),
            QuickRule(r"lock" + pc + r"|lock\s+(?:the\s+)?screen", lambda m: ("lock_pc", {})),
            QuickRule(r"(?:shut\s*down|power\s+off|turn\s+off)" + pc + r"(?:\s+in\s+(?P<n>\d+)\s*(?:min|mins|minutes))?",
                      lambda m: ("power_off", {"action": "shutdown", "minutes": int(m["n"] or 0)})),
            QuickRule(r"(?:restart|reboot)" + pc + r"(?:\s+in\s+(?P<n>\d+)\s*(?:min|mins|minutes))?",
                      lambda m: ("power_off", {"action": "restart", "minutes": int(m["n"] or 0)})),
            QuickRule(r"(?:sign|log)\s*(?:out|off)", lambda m: ("power_off", {"action": "signout"})),
            QuickRule(r"(?:put\s+(?:the\s+)?(?:pc|computer|laptop)\s+to\s+)?sleep" + pc + r"|go\s+to\s+sleep",
                      lambda m: ("sleep_pc", {})),
            QuickRule(r"(?:cancel|abort|stop)\s+(?:the\s+)?(?:shutdown|restart|reboot)", lambda m: ("cancel_shutdown", {})),
            QuickRule(r"(?:what(?:'s| is)\s+(?:my\s+|the\s+)?)?battery(?:\s+(?:status|level|percentage|left|life))?|how\s+much\s+battery(?:\s+(?:is\s+)?left)?(?:\s+do\s+i\s+have)?",
                      lambda m: ("battery_status", {})),
            QuickRule(r"(?:pc|computer|system)\s+(?:status|health)|(?:cpu|ram|memory)\s+usage|how\s+is\s+my\s+(?:pc|computer)(?:\s+doing)?|why\s+is\s+my\s+(?:pc|computer|laptop)\s+(?:so\s+)?slow",
                      lambda m: ("pc_status", {})),
            QuickRule(r"empty\s+(?:the\s+)?(?:recycle\s*bin|trash|bin)", lambda m: ("empty_recycle_bin", {})),
            QuickRule(r"(?:open\s+)?(?P<p>[a-z ]+?)\s+settings", lambda m: ("open_settings", {"page": m["p"]})
                      if m["p"].strip().lower() in SETTINGS_PAGES else None, priority=45),
        ]
