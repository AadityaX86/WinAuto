"""Getting the built-in AI ready: picking a model for this PC and downloading it in the background."""

from __future__ import annotations

import copy
import logging
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable

from winauto.adapters.local_ai import catalog
from winauto.adapters.local_ai.catalog import Model
from winauto.adapters.local_ai.download import Cancelled, DownloadError
from winauto.adapters.local_ai.manager import DOWNLOADING, ERROR, MISSING, READY, STARTING, LocalAI, Status, gb
from winauto.adapters.local_ai.server import EngineError
from winauto.config import CONFIG_VERSION, Config

log = logging.getLogger(__name__)

PAUSED_KEY = "ai_download_paused"


@dataclass
class SetupView:
    """What the popup shows about the built-in AI: a card on the home screen and the status dot."""

    visible: bool = False
    title: str = ""
    message: str = ""
    progress: float | None = None  # 0..1, -1 for "busy" without a percentage, None for no bar
    detail: str = ""
    action: str = ""  # "pause", "resume", "retry" or "" (no button)
    action_label: str = ""
    dot: bool | None = None  # status dot: None = working on it, True = ready, False = problem
    dot_label: str = ""
    hide_after_ms: int = 0


@dataclass
class ModelChoice:
    model: Model
    installed: bool
    recommended: bool

    @property
    def label(self) -> str:
        text = f"{self.model.name} · {gb(self.model.size)}"
        return text + (" · downloaded" if self.installed else " · best for this PC" if self.recommended else "")


