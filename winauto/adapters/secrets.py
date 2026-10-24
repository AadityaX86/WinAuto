"""Passwords live in Windows Credential Manager (via keyring), never in config.json."""

from __future__ import annotations

import logging

log = logging.getLogger(__name__)
SERVICE = "WinAuto"


def get_secret(name: str) -> str | None:
    try:
        import keyring

        return keyring.get_password(SERVICE, name)
    except Exception:
        log.warning("Couldn't read secret %s", name)
        log.debug("details", exc_info=True)
        return None


def set_secret(name: str, value: str) -> bool:
    try:
        import keyring

        if value:
            keyring.set_password(SERVICE, name, value)
        else:
            try:
                keyring.delete_password(SERVICE, name)
            except Exception:
                pass
        return True
    except Exception:
        log.warning("Couldn't save secret %s", name)
        log.debug("details", exc_info=True)
        return False
