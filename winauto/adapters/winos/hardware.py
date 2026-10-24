"""Which graphics cards this PC has and how much memory they have (for picking an AI model)."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from winauto.adapters.winos import IS_WINDOWS

log = logging.getLogger(__name__)

# Display adapters' driver settings live under this device class.
DISPLAY_CLASS = r"SYSTEM\CurrentControlSet\Control\Class\{4d36e968-e325-11ce-bfc1-08002be10318}"


@dataclass
class Gpu:
    name: str
    vram: int  # bytes of dedicated video memory

    @property
    def vram_gb(self) -> float:
        return self.vram / 1024**3


def gpus() -> list[Gpu]:
    """Graphics cards with their dedicated memory, biggest first. Empty when unknown or not on Windows.

    Reads the driver's registry entry: HardwareInformation.qwMemorySize is exact
    (WMI's AdapterRAM stops at 4 GB).
    """
    if not IS_WINDOWS:
        return []
    import winreg

    found: list[Gpu] = []
    try:
        root = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, DISPLAY_CLASS)
    except OSError:
        return []
    with root:
        for i in range(64):
            try:
                sub = winreg.EnumKey(root, i)
            except OSError:
                break
            if not sub.isdigit():
                continue
            try:
                with winreg.OpenKey(root, sub) as key:
                    name = _value(key, "DriverDesc") or "Graphics card"
                    vram = _memory(key)
            except OSError:
                continue
            if vram:
                found.append(Gpu(str(name), vram))
    return sorted(found, key=lambda g: -g.vram)


def _value(key, name: str):
    import winreg

    try:
        return winreg.QueryValueEx(key, name)[0]
    except OSError:
        return None


def _memory(key) -> int:
    for name in ("HardwareInformation.qwMemorySize", "HardwareInformation.MemorySize"):
        value = _value(key, name)
        if isinstance(value, int) and value > 0:
            return value
        if isinstance(value, (bytes, bytearray)) and value:
            return int.from_bytes(value[:8], "little")
    return 0
