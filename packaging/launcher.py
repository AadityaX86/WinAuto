"""Entry point for the packaged WinAuto.exe.

Imports are written out (not runpy) so PyInstaller can see and bundle them.
"""

import os
import sys
import tempfile
import traceback


def _run() -> int:
    if "--selftest" in sys.argv:
        from winauto.selftest import main
    elif "--cli" in sys.argv:
        from winauto.cli import main
    else:
        from winauto.app import main
    return main() or 0


if __name__ == "__main__":
    try:
        code = _run()
    except SystemExit:
        raise
    except BaseException:
        # A windowed exe would otherwise show a blocking error box (and hang CI).
        path = os.path.join(tempfile.gettempdir(), "winauto-crash.txt")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(traceback.format_exc())
        try:
            import logging

            from winauto.log import setup_logging

            setup_logging()
            logging.getLogger("winauto").critical("Crashed on start:\n%s", traceback.format_exc())
        except Exception:
            pass
        if "--selftest" not in sys.argv and sys.platform == "win32":
            import ctypes

            ctypes.windll.user32.MessageBoxW(
                None, f"WinAuto couldn't start. Details were saved to:\n{path}", "WinAuto", 0x10
            )
        code = 1
    sys.exit(code)