class AISetup:
    def __init__(self, ai: LocalAI, get_config: Callable[[], Config], apply_config: Callable[[Config], None],
                 store: Any = None, gpus: Callable[[], list] | None = None, ram: Callable[[], int] | None = None,
                 notify: Callable[[str, str], None] | None = None):
        self.ai = ai
        self._notify = notify  # desktop notification (title, message), e.g. when the download is done
        self._get_config = get_config
        self._apply_config = apply_config
        self._store = store
        self._gpus = gpus or _default_gpus
        self._ram = ram or _default_ram
        self._thread: threading.Thread | None = None
        self._cancel = threading.Event()
        self._celebrate = False  # show "ready" once after a download
        self._samples: list[tuple[float, int]] = []  # (time, bytes) for the speed estimate

    # ----- state -----

    @property
    def active(self) -> bool:
        """True when WinAuto is set to use the built-in AI."""
        return self._get_config().llm.backend == "builtin"

    @property
    def downloading(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    @property
    def paused(self) -> bool:
        return self._store is not None and self._store.get_value(PAUSED_KEY) == "1"

    def needed(self) -> bool:
        return self.active and not self.ai.installed()

    def status(self) -> Status:
        return self.ai.status()

    def subscribe(self, listener: Callable[[Status], None]) -> None:
        self.ai.subscribe(listener)

    # ----- choosing a model -----

    def hardware(self) -> str:
        """A short description of this PC's graphics card, e.g. 'NVIDIA GeForce RTX 3060 · 12 GB'."""
        gpus = self._gpus()
        if not gpus:
            return "No graphics card found; the AI will run on the processor."
        g = gpus[0]
        return f"{g.name} · {g.vram_gb:.0f} GB graphics memory"

    def recommended(self) -> Model:
        gpus = self._gpus()
        vram = gpus[0].vram_gb if gpus else None
        ram = self._ram()
        return catalog.recommend(vram, ram / 1024**3 if ram else None)

    def choices(self) -> list[ModelChoice]:
        best = self.recommended().id
        return [ModelChoice(m, self.ai.installed(m), m.id == best) for m in catalog.MODELS]

    # ----- downloading -----

    def start(self, user_asked: bool = False) -> bool:
        """Download what's missing in the background. Returns False if nothing was started.

        Starts on its own on first run, unless the user paused it; `user_asked` overrides that.
        """
        if not self.active or self.downloading or self.ai.installed():
            return False
        if self.paused and not user_asked:
            return False
        if self._store is not None:
            self._store.set_value(PAUSED_KEY, "0")
        cfg = self._get_config()
        if not cfg.llm.builtin_model:
            # First run: remember the model picked for this PC.
            new = copy.deepcopy(cfg)
            new.llm.builtin_model = self.recommended().id
            self._apply_config(new)
            self.ai.set_model(new.llm.builtin_model)
        self._cancel = threading.Event()
        self._thread = threading.Thread(target=self._run, args=(self._cancel,), daemon=True, name="ai-download")
        self._thread.start()
        return True

    def _run(self, cancel: threading.Event) -> None:
        self._samples = []
        try:
            self.ai.install(cancel)
            self._celebrate = True
            log.info("Built-in AI downloaded (%s)", self.ai.model.id)
            if self.load() and self._notify:  # ready straight away, no restart needed
                keys = "+".join(k.capitalize() for k in self._get_config().hotkey.split("+"))
                self._notify("Your AI is ready", f"Press {keys} and ask anything. It runs entirely on this PC.")
        except Cancelled:
            log.info("Built-in AI download paused")
        except DownloadError as exc:
            log.warning("Built-in AI download failed: %s", exc)

    def load(self) -> bool:
        """Start the engine with the downloaded model (slow: call it off the UI thread)."""
        if not self.active or not self.ai.installed():
            return False
        try:
            self.ai.ensure_running()
        except EngineError as exc:
            log.warning("Built-in AI couldn't start: %s", exc)
            return False
        return True

    def retry(self) -> None:
        """After an error: download again, or start the engine again."""
        if self.ai.installed():
            threading.Thread(target=self.load, daemon=True, name="ai-load").start()
        else:
            self.start(user_asked=True)

    def pause(self) -> None:
        """Stop the download; it continues from where it stopped next time."""
        if self._store is not None:
            self._store.set_value(PAUSED_KEY, "1")
        self._cancel.set()

    def dismiss(self) -> None:
        """The "ready" card has been seen."""
        self._celebrate = False

    # ----- what to show -----

    def view(self, status: Status | None = None) -> SetupView:
        if not self.active:
            return SetupView(dot_label="")
        st = status or self.status()
        label = self.ai.model.name
        if st.state == DOWNLOADING:
            pct = int(st.fraction * 100)
            return SetupView(
                True, "Setting up your private AI",
                f"Downloading {label} ({gb(st.total)}, only this once). Quick commands work meanwhile.",
                st.fraction, self._detail(st), "pause", "Pause", None, f"Downloading AI · {pct}%")
        if st.state == MISSING:
            size = gb(self.ai.missing_bytes())
            if self.paused:
                return SetupView(True, "AI download paused", f"{size} left. It continues from where it stopped.",
                                 None, "", "resume", "Continue", None, "AI download paused")
            return SetupView(True, "Your private AI needs a one-time download",
                             f"{label} ({size}) runs entirely on this PC. Quick commands work without it.",
                             None, "", "resume", "Download", False, "AI not downloaded")
        if st.state == ERROR:
            first = st.message.strip().splitlines()[0] if st.message.strip() else "Something went wrong."
            return SetupView(True, "The AI couldn't be set up", first, None, "", "retry", "Try again", False,
                             "AI problem")
        if st.state == STARTING:
            return SetupView(self._celebrate, "Loading your AI…", "This takes a few seconds the first time.",
                             -1, "", "", "", None, "Loading AI…")
        if st.state == READY:
            return SetupView(self._celebrate, "✓ Your private AI is ready",
                             "Ask anything, or try “what's on my screen?”.", None, "", "", "", True, label,
                             hide_after_ms=6000)
        # INSTALLED: downloaded, starts when first needed
        return SetupView(False, dot=None, dot_label=label)

    def _detail(self, st: Status) -> str:
        now = time.monotonic()
        self._samples = [(t, b) for t, b in self._samples if now - t < 15] + [(now, st.done)]
        text = f"{gb(st.done)} of {gb(st.total)}"
        (t0, b0), (t1, b1) = self._samples[0], self._samples[-1]
        if t1 - t0 >= 3 and b1 > b0:
            speed = (b1 - b0) / (t1 - t0)
            left = (st.total - st.done) / speed
            text += f" · {speed / 1e6:.0f} MB/s · " + (f"about {left / 60:.0f} min left" if left >= 90 else "less than 2 min left")
        return text


def upgrade_config(cfg: Config, ollama_ready: Callable[[], bool]) -> bool:
    """One-time change for settings written by WinAuto 0.1, which only knew Ollama.

    Keeps Ollama if it's set up and running; otherwise switches to the built-in AI.
    Returns True if `cfg` changed (the caller saves it).
    """
    if cfg.config_version >= CONFIG_VERSION:
        return False
    if cfg.llm.backend == "ollama" and not ollama_ready():
        cfg.llm.backend = "builtin"
    cfg.config_version = CONFIG_VERSION
    return True


def _default_gpus() -> list:
    from winauto.adapters.winos.hardware import gpus

    try:
        return gpus()
    except Exception:
        log.debug("couldn't read graphics cards", exc_info=True)
        return []


def _default_ram() -> int:
    from winauto.adapters.sysinfo import total_ram

    return total_ram()
