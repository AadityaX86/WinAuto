"""The built-in AI: downloads, model choice, engine process and first-run setup (no network)."""

from __future__ import annotations

import hashlib
import io
import threading
import zipfile
from pathlib import Path

import pytest

from winauto.adapters.local_ai import catalog
from winauto.adapters.local_ai.catalog import Engine, Model, RemoteFile
from winauto.adapters.local_ai.download import Cancelled, DownloadError, download
from winauto.adapters.local_ai.manager import DOWNLOADING, ERROR, INSTALLED, MISSING, READY, LocalAI
from winauto.adapters.local_ai.server import EngineError, LlamaServer
from winauto.adapters.winos.hardware import Gpu
from winauto.config import CONFIG_VERSION, Config

# ---------------- downloads ----------------


class FakeResponse(io.BytesIO):
    def __init__(self, data: bytes, status: int = 200):
        super().__init__(data)
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


def opener_for(data: bytes, ranges: bool = True, fail_after: int | None = None, calls: list | None = None):
    def open_(req, timeout=60):
        rng = req.headers.get("Range")
        if calls is not None:
            calls.append(rng)
        start = int(rng.split("=")[1].rstrip("-")) if rng and ranges else 0
        body = data[start:]
        if fail_after is not None and len(calls or []) == 1:
            body = body[:fail_after]  # connection drops early on the first try
        return FakeResponse(body, 206 if rng and ranges else 200)

    return open_


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def test_download_verifies_and_resumes(tmp_path, monkeypatch):
    monkeypatch.setattr("winauto.adapters.local_ai.download._sleep", lambda s, c: None)
    data = bytes(range(256)) * 4096  # 1 MiB
    dest = tmp_path / "m.gguf"
    calls: list = []
    seen = []
    download("https://x/m.gguf", dest, sha(data), len(data), progress=lambda d, t: seen.append(d),
             opener=opener_for(data, fail_after=300_000, calls=calls))
    assert dest.read_bytes() == data
    assert calls == [None, "bytes=300000-"]  # second try continued where the first stopped
    assert seen[-1] == len(data)
    # already there: nothing is fetched
    download("https://x/m.gguf", dest, sha(data), len(data), opener=lambda *a, **k: pytest.fail("fetched again"))


def test_download_rejects_damaged_files(tmp_path):
    data = b"a" * 1000
    with pytest.raises(DownloadError, match="damaged"):
        download("https://x/f", tmp_path / "f", sha(b"b" * 1000), 1000, opener=opener_for(data))
    assert not (tmp_path / "f").exists() and not (tmp_path / "f.part").exists()


def test_download_checks_disk_space_and_can_cancel(tmp_path, monkeypatch):
    monkeypatch.setattr("winauto.adapters.local_ai.download.free_space", lambda folder: 10)
    with pytest.raises(DownloadError, match="Not enough free disk space"):
        download("https://x/f", tmp_path / "f", "0" * 64, 5_000_000_000, opener=opener_for(b""))
    monkeypatch.undo()
    cancel = threading.Event()
    cancel.set()
    with pytest.raises(Cancelled):
        download("https://x/f", tmp_path / "g", sha(b"x" * 10), 10, cancel=cancel, opener=opener_for(b"x" * 10))


# ---------------- catalog ----------------


def test_catalog_is_pinned_and_recommends_by_hardware():
    for m in catalog.MODELS + [catalog.TEST_MODEL]:
        for f in m.files:
            assert f.url.startswith("https://huggingface.co/") and len(f.sha256) == 64 and f.size > 100_000_000
    for e in catalog.ENGINES.values():
        assert e.archive.url.startswith("https://github.com/ggml-org/llama.cpp/releases/download/")
        assert len(e.archive.sha256) == 64
    assert catalog.MODELS[0].vision and catalog.MODELS[1].vision  # every user model understands images
    assert catalog.recommend(12).id == "qwen3-vl-8b"
    assert catalog.recommend(8).id == "qwen3-vl-8b"
    assert catalog.recommend(6).id == "qwen3-vl-4b"
    assert catalog.recommend(1).id == "qwen3-vl-4b"
    assert catalog.recommend(None, ram_gb=32).id == "qwen3-vl-8b"
    assert catalog.recommend(None, ram_gb=8).id == "qwen3-vl-4b"
    assert catalog.engine("win32").executable == "llama-server.exe"
    assert catalog.engine("darwin") is None


# ---------------- engine process ----------------


def test_server_command_is_local_and_keyed(tmp_path):
    s = LlamaServer(Path("llama-server.exe"), Path("m.gguf"), tmp_path / "log.txt", vision=Path("v.gguf"), port=5000)
    cmd = s.command()
    assert cmd[cmd.index("--host") + 1] == "127.0.0.1"
    assert cmd[cmd.index("--api-key") + 1] == s.api_key and len(s.api_key) > 20
    assert cmd[cmd.index("--mmproj") + 1] == "v.gguf"
    assert "--jinja" in cmd and cmd[cmd.index("--reasoning-budget") + 1] == "0"
    assert cmd[cmd.index("--fit") + 1] == "on"
    assert cmd[cmd.index("--chat-template-kwargs") + 1] == '{"enable_thinking": false}'
    cpu = LlamaServer(Path("x"), Path("m"), tmp_path / "l", gpu=False, port=5001).command()
    assert cpu[cpu.index("--n-gpu-layers") + 1] == "0" and "--fit" not in cpu
    assert s.base_url == "http://127.0.0.1:5000/v1"


