"""Speaking text with Windows' built-in offline voices (System.Speech via PowerShell)."""

from __future__ import annotations

import base64
import subprocess

from winauto.adapters.winos import CREATE_NO_WINDOW, IS_WINDOWS, NotOnWindows


class Speaker:
    def __init__(self) -> None:
        self._proc: subprocess.Popen | None = None

    def say(self, text: str) -> None:
        if not IS_WINDOWS:
            raise NotOnWindows("Reading aloud")
        self.stop()
        script = (
            "Add-Type -AssemblyName System.Speech; "
            "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer; $s.Rate = 1; "
            "$t = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('"
            + base64.b64encode(text.encode("utf-8")).decode("ascii") + "')); $s.Speak($t)"
        )
        encoded = base64.b64encode(script.encode("utf-16-le")).decode("ascii")
        self._proc = subprocess.Popen(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-EncodedCommand", encoded],
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            creationflags=CREATE_NO_WINDOW,
        )

    def stop(self) -> bool:
        if self._proc and self._proc.poll() is None:
            self._proc.terminate()
            self._proc = None
            return True
        return False
