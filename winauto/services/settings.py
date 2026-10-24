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

    def __init__(self, ai_setup: Any = None):
        self.ai_setup = ai_setup  # services.ai_setup.AISetup, when the app has one

    # ----- built-in AI -----

    def builtin_models(self) -> list[tuple[str, str]]:
        """(model id, label) for each built-in model, with size and whether it's downloaded."""
        if self.ai_setup is not None:
            return [(c.model.id, c.label) for c in self.ai_setup.choices()]
        from winauto.adapters.local_ai import catalog
        from winauto.adapters.local_ai.manager import gb

        return [(m.id, f"{m.name} · {gb(m.size)}") for m in catalog.MODELS]

    def builtin_default(self) -> str:
        if self.ai_setup is not None:
            return self.ai_setup.recommended().id
        from winauto.adapters.local_ai import catalog

        return catalog.DEFAULT_MODEL

    def hardware(self) -> str:
        return self.ai_setup.hardware() if self.ai_setup is not None else ""

    @property
    def data_dir(self) -> Path:
        return data_dir()

    # ----- AI model -----

    def list_models(self, llm: Any) -> list[str]:
        """Models installed in Ollama. Raises LLMError if it can't be reached."""
        return OllamaClient(base_url=llm.base_url).list_models()

    def check_model(self, llm: Any) -> tuple[bool, str]:
        """Can we reach the server, and is the model there? (ok, message for the user)."""
        if llm.backend == "builtin":
            if self.ai_setup is None:
                return False, "The built-in AI is set up when WinAuto starts."
            ai = self.ai_setup.ai
            if llm.builtin_model and llm.builtin_model != ai.model.id:
                return True, "Save to download and use this model."
            status = ai.status()
            return ai.installed(), status.message
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
