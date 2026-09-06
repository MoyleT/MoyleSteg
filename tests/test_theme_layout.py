"""The redesigned workspace keeps its primary actions reachable in both languages."""
import pytest
from PySide6.QtCore import QSettings, QRect, QPoint


@pytest.mark.parametrize('language', ['zh_CN', 'en_US'])
def test_appearance_control_and_compact_hide_workspace(qtbot, tmp_path, language):
    from moyle_steg.window import MainWindow
    window = MainWindow(QSettings(str(tmp_path / 'layout.ini'), QSettings.Format.IniFormat))
    qtbot.addWidget(window)
    window.resize(1220, 820)
    window.set_language(language)
    window.show()
    assert hasattr(window, 'theme_combo'), 'Appearance must be switchable from the workspace'
    qtbot.wait(100)
    run = window.forms['hide']['run']
    viewport = window.scroll.viewport()
    rect = QRect(run.mapTo(viewport, QPoint()), run.size())
    assert viewport.rect().contains(rect), 'Primary hide action must be visible in the initial default-size view'
    assert window.scroll.verticalScrollBar().maximum() == 0, 'Hidden pages must not cause empty scrolling'
    for control in (window.theme_combo, window.language_combo):
        assert window.rect().contains(QRect(control.mapTo(window, QPoint()), control.size()))


@pytest.mark.parametrize('language', ['zh_CN', 'en_US'])
def test_all_task_pages_remain_reachable_at_minimum_size_and_guide_has_one_scroller(qtbot, tmp_path, language):
    from moyle_steg.window import MainWindow
    window = MainWindow(QSettings(str(tmp_path / 'compact.ini'), QSettings.Format.IniFormat))
    qtbot.addWidget(window)
    window.resize(1040, 720)
    window.set_language(language)
    window.set_reduce_motion(True)
    window.show()
    for page in ('hide', 'extract', 'crypt', 'verify', 'keygen'):
        window.show_page(page)
        qtbot.wait(50)
        run = window.forms[page]['run']
        window.scroll.ensureWidgetVisible(run)
        qtbot.wait(20)
        assert window.scroll.viewport().rect().contains(QRect(run.mapTo(window.scroll.viewport(), QPoint()), run.size()))
        assert window.width() == 1040, 'Localization must not force the window wider'
    window.show_page('guide')
    qtbot.wait(80)
    assert window.scroll.verticalScrollBar().maximum() == 0
    assert window.guide_browser.verticalScrollBar().maximum() > 0
