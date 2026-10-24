"""Running llama-server (llama.cpp) in the background, reachable only from this PC."""

from __future__ import annotations

import json
import logging
import secrets
import socket
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Callable

from winauto.adapters.winos import CREATE_NO_WINDOW

log = logging.getLogger(__name__)


class EngineError(Exception):
    """The AI engine couldn't start; the message is written for the user."""


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class LlamaServer:
    """One llama-server process serving one model on 127.0.0.1 with a random API key."""

    def __init__(self, executable: Path, model: Path, log_path: Path, *, vision: Path | None = None,
                 context: int = 8192, gpu: bool = True, port: int | None = None,
                 popen: Callable[..., subprocess.Popen] = subprocess.Popen,
                 on_started: Callable[[int], None] | None = None):
        self.executable = executable
        self.model = model
        self.vision = vision
        self.context = context
        self.gpu = gpu
        self.log_path = log_path
        self.port = port or free_port()
        # Without a key, any web page open in a browser could use the model through localhost.
        self.api_key = secrets.token_urlsafe(24)
        self._popen = popen
        self._on_started = on_started
        self._proc: subprocess.Popen | None = None

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.port}/v1"

    def command(self) -> list[str]:
        cmd = [
            str(self.executable),
            "--model", str(self.model),
            "--host", "127.0.0.1",
            "--port", str(self.port),
            "--api-key", self.api_key,
            "--alias", "winauto",
            "--ctx-size", str(self.context),
            "--parallel", "1",
            "--jinja",                 # the model's own chat template, needed for tool calls
            "--reasoning-budget", "0",  # answer straight away; no hidden "thinking"
        ]
        if self.vision:
            cmd += ["--mmproj", str(self.vision)]
        if self.gpu:
            cmd += ["--fit", "on"]       # use as much of the graphics card as fits, the rest on the CPU
        else:
            cmd += ["--n-gpu-layers", "0"]
        return cmd

    def alive(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    def start(self, timeout: float = 300.0) -> None:
        """Start the server and wait until the model is loaded. Raises EngineError."""
        if self.alive():
            return
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        log_file = open(self.log_path, "w", encoding="utf-8", errors="replace")
        try:
            self._proc = self._popen(
                self.command(), stdin=subprocess.DEVNULL, stdout=log_file, stderr=subprocess.STDOUT,
                cwd=str(self.executable.parent), creationflags=CREATE_NO_WINDOW,
            )
        except OSError as exc:
            log_file.close()
            raise EngineError(f"Couldn't start the AI engine: {exc}") from exc
        log_file.close()  # the child keeps its own handle
        if self._on_started:
            self._on_started(self._proc.pid)
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self._proc.poll() is not None:
                raise EngineError("The AI engine stopped while loading the model.\n" + self.log_tail())
            if self._healthy():
                log.info("AI engine ready on port %s (%s)", self.port, self.model.name)
                return
            time.sleep(0.5)
        self.stop()
        raise EngineError("The AI engine took too long to load the model.\n" + self.log_tail())

    def _healthy(self) -> bool:
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{self.port}/health", timeout=2) as resp:
                return json.loads(resp.read().decode("utf-8") or "{}").get("status") == "ok"
        except (urllib.error.URLError, OSError, ValueError):
            return False

    def stop(self) -> None:
        proc, self._proc = self._proc, None
        if proc is None or proc.poll() is not None:
            return
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()

    def log_tail(self, lines: int = 12) -> str:
        try:
            text = self.log_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return ""
        return "\n".join(text.strip().splitlines()[-lines:])
