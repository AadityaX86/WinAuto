"""Entry point for the packaged WinAuto.exe."""

import os
import runpy
import sys
import tempfile
import traceback

try:
    runpy.run_module("winauto", run_name="__main__", alter_sys=True)
except SystemExit:
    raise
except BaseException:
    # A windowed exe would otherwise show a blocking error box (and hang CI).
    path = os.path.join(tempfile.gettempdir(), "winauto-crash.txt")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(traceback.format_exc())
    try:
        from winauto.log import setup_logging
        import logging

        setup_logging()
        logging.getLogger("winauto").critical("Crashed on start:\n%s", traceback.format_exc())
    except Exception:
        pass
    if "--selftest" not in sys.argv and sys.platform == "win32":
        import ctypes

        ctypes.windll.user32.MessageBoxW(
            None, f"WinAuto couldn't start. Details were saved to:\n{path}", "WinAuto", 0x10
        )
    sys.exit(1)
