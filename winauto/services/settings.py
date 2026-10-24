"""The checks and secrets behind the Settings window."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from winauto import __version__
from winauto.adapters.gmail import SECRET_NAME as GMAIL_SECRET
from winauto.adapters.gmail import GmailBackend
from winauto.adapters.llm import OllamaClient, make_client
from winauto.adapters.secrets import get_secret, set_secret
from winauto.adapters.winos.hotkey import parse_hotkey
from winauto.paths import data_dir


class SettingsService:
    version = __version__

    @property
    def data_dir(self) -> Path:
        return data_dir()

    # ----- AI model -----

    def list_models(self, llm: Any) -> list[str]:
        """Models installed in Ollama. Raises LLMError if it can't be reached."""
        return OllamaClient(base_url=llm.base_url).list_models()

    def check_model(self, llm: Any) -> tuple[bool, str]:
        """Can we reach the server, and is the model there? (ok, message for the user)."""
        return make_client(llm).check()

    # ----- Gmail -----

    def gmail_password_saved(self) -> bool:
        return bool(get_secret(GMAIL_SECRET))

    def save_gmail_password(self, password: str) -> bool:
        return set_secret(GMAIL_SECRET, password.replace(" ", ""))

    def test_gmail(self, address: str, password: str = "") -> str:
        """Sign in to Gmail (with the saved password if none is given). Raises EmailError on failure."""
        from winauto.adapters.gmail import EmailError

        password = password or get_secret(GMAIL_SECRET) or ""
        if not address or not password:
            raise EmailError("Enter your Gmail address and app password first.")
        return GmailBackend(address, password).check()

    # ----- shortcuts -----

    def hotkey_error(self, combo: str) -> str | None:
        """Why a shortcut like 'ctrl+alt+space' can't be used, or None if it's fine."""
        try:
            parse_hotkey(combo)
        except ValueError as exc:
            return str(exc)
        return None
