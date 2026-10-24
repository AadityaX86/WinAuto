"""User settings, stored as JSON in the data folder."""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field, fields, is_dataclass
from pathlib import Path
from typing import Any

from winauto.paths import config_path

log = logging.getLogger(__name__)


@dataclass
class LLMConfig:
    # "ollama" uses Ollama's own API. "openai" works with any OpenAI-compatible
    # local server (LM Studio, llama.cpp server, Jan, vLLM...).
    backend: str = "ollama"
    base_url: str = "http://localhost:11434"
    model: str = "qwen3:8b"
    # Ollama's default context window is small; tool definitions need room.
    num_ctx: int = 8192
    temperature: float = 0.2
    keep_alive: str = "30m"
    timeout: float = 180.0
    api_key: str = ""  # only for openai-compatible servers that want one
    # Used for questions about the screen or images. Must be a vision model.
    vision_model: str = "qwen2.5vl:7b"
    stream: bool = True  # show answers as they're written


@dataclass
class EmailConfig:
    address: str = ""  # your Gmail address; the app password lives in Windows Credential Manager
    display_name: str = ""
    signature: str = ""


@dataclass
class MessagingConfig:
    # Added to phone numbers saved without one, e.g. "977" for Nepal, "91" for India.
    default_country_code: str = ""
    # Press Enter for you after the message is typed in. Off = you press it.
    whatsapp_auto_send: bool = True
    discord_auto_send: bool = True


@dataclass
class Config:
    llm: LLMConfig = field(default_factory=LLMConfig)
    email: EmailConfig = field(default_factory=EmailConfig)
    messaging: MessagingConfig = field(default_factory=MessagingConfig)
    hotkey: str = "ctrl+alt+space"
    text_hotkey: str = "ctrl+alt+t"  # writing tools for the selected text
    start_with_windows: bool = False
    search_engine: str = "google"  # google, bing, duckduckgo
    user_name: str = ""
    history_turns: int = 6
    max_steps: int = 6
    use_quick_commands: bool = True
    weather_location: str = ""
    music_service: str = "youtube"  # youtube or spotify
    # Private iCal links (Google Calendar: Settings → your calendar → "Secret address in iCal format").
    calendar_urls: list[str] = field(default_factory=list)
    morning_briefing: bool = True  # show the daily briefing the first time you open WinAuto each morning
    speak_replies: bool = False  # read answers aloud
    focus_block_apps: list[str] = field(default_factory=lambda: ["discord", "steam", "whatsapp", "telegram"])
    extra_sites: dict[str, str] = field(default_factory=dict)
    app_aliases: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _merge(cls: type, data: Any) -> Any:
    """Build dataclass `cls` from `data`, ignoring unknown keys and keeping defaults."""
    default = cls()
    if not isinstance(data, dict):
        return default
    kwargs = {}
    for f in fields(cls):
        if f.name not in data:
            continue
        current = getattr(default, f.name)
        value = data[f.name]
        if is_dataclass(current):
            kwargs[f.name] = _merge(type(current), value)
        elif isinstance(current, bool):
            kwargs[f.name] = bool(value)
        elif isinstance(current, (int, float)) and not isinstance(value, (int, float)):
            try:
                kwargs[f.name] = type(current)(value)
            except (TypeError, ValueError):
                pass
        elif isinstance(current, dict) and not isinstance(value, dict):
            pass
        elif isinstance(current, list) and not isinstance(value, list):
            pass
        else:
            kwargs[f.name] = value
    return cls(**{**{f.name: getattr(default, f.name) for f in fields(cls)}, **kwargs})


def load_config(path: Path | None = None) -> Config:
    path = path or config_path()
    if not path.exists():
        cfg = Config()
        save_config(cfg, path)
        return cfg
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        log.warning("Could not read %s (%s); using defaults", path, exc)
        return Config()
    return _merge(Config, data)


def save_config(cfg: Config, path: Path | None = None) -> None:
    path = path or config_path()
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(cfg.to_dict(), indent=2), encoding="utf-8")
    tmp.replace(path)
