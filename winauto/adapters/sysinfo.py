"""Facts about this PC: battery, CPU/memory/disk use, network addresses (psutil and sockets)."""

from __future__ import annotations

import re
import socket
import sys
from dataclasses import dataclass


@dataclass
class Battery:
    percent: float
    plugged_in: bool
    seconds_left: int | None  # None while charging or when Windows can't tell


@dataclass
class Usage:
    cpu_percent: float
    memory_percent: float
    memory_used: int
    memory_total: int
    disk_root: str
    disk_free: int
    disk_total: int
    top_memory: list[tuple[str, int]]  # (app name, bytes), biggest first


def battery() -> Battery | None:
    """None on PCs without a battery."""
    import psutil

    b = psutil.sensors_battery()
    if b is None:
        return None
    unknown = (psutil.POWER_TIME_UNLIMITED, psutil.POWER_TIME_UNKNOWN)
    left = None if b.power_plugged or b.secsleft in unknown else int(b.secsleft)
    return Battery(float(b.percent), bool(b.power_plugged), left)


def usage(top: int = 5) -> Usage:
    import psutil

    cpu = psutil.cpu_percent(interval=0.5)
    mem = psutil.virtual_memory()
    root = "C:\\" if sys.platform == "win32" else "/"
    disk = psutil.disk_usage(root)
    totals: dict[str, int] = {}
    for p in psutil.process_iter(["name", "memory_info"]):
        try:
            key = (p.info["name"] or "?").removesuffix(".exe")
            totals[key] = totals.get(key, 0) + p.info["memory_info"].rss
        except (TypeError, AttributeError):
            continue
    biggest = sorted(totals.items(), key=lambda x: -x[1])[:top]
    return Usage(cpu, mem.percent, mem.used, mem.total, root, disk.free, disk.total, biggest)


def local_ip() -> str | None:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("192.0.2.1", 80))  # no packets are sent for UDP connect
            return s.getsockname()[0]
    except OSError:
        return None


def hostname() -> str:
    return socket.gethostname()


def wifi_network() -> tuple[str, str] | None:
    """(network name, signal) on Windows when on Wi-Fi."""
    if sys.platform != "win32":
        return None
    from winauto.adapters.winos import run_hidden

    try:
        out = run_hidden(["netsh", "wlan", "show", "interfaces"], timeout=10).stdout
    except (OSError, ValueError):
        return None
    ssid = re.search(r"^\s*SSID\s*:\s*(.+)$", out, re.M)
    signal = re.search(r"^\s*Signal\s*:\s*(.+)$", out, re.M)
    return (ssid.group(1).strip(), signal.group(1).strip() if signal else "") if ssid else None