class FakeProc:
    pid = 4242

    def __init__(self, exits: bool):
        self.exits = exits
        self.stopped = False

    def poll(self):
        return 1 if self.exits or self.stopped else None

    def terminate(self):
        self.stopped = True

    def wait(self, timeout=None):
        return 0


def test_server_start_reports_crash_with_log(tmp_path):
    def popen(cmd, **kw):
        kw["stdout"].write("error: out of device memory\n")
        return FakeProc(exits=True)

    s = LlamaServer(Path("x"), Path("m"), tmp_path / "log.txt", popen=popen, port=5002)
    with pytest.raises(EngineError, match="out of device memory"):
        s.start(timeout=5)


# ---------------- installing and running ----------------


def make_zip() -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("llama-server.exe", b"MZ fake")
        z.writestr("ggml-vulkan.dll", b"dll")
    return buf.getvalue()


ZIP = make_zip()
WEIGHTS, VISION = b"w" * 5000, b"v" * 3000
ENGINE = Engine("b1", RemoteFile("https://github.com/ggml-org/llama.cpp/releases/download/b1/llama-win.zip",
                                 len(ZIP), sha(ZIP)), "llama-server.exe")
MODEL = Model("tiny-vl", "Tiny VL", "Tiny", "test",
              RemoteFile("https://huggingface.co/x/y/resolve/main/tiny.gguf", len(WEIGHTS), sha(WEIGHTS)),
              RemoteFile("https://huggingface.co/x/y/resolve/main/mmproj-tiny.gguf", len(VISION), sha(VISION)))
FILES = {ENGINE.archive.url: ZIP, MODEL.weights.url: WEIGHTS, MODEL.vision.url: VISION}


def fake_download(url, dest, sha256, size, progress=None, cancel=None):
    if cancel is not None and cancel.is_set():
        raise Cancelled()
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(FILES[url])
    if progress:
        progress(size, size)
    return dest


class FakeServer:
    instances: list = []

    def __init__(self, exe, model, log_path, vision=None, context=8192, gpu=True, on_started=None):
        self.exe, self.model, self.vision, self.gpu = exe, model, vision, gpu
        self.base_url, self.api_key = "http://127.0.0.1:9/v1", "k"
        self.running = False
        FakeServer.instances.append(self)

    def start(self):
        if self.gpu and FakeServer.fail_gpu:
            raise EngineError("GPU out of memory")
        self.running = True

    def alive(self):
        return self.running

    def stop(self):
        self.running = False


@pytest.fixture
def ai(tmp_path, monkeypatch):
    monkeypatch.setattr(catalog, "MODELS", [MODEL])
    monkeypatch.setattr(catalog, "DEFAULT_MODEL", MODEL.id)
    FakeServer.instances, FakeServer.fail_gpu = [], False
    return LocalAI(tmp_path / "ai", MODEL.id, engine=ENGINE, downloader=fake_download, server_factory=FakeServer)


def test_install_then_run_with_cpu_fallback(ai):
    states = []
    ai.subscribe(lambda st: states.append(st.state))
    assert ai.status().state == MISSING and ai.missing_bytes() == len(ZIP) + len(WEIGHTS) + len(VISION)
    ai.install()
    assert DOWNLOADING in states and ai.status().state == INSTALLED and ai.installed()
    assert ai.executable().name == "llama-server.exe" and ai.missing_bytes() == 0
    FakeServer.fail_gpu = True
    server = ai.ensure_running()
    assert [s.gpu for s in FakeServer.instances] == [True, False]  # GPU failed, CPU worked
    assert server.vision.name == "mmproj-tiny.gguf" and ai.status().state == READY
    assert ai.ensure_running() is server  # already running
    ai.stop()
    assert not server.running and ai.status().state == INSTALLED


def test_running_before_download_explains(ai):
    with pytest.raises(EngineError, match="one-time download"):
        ai.ensure_running()


def test_failed_download_shows_error(ai):
    def broken(url, dest, sha256, size, progress=None, cancel=None):
        raise DownloadError("Download failed: no internet.")

    ai._download = broken
    with pytest.raises(DownloadError):
        ai.install()
    assert ai.status().state == ERROR and "no internet" in ai.status().message


def test_builtin_client_messages(ai):
    from winauto.adapters.llm.builtin import BuiltinClient
    from winauto.core.llm import LLMError

    client = BuiltinClient(ai)
    ok, msg = client.check()
    assert not ok and "one-time download" in msg
    with pytest.raises(LLMError, match="isn't downloaded yet"):
        client.chat([{"role": "user", "content": "hi"}], [])
    ai._set(ai.status().__class__(DOWNLOADING, "", 50, 100))
    with pytest.raises(LLMError, match="still downloading \\(50%\\)"):
        client.chat([{"role": "user", "content": "hi"}], [])
    ai._set(None)
    ai.install()
    ok, msg = client.check()
    assert ok and "Tiny VL" in msg


