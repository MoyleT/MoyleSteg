"""The Windows offscreen platform must render Latin and Chinese glyphs."""

import sys
import pytest


@pytest.mark.skipif(sys.platform != "win32", reason="Windows system font registration")
def test_system_font_setup_supports_both_ui_languages(qapp):
    from PySide6.QtGui import QFont, QRawFont
    from moyle_steg.fonts import configure_fonts

    configure_fonts(qapp)
    assert QRawFont.fromFont(QFont("Segoe UI")).supportsCharacter("M")
    assert QRawFont.fromFont(QFont("Microsoft YaHei UI")).supportsCharacter("中")
