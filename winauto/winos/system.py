"""Volume, brightness, theme, power, radios, battery, recycle bin."""

from __future__ import annotations

import ctypes
import logging
import os
import time

from winauto.winos import require_windows, run_hidden
from winauto.winos.powershell import run_powershell

log = logging.getLogger(__name__)

VK_VOLUME_MUTE, VK_VOLUME_DOWN, VK_VOLUME_UP = 0xAD, 0xAE, 0xAF
KEYEVENTF_KEYUP = 0x2


def press_key(vk: int, times: int = 1) -> None:
    user32 = ctypes.windll.user32
    for _ in range(times):
        user32.keybd_event(vk, 0, 0, 0)
        user32.keybd_event(vk, 0, KEYEVENTF_KEYUP, 0)


class WindowsSystem:
    # ----- volume -----

    def _endpoint(self):
        import comtypes
        from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume

        try:
            comtypes.CoInitialize()  # needed on each worker thread
        except OSError:
            pass
        speakers = AudioUtilities.GetSpeakers()
        if hasattr(speakers, "EndpointVolume"):  # pycaw >= 2024
            return speakers.EndpointVolume
        from ctypes import POINTER, cast

        iface = speakers.Activate(IAudioEndpointVolume._iid_, comtypes.CLSCTX_ALL, None)
        return cast(iface, POINTER(IAudioEndpointVolume))

    def get_volume(self) -> tuple[int, bool]:
        require_windows("Volume control")
        vol = self._endpoint()
        return round(vol.GetMasterVolumeLevelScalar() * 100), bool(vol.GetMute())

    def set_volume(self, percent: int) -> None:
        require_windows("Volume control")
        percent = max(0, min(100, percent))
        try:
            vol = self._endpoint()
            vol.SetMasterVolumeLevelScalar(percent / 100, None)
            if percent > 0 and vol.GetMute():
                vol.SetMute(0, None)
        except Exception:
            log.info("pycaw unavailable, using volume keys", exc_info=True)
            press_key(VK_VOLUME_DOWN, 50)  # each press is 2%
            press_key(VK_VOLUME_UP, round(percent / 2))

    def set_mute(self, mute: bool) -> None:
        require_windows("Volume control")
        try:
            self._endpoint().SetMute(1 if mute else 0, None)
        except Exception:
            press_key(VK_VOLUME_MUTE)

    # ----- brightness (laptop screens) -----

    def get_brightness(self) -> int:
        require_windows("Brightness")
        r = run_powershell("(Get-CimInstance -Namespace root/WMI -ClassName WmiMonitorBrightness).CurrentBrightness")
        if r.returncode != 0 or not r.stdout.strip():
            raise RuntimeError("This screen doesn't support brightness control (usually only laptop screens do).")
        return int(r.stdout.split()[0])

    def set_brightness(self, percent: int) -> None:
        require_windows("Brightness")
        percent = max(0, min(100, percent))
        script = (
            "$m = Get-CimInstance -Namespace root/WMI -ClassName WmiMonitorBrightnessMethods; "
            f"Invoke-CimMethod -InputObject $m -MethodName WmiSetBrightness -Arguments @{{Timeout=1; Brightness={percent}}} | Out-Null"
        )
        r = run_powershell(script)
        if r.returncode != 0:
            raise RuntimeError("This screen doesn't support brightness control (usually only laptop screens do).")

    # ----- theme -----

    def set_dark_mode(self, dark: bool) -> None:
        require_windows("Dark mode")
        import winreg

        path = r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize"
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, path, 0, winreg.KEY_SET_VALUE) as key:
            value = 0 if dark else 1
            winreg.SetValueEx(key, "AppsUseLightTheme", 0, winreg.REG_DWORD, value)
            winreg.SetValueEx(key, "SystemUsesLightTheme", 0, winreg.REG_DWORD, value)
        # Tell open apps the theme changed.
        result = ctypes.c_ulong()
        ctypes.windll.user32.SendMessageTimeoutW(
            0xFFFF, 0x001A, 0, ctypes.c_wchar_p("ImmersiveColorSet"), 0x0002, 200, ctypes.byref(result)
        )

    def is_dark_mode(self) -> bool:
        require_windows("Dark mode")
        import winreg

        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize"
        ) as key:
            return winreg.QueryValueEx(key, "AppsUseLightTheme")[0] == 0

    # ----- power -----

    def lock(self) -> None:
        require_windows("Locking")
        if not ctypes.windll.user32.LockWorkStation():
            raise RuntimeError("Windows refused to lock.")

    def sleep(self) -> None:
        require_windows("Sleep")
        ctypes.windll.powrprof.SetSuspendState(0, 1, 0)

    def shutdown(self, kind: str, delay_seconds: int = 0) -> None:
        require_windows("Shutting down")
        flags = {"shutdown": ["/s", "/hybrid"], "restart": ["/r"], "signout": ["/l"]}[kind]
        args = ["shutdown", *flags]
        if kind != "signout":
            args += ["/t", str(max(0, delay_seconds))]
        r = run_hidden(args)
        if r.returncode != 0 and "/hybrid" in args:  # fast startup off: plain shutdown
            r = run_hidden(["shutdown", "/s", "/t", str(max(0, delay_seconds))])
        if r.returncode != 0:
            raise RuntimeError(r.stderr.strip() or r.stdout.strip() or "shutdown failed")

    def cancel_shutdown(self) -> bool:
        require_windows("Shutting down")
        return run_hidden(["shutdown", "/a"]).returncode == 0

    # ----- radios -----

    def set_radio(self, kind: str, on: bool) -> None:
        """kind: 'WiFi' or 'Bluetooth'. Uses the same switch as Quick Settings."""
        require_windows("Wi-Fi/Bluetooth")
        state = "On" if on else "Off"
        script = r"""
Add-Type -AssemblyName System.Runtime.WindowsRuntime
$asTaskGeneric = ([System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object {
  $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1' })[0]
function Await($task, $type) {
  $t = $asTaskGeneric.MakeGenericMethod($type).Invoke($null, @($task)); $t.Wait(-1) | Out-Null; $t.Result }
[Windows.Devices.Radios.Radio, Windows.System.Devices, ContentType=WindowsRuntime] | Out-Null
[Windows.Devices.Radios.RadioAccessStatus, Windows.System.Devices, ContentType=WindowsRuntime] | Out-Null
Await ([Windows.Devices.Radios.Radio]::RequestAccessAsync()) ([Windows.Devices.Radios.RadioAccessStatus]) | Out-Null
$radios = Await ([Windows.Devices.Radios.Radio]::GetRadiosAsync()) ([System.Collections.Generic.IReadOnlyList[Windows.Devices.Radios.Radio]])
$radio = $radios | Where-Object { $_.Kind -eq '__KIND__' } | Select-Object -First 1
if (-not $radio) { Write-Output 'NO_RADIO'; exit 3 }
[Windows.Devices.Radios.RadioState, Windows.System.Devices, ContentType=WindowsRuntime] | Out-Null
$r = Await ($radio.SetStateAsync('__STATE__')) ([Windows.Devices.Radios.RadioAccessStatus])
Write-Output $r
""".replace("__KIND__", kind).replace("__STATE__", state)
        r = run_powershell(script, timeout=30)
        out = r.stdout.strip()
        if "NO_RADIO" in out:
            raise RuntimeError(f"No {kind} adapter found.")
        if r.returncode != 0 or (out and "Allowed" not in out):
            raise RuntimeError(f"Windows didn't allow changing {kind} ({out or r.stderr.strip()[:200]}).")

    # ----- misc -----

    def open_uri(self, uri: str) -> None:
        require_windows("Opening settings")
        os.startfile(uri)  # type: ignore[attr-defined]

    def recycle_bin(self) -> tuple[int, int]:
        """(item count, total bytes)."""
        require_windows("Recycle Bin")

        class SHQUERYRBINFO(ctypes.Structure):
            _fields_ = [("cbSize", ctypes.c_ulong), ("i64Size", ctypes.c_longlong), ("i64NumItems", ctypes.c_longlong)]

        info = SHQUERYRBINFO()
        info.cbSize = ctypes.sizeof(info)
        ctypes.windll.shell32.SHQueryRecycleBinW(None, ctypes.byref(info))
        return int(info.i64NumItems), int(info.i64Size)

    def empty_recycle_bin(self) -> None:
        require_windows("Recycle Bin")
        # SHERB_NOCONFIRMATION | SHERB_NOPROGRESSUI | SHERB_NOSOUND
        hr = ctypes.windll.shell32.SHEmptyRecycleBinW(None, None, 0x7)
        if hr not in (0, -2147418113):  # S_OK, or E_UNEXPECTED when already empty
            raise RuntimeError(f"Windows couldn't empty the Recycle Bin (code {hr}).")

    def uptime_seconds(self) -> float:
        import psutil

        return time.time() - psutil.boot_time()
