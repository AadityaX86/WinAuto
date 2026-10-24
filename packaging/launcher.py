"""Entry point for the packaged WinAuto.exe."""

import runpy

runpy.run_module("winauto", run_name="__main__", alter_sys=True)