def test_builtin_client_streams_with_a_length_cap(ai, monkeypatch):
    """Always streamed and capped, so a slow or rambling answer can't tie up the engine."""
    from winauto.adapters.llm import builtin
    from winauto.core.llm import LLMError, LLMReply

    seen = {}

    class FakeClient:
        def __init__(self, **kwargs):
            seen["init"] = kwargs

        def chat(self, messages, tools, on_token=None):
            seen["on_token"] = on_token
            if messages[-1]["content"] == "slow":
                raise LLMError("The AI model took too long to answer.")
            return LLMReply(content="Paris.")

    monkeypatch.setattr(builtin, "OpenAICompatClient", FakeClient)
    ai.install()
    client = builtin.BuiltinClient(ai)
    assert client.chat([{"role": "user", "content": "capital of france?"}], []).content == "Paris."
    assert seen["init"]["max_tokens"] == builtin.MAX_ANSWER_TOKENS and callable(seen["on_token"])
    with pytest.raises(LLMError, match="small model in Settings"):
        client.chat([{"role": "user", "content": "slow"}], [])


# ---------------- first-run setup service ----------------


class Store(dict):
    def get_value(self, key, default=None):
        return self.get(key, default)

    def set_value(self, key, value):
        self[key] = value


def test_setup_picks_model_downloads_and_loads(ai, monkeypatch):
    from winauto.services.ai_setup import AISetup

    monkeypatch.setattr(catalog, "MODELS", [MODEL])
    cfg = Config()
    saved = []

    def apply(new):
        saved.append(new.llm.builtin_model)
        cfg.llm.builtin_model = new.llm.builtin_model

    store = Store()
    notes = []
    setup = AISetup(ai, lambda: cfg, apply, store=store, gpus=lambda: [Gpu("RTX", 12 * 1024**3)], ram=lambda: 0,
                    notify=lambda title, message: notes.append((title, message)))
    assert setup.needed() and setup.view().action == "resume"
    assert setup.hardware() == "RTX · 12 GB graphics memory"
    assert setup.start()
    setup._thread.join(5)
    assert saved == ["tiny-vl"] and ai.installed() and ai.status().state == READY
    # A desktop notification says so, in case the popup is closed.
    assert notes == [("Your AI is ready", "Press Ctrl+Alt+Space and ask anything. It runs entirely on this PC.")]
    view = setup.view()
    assert view.visible and view.title.startswith("✓") and view.dot is True
    setup.dismiss()
    assert not setup.view().visible and not setup.start()  # nothing left to do


def test_setup_pause_and_views(ai):
    from winauto.adapters.local_ai.manager import Status
    from winauto.services.ai_setup import AISetup

    cfg = Config()
    cfg.llm.builtin_model = MODEL.id
    store = Store()
    setup = AISetup(ai, lambda: cfg, lambda c: None, store=store, gpus=lambda: [], ram=lambda: 0)
    setup.pause()
    assert setup.paused and not setup.start()  # paused: not started on its own
    v = setup.view()
    assert v.title == "AI download paused" and v.action == "resume"
    v = setup.view(Status(DOWNLOADING, "", 1_000_000_000, 4_000_000_000))
    assert v.progress == 0.25 and v.action == "pause" and v.dot_label == "Downloading AI · 25%"
    v = setup.view(Status(ERROR, "Not enough free disk space.\nmore"))
    assert v.message == "Not enough free disk space." and v.action == "retry"
    cfg.llm.backend = "ollama"
    assert not setup.view().visible and not setup.needed()


def test_old_settings_switch_to_builtin_unless_ollama_runs():
    from winauto.services.ai_setup import upgrade_config

    old = Config()
    old.config_version, old.llm.backend = 1, "ollama"
    assert upgrade_config(old, lambda: False) and old.llm.backend == "builtin" and old.config_version == CONFIG_VERSION
    keep = Config()
    keep.config_version, keep.llm.backend = 1, "ollama"
    assert upgrade_config(keep, lambda: True) and keep.llm.backend == "ollama"
    assert not upgrade_config(Config(), lambda: pytest.fail("not needed"))


def test_old_config_file_is_marked(tmp_path):
    import json

    from winauto.config import load_config

    p = tmp_path / "config.json"
    p.write_text(json.dumps({"llm": {"backend": "ollama"}}), encoding="utf-8")
    cfg = load_config(p)
    assert cfg.config_version == 1 and cfg.llm.backend == "ollama"
    assert Config().llm.backend == "builtin" and Config().config_version == CONFIG_VERSION


def test_hardware_is_empty_off_windows():
    import sys

    from winauto.adapters.winos.hardware import gpus

    if sys.platform != "win32":
        assert gpus() == []
    else:
        assert all(g.vram > 0 for g in gpus())
