"""Exactly which engine and model files the built-in AI downloads.

Everything is pinned (URL, size, SHA-256), so every PC gets the same, verified
files. To update: change the values here (sizes and hashes are on the files'
GitHub release / Hugging Face pages), then run the Windows CI check.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field


@dataclass(frozen=True)
class RemoteFile:
    url: str
    size: int
    sha256: str

    @property
    def name(self) -> str:
        return self.url.rsplit("/", 1)[-1]


@dataclass(frozen=True)
class Engine:
    """llama.cpp's llama-server: runs GGUF models on the GPU (Vulkan) or CPU."""

    version: str
    archive: RemoteFile
    executable: str  # file name inside the archive


@dataclass(frozen=True)
class Model:
    id: str
    name: str  # e.g. "Qwen3-VL 8B"
    label: str  # e.g. "Standard"
    description: str
    weights: RemoteFile
    vision: RemoteFile | None = None  # projector file that lets the model see images
    min_vram_gb: float = 0.0  # below this, the model runs (slowly) on the CPU
    context: int = 8192
    tags: tuple[str, ...] = field(default=())

    @property
    def files(self) -> list[RemoteFile]:
        return [self.weights] + ([self.vision] if self.vision else [])

    @property
    def size(self) -> int:
        return sum(f.size for f in self.files)


_LLAMA = "https://github.com/ggml-org/llama.cpp/releases/download/b11857/"
_HF = "https://huggingface.co/{repo}/resolve/main/{file}"

ENGINES = {
    "win32": Engine(
        version="b11857",
        archive=RemoteFile(_LLAMA + "llama-b11857-bin-win-vulkan-x64.zip", 36_995_764,
                           "6d90c98f2eaa19389f426f5b1daa8721226ed7e4a491d181bc0efa13eda6c453"),
        executable="llama-server.exe",
    ),
    # For developing and testing on Linux (CPU only).
    "linux": Engine(
        version="b11857",
        archive=RemoteFile(_LLAMA + "llama-b11857-bin-ubuntu-x64.tar.gz", 22_438_621,
                           "d2f82dbe8fa95738cccfc9e8b14d1186d85d56cd1d19acdebb4ddf24b0a0453e"),
        executable="llama-server",
    ),
}

# Qwen3-VL Instruct: one model that chats, calls tools and understands screenshots.
MODELS = [
    Model(
        id="qwen3-vl-8b",
        name="Qwen3-VL 8B",
        label="Standard",
        description="Best for graphics cards with 8 GB or more.",
        weights=RemoteFile(_HF.format(repo="Qwen/Qwen3-VL-8B-Instruct-GGUF", file="Qwen3VL-8B-Instruct-Q4_K_M.gguf"),
                           5_027_784_800, "67d1659bfe71b89d50b45a4ad1a9e5b997e5bb16ce5da66a6a6167abd569e9e2"),
        vision=RemoteFile(_HF.format(repo="Qwen/Qwen3-VL-8B-Instruct-GGUF", file="mmproj-Qwen3VL-8B-Instruct-Q8_0.gguf"),
                          752_289_728, "c6ba85508d82f42590e6eb77d5340369ab6fecf107a7561d809523d8aa5f3bfd"),
        min_vram_gb=7.0,
    ),
    Model(
        id="qwen3-vl-4b",
        name="Qwen3-VL 4B",
        label="Small",
        description="For 4–6 GB graphics cards, or PCs without one. Faster, a little less clever.",
        weights=RemoteFile(_HF.format(repo="Qwen/Qwen3-VL-4B-Instruct-GGUF", file="Qwen3VL-4B-Instruct-Q4_K_M.gguf"),
                           2_497_281_664, "66358cb18bb6b3b1b6675aa412c7a88ef01d228f481184d13668e5201c730a0a"),
        vision=RemoteFile(_HF.format(repo="Qwen/Qwen3-VL-4B-Instruct-GGUF", file="mmproj-Qwen3VL-4B-Instruct-Q8_0.gguf"),
                          453_974_304, "30ba2c7dd3127a4561b6cba9d13d0f711c91bdb38742e2f56d73c8cb596bd06d"),
        min_vram_gb=3.5,
    ),
]

# Tiny text-only model for the end-to-end test in CI. Not offered to users.
TEST_MODEL = Model(
    id="test-qwen3-0.6b",
    name="Qwen3 0.6B",
    label="Test",
    description="Only for automated tests.",
    weights=RemoteFile(_HF.format(repo="Qwen/Qwen3-0.6B-GGUF", file="Qwen3-0.6B-Q8_0.gguf"),
                       639_446_688, "9465e63a22add5354d9bb4b99e90117043c7124007664907259bd16d043bb031"),
    context=4096,
    tags=("test",),
)

DEFAULT_MODEL = "qwen3-vl-8b"


def engine(platform: str = sys.platform) -> Engine | None:
    return ENGINES.get("win32" if platform == "win32" else "linux" if platform.startswith("linux") else "")


def model(model_id: str) -> Model | None:
    return next((m for m in [*MODELS, TEST_MODEL] if m.id == model_id), None)


def recommend(vram_gb: float | None, ram_gb: float | None = None) -> Model:
    """The best model for this PC: by graphics memory, or by RAM when the graphics card is unknown."""
    if vram_gb is None:
        big = ram_gb is None or ram_gb >= 15
        return MODELS[0] if big else MODELS[-1]
    for m in MODELS:  # biggest first
        if vram_gb >= m.min_vram_gb:
            return m
    return MODELS[-1]
