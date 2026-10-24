"""Where Windows really keeps Documents, Downloads, etc. (they may be moved to OneDrive)."""

from __future__ import annotations

import ctypes
import os
import uuid
from pathlib import Path

from winauto.adapters.winos import IS_WINDOWS

KNOWN_FOLDER_IDS = {
    "desktop": "B4BFCC3A-DB2C-424C-B029-7FE99A87C641",
    "documents": "FDD39AD0-238F-46AF-ADB4-6C85480369C7",
    "downloads": "374DE290-123F-4565-9164-39C4925E467B",
    "pictures": "33E28130-4E1E-4676-835A-98395C3BC3BB",
    "music": "4BD8D571-6D19-48D3-BE97-422220080E43",
    "videos": "18989B1D-99B5-455B-841C-AB7C74E4DDFC",
    "screenshots": "B7BEDE81-DF94-4682-A7D8-57A52620B86F",
    "recent": "AE50C081-EBD2-438A-8655-8A092E34987A",
}


def _known_folder(guid: str) -> Path | None:
    from ctypes import wintypes

    class GUID(ctypes.Structure):
        _fields_ = [("Data1", wintypes.DWORD), ("Data2", wintypes.WORD), ("Data3", wintypes.WORD),
                    ("Data4", ctypes.c_ubyte * 8)]

    u = uuid.UUID(guid)
    g = GUID(u.fields[0], u.fields[1], u.fields[2], (ctypes.c_ubyte * 8).from_buffer_copy(u.bytes[8:]))
    path_ptr = ctypes.c_wchar_p()
    shell32 = ctypes.windll.shell32
    if shell32.SHGetKnownFolderPath(ctypes.byref(g), 0, None, ctypes.byref(path_ptr)) != 0:
        return None
    try:
        return Path(path_ptr.value)
    finally:
        ctypes.windll.ole32.CoTaskMemFree(path_ptr)


def folder(name: str) -> Path | None:
    """'downloads' -> C:\\Users\\you\\Downloads (or wherever it was moved)."""
    key = name.lower()
    if key in ("home", "user", "profile"):
        return Path.home()
    if key == "temp":
        return Path(os.environ.get("TEMP", "/tmp"))
    if key == "onedrive":
        od = os.environ.get("OneDrive")
        return Path(od) if od else None
    if key == "appdata":
        return Path(os.environ.get("APPDATA", Path.home()))
    if IS_WINDOWS and key in KNOWN_FOLDER_IDS:
        try:
            found = _known_folder(KNOWN_FOLDER_IDS[key])
            if found:
                return found
        except OSError:
            pass
    if key == "recent":
        return Path(os.environ.get("APPDATA", Path.home())) / "Microsoft" / "Windows" / "Recent"
    if key == "screenshots":
        return (folder("pictures") or Path.home() / "Pictures") / "Screenshots"
    if key in KNOWN_FOLDER_IDS:
        return Path.home() / key.capitalize()
    return None
