"""Register installed Windows fonts when Qt's offscreen backend has none."""

import os
import sys
from pathlib import Path

from PySide6.QtGui import QFont, QFontDatabase


_registered = False


def configure_fonts(app):
    global _registered
    if not _registered and sys.platform == "win32" and not QFontDatabase.families():
        font_directory = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts"
        for name in ("segoeui.ttf", "seguisb.ttf", "msyh.ttc", "msyhbd.ttc"):
            font_file = font_directory / name
            if font_file.is_file():
                QFontDatabase.addApplicationFont(str(font_file))
    _registered = True
    app.setFont(QFont("Microsoft YaHei UI", 10))
