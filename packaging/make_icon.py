"""Writes packaging/winauto.ico from the icon the app draws for itself."""

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from winauto.ui.theme import app_icon  # noqa: E402

app = QApplication(sys.argv[:1])
out = Path(__file__).with_name("winauto.ico")
if not app_icon().pixmap(256, 256).save(str(out), "ICO"):
    sys.exit("Couldn't write the icon")
print(out)
