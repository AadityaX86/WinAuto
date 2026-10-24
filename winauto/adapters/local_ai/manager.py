"""The built-in AI: installs the engine and a model into one folder, and runs them on demand.

    root/
      engine/<version>/llama-server.exe (+ DLLs)
      models/<model id>/<weights>.gguf, <vision projector>.gguf
      downloads/                         partial downloads, resumed next time
      logs/engine.log
"""

from __future__ import annotations

import logging
import shutil
import tarfile
import threading
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from winauto.adapters.local_ai import catalog
from winauto.adapters.local_ai.catalog import Engine, Model, RemoteFile
from winauto.adapters.local_ai.download import Cancelled, DownloadError, download
from winauto.adapters.local_ai.server import EngineError, LlamaServer

log = logging.getLogger(__name__)

# States, in the order a first run goes through them.
MISSING, DOWNLOADING, INSTALLED, STARTING, READY, ERROR = "missing", "downloading", "installed", "starting", "ready", "error"


@dataclass
class Status:
    state: str
    message: str
    done: int = 0  # bytes downloaded so far (while downloading)
    total: int = 0

    @property
    def fraction(self) -> float:
        return self.done / self.total if self.total else 0.0


def gb(n: int) -> str:
    return f"{n / 1e9:.1f} GB"


