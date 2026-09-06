"""Placeholder glyphs must retain the theme's contrast after Qt style painting."""
from collections import Counter

import pytest
from PySide6.QtCore import QPoint, QRect, QSettings
from PySide6.QtGui import QColor


@pytest.mark.parametrize('theme_id', ['midnight', 'blossom', 'terminal'])
@pytest.mark.parametrize('language', ['zh_CN', 'en_US'])
@pytest.mark.parametrize('enabled', [True, False], ids=['enabled', 'disabled'])
def test_rendered_file_and_password_placeholders_keep_theme_color(
        qtbot, tmp_path, theme_id, language, enabled):
    from moyle_steg.window import MainWindow
    window = MainWindow(QSettings(str(tmp_path / 'placeholder.ini'), QSettings.Format.IniFormat))
    qtbot.addWidget(window)
    window.set_theme(theme_id)
    window.set_language(language)
    window.set_reduce_motion(True)
    window.show()
    window.nav_buttons['hide'].setFocus()
    expected = QColor(window.theme.muted if enabled else window.theme.disabled_text)
    background = QColor(window.theme.input_bg if enabled else window.theme.disabled_bg)
    for edit in (window.forms['hide']['cover'].edit, window.forms['hide']['password']):
        assert not edit.text() and edit.placeholderText()
        edit.setEnabled(enabled)
        previous_rect = None

        def fully_visible():
            nonlocal previous_rect
            # A small logical work area stacks the form. Scroll to each field
            # as a user would, then let that reflow settle before pixel sampling.
            # Qt may track a line edit's cursor rectangle rather than the full
            # painted field. Include enough margin for its padding and border.
            window.scroll.ensureWidgetVisible(edit, 12, edit.height() + 12)
            position = edit.mapTo(window.scroll.viewport(), QPoint())
            rect = QRect(position, edit.size())
            stable = rect == previous_rect
            previous_rect = QRect(rect)
            return stable and window.scroll.viewport().rect().contains(rect)

        qtbot.waitUntil(fully_visible, timeout=3000)
        # Inspect the composed window, not its palette: Qt can silently derive
        # a half-opacity placeholder even when PlaceholderText is explicit.
        qtbot.wait(20)
        image = window.grab().toImage()
        ratio = image.devicePixelRatio()
        origin = edit.mapTo(window, QPoint())
        interior = image.copy(round((origin.x() + 12) * ratio),
                              round((origin.y() + 8) * ratio),
                              round((edit.width() - 32) * ratio),
                              round((edit.height() - 16) * ratio))
        glyphs = 0
        colors = Counter()
        for y in range(interior.height()):
            for x in range(interior.width()):
                pixel = interior.pixelColor(x, y)
                if max(abs(pixel.red() - expected.red()), abs(pixel.green() - expected.green()),
                       abs(pixel.blue() - expected.blue())) <= 16:
                    glyphs += 1
                if pixel != background:
                    colors[pixel.name()] += 1
        assert glyphs > 25, (theme_id, language, enabled, edit.objectName(),
                             expected.name(), glyphs, colors.most_common(5))
