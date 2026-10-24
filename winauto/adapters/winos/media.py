"""Media keys and "what's playing" (Windows media session) for any player."""

from __future__ import annotations

import json

from winauto.adapters.winos import require_windows
from winauto.adapters.winos.shell import open_app_uri, open_url

MEDIA_KEYS = {"next": 0xB0, "previous": 0xB1, "stop": 0xB2, "play_pause": 0xB3}  # virtual-key codes

NOW_PLAYING_SCRIPT = r"""
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
Add-Type -AssemblyName System.Runtime.WindowsRuntime
$asTaskGeneric = ([System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object {
  $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1' })[0]
function Await($task, $type) {
  $t = $asTaskGeneric.MakeGenericMethod($type).Invoke($null, @($task)); $t.Wait(-1) | Out-Null; $t.Result }
[Windows.Media.Control.GlobalSystemMediaTransportControlsSessionManager, Windows.Media.Control, ContentType=WindowsRuntime] | Out-Null
$mgr = Await ([Windows.Media.Control.GlobalSystemMediaTransportControlsSessionManager]::RequestAsync()) ([Windows.Media.Control.GlobalSystemMediaTransportControlsSessionManager])
$s = $mgr.GetCurrentSession()
if (-not $s) { Write-Output '{}'; exit }
$p = Await ($s.TryGetMediaPropertiesAsync()) ([Windows.Media.Control.GlobalSystemMediaTransportControlsSessionMediaProperties])
$info = $s.GetPlaybackInfo()
@{ title = $p.Title; artist = $p.Artist; album = $p.AlbumTitle; app = $s.SourceAppUserModelId; status = "$($info.PlaybackStatus)" } | ConvertTo-Json -Compress
"""


class WindowsMedia:
    def control(self, action: str) -> None:
        """action: play_pause, next, previous or stop."""
        require_windows("Media keys")
        from winauto.adapters.winos.system import press_key

        press_key(MEDIA_KEYS[action])

    def now_playing(self) -> dict[str, str]:
        from winauto.adapters.winos.powershell import run_powershell

        r = run_powershell(NOW_PLAYING_SCRIPT, timeout=20)
        try:
            return json.loads(r.stdout.strip() or "{}")
        except ValueError:
            return {}

    def open(self, target: str) -> None:
        if target.startswith("spotify:"):
            if not open_app_uri(target):
                raise OSError("Spotify isn't installed.")
        else:
            open_url(target)