class LocalAI:
    def __init__(self, root: Path, model_id: str, *, engine: Engine | None = None,
                 downloader: Callable = download, server_factory: Callable[..., LlamaServer] = LlamaServer,
                 on_server_started: Callable[[int], None] | None = None):
        self.root = root
        self.engine = engine if engine is not None else catalog.engine()
        self.model = catalog.model(model_id) or catalog.model(catalog.DEFAULT_MODEL)
        self._download = downloader
        self._server_factory = server_factory
        self._on_server_started = on_server_started
        self._server: LlamaServer | None = None
        self._lock = threading.RLock()
        self._status: Status | None = None  # set while downloading/starting or after an error
        self._listeners: list[Callable[[Status], None]] = []

    # ----- where things go -----

    def _engine_dir(self) -> Path:
        assert self.engine is not None
        return self.root / "engine" / self.engine.version

    def _model_path(self, f: RemoteFile, model: Model | None = None) -> Path:
        return self.root / "models" / (model or self.model).id / f.name

    def executable(self) -> Path | None:
        if self.engine is None:
            return None
        folder = self._engine_dir()
        if not (folder / ".complete").exists():
            return None
        found = next(folder.rglob(self.engine.executable), None)
        return found

    # ----- status -----

    def subscribe(self, listener: Callable[[Status], None]) -> None:
        self._listeners.append(listener)

    def _set(self, status: Status | None) -> None:
        self._status = status
        current = self.status()
        for listener in list(self._listeners):
            try:
                listener(current)
            except Exception:
                log.exception("status listener failed")

    def installed(self, model: Model | None = None) -> bool:
        model = model or self.model
        return self.executable() is not None and all(
            (p := self._model_path(f, model)).exists() and p.stat().st_size == f.size for f in model.files)

    def missing_bytes(self, model: Model | None = None) -> int:
        model = model or self.model
        total = 0 if self.executable() is not None or self.engine is None else self.engine.archive.size
        for f in model.files:
            p = self._model_path(f, model)
            if not (p.exists() and p.stat().st_size == f.size):
                part = p.with_name(p.name + ".part")
                total += f.size - (part.stat().st_size if part.exists() else 0)
        return total

    def status(self) -> Status:
        if self._status is not None:
            return self._status
        if self._server is not None and self._server.alive():
            return Status(READY, f"{self.model.name} is ready.")
        if self.engine is None:
            return Status(ERROR, "The built-in AI isn't available on this system. Use Ollama instead (Settings → AI model).")
        if self.installed():
            return Status(INSTALLED, f"{self.model.name} is downloaded.")
        return Status(MISSING, f"The AI model needs a one-time download ({gb(self.missing_bytes())}).")

    # ----- installing -----

    def install(self, cancel: threading.Event | None = None) -> None:
        """Download whatever is missing (engine, model, vision file). Raises DownloadError or Cancelled."""
        if self.engine is None:
            raise DownloadError("The built-in AI isn't available on this system.")
        model = self.model
        total = self.missing_bytes(model)
        done = 0

        def progress_for(base: int) -> Callable[[int, int], None]:
            def report(n: int, _size: int) -> None:
                self._set(Status(DOWNLOADING, f"Downloading the AI model… {gb(base + n)} of {gb(total)}",
                                 base + n, total))
            return report

        try:
            self._set(Status(DOWNLOADING, f"Downloading the AI model… 0.0 of {gb(total)}", 0, total))
            if self.executable() is None:
                archive = self.root / "downloads" / self.engine.archive.name
                self._download(self.engine.archive.url, archive, self.engine.archive.sha256, self.engine.archive.size,
                               progress_for(done), cancel)
                self._extract(archive, self._engine_dir())
                archive.unlink(missing_ok=True)
                done += self.engine.archive.size
            for f in model.files:
                dest = self._model_path(f, model)
                if dest.exists() and dest.stat().st_size == f.size:
                    continue
                part = dest.with_name(dest.name + ".part")
                already = part.stat().st_size if part.exists() else 0
                self._download(f.url, dest, f.sha256, f.size, progress_for(done - already), cancel)
                done += f.size - already
        except (DownloadError, OSError) as exc:
            if isinstance(exc, Cancelled):
                self._set(None)
                raise
            message = str(exc) if isinstance(exc, DownloadError) else f"Couldn't save the AI files: {exc}"
            self._set(Status(ERROR, message))
            raise DownloadError(message) from exc
        self._set(None)

    def _extract(self, archive: Path, dest: Path) -> None:
        tmp = dest.with_name(dest.name + ".tmp")
        shutil.rmtree(tmp, ignore_errors=True)
        tmp.mkdir(parents=True)
        if archive.name.endswith(".zip"):
            with zipfile.ZipFile(archive) as z:
                z.extractall(tmp)
        else:
            with tarfile.open(archive) as t:
                try:
                    t.extractall(tmp, filter="data")
                except TypeError:  # Python without extraction filters
                    t.extractall(tmp)  # noqa: S202 - pinned, checksum-verified archive
        shutil.rmtree(dest, ignore_errors=True)
        tmp.rename(dest)
        (dest / ".complete").write_text(self.engine.version if self.engine else "", encoding="utf-8")

    def remove_other_models(self) -> int:
        """Delete downloaded models other than the current one. Returns bytes freed."""
        freed = 0
        models = self.root / "models"
        if not models.exists():
            return 0
        for folder in models.iterdir():
            if folder.is_dir() and folder.name != self.model.id:
                freed += sum(p.stat().st_size for p in folder.rglob("*") if p.is_file())
                shutil.rmtree(folder, ignore_errors=True)
        return freed

    # ----- running -----

    def set_model(self, model_id: str) -> None:
        new = catalog.model(model_id)
        if new is None or new.id == self.model.id:
            return
        with self._lock:
            self.stop()
            self.model = new
            self._set(None)

    def ensure_running(self) -> LlamaServer:
        """Start the engine with the model if it isn't running. Raises EngineError."""
        with self._lock:
            if self._server is not None and self._server.alive():
                return self._server
            exe = self.executable()
            if exe is None or not self.installed():
                raise EngineError(self.status().message)
            self._set(Status(STARTING, f"Loading {self.model.name}…"))
            errors = []
            for gpu in (True, False):  # if the graphics card fails, fall back to the CPU
                server = self._server_factory(
                    exe, self._model_path(self.model.weights),
                    self.root / "logs" / "engine.log",
                    vision=self._model_path(self.model.vision) if self.model.vision else None,
                    context=self.model.context, gpu=gpu, on_started=self._on_server_started,
                )
                try:
                    server.start()
                except EngineError as exc:
                    log.warning("AI engine failed to start (gpu=%s): %s", gpu, exc)
                    errors.append(str(exc))
                    continue
                self._server = server
                self._set(None)
                return server
            self._set(Status(ERROR, errors[-1] if errors else "The AI engine couldn't start."))
            raise EngineError(self._status.message if self._status else "The AI engine couldn't start.")

    def stop(self) -> None:
        with self._lock:
            server, self._server = self._server, None
            if server is not None:
                server.stop()
            if self._status is not None and self._status.state in (READY, STARTING):
                self._status = None
