"""Verification capture progress remains meaningful across language changes."""
import time

from PySide6.QtCore import QSettings

from moyle_steg.i18n import tr
from moyle_steg.window import MainWindow


def test_capture_progress_translates_and_keeps_measured_stage_counts(qtbot, tmp_path):
    window = MainWindow(QSettings(str(tmp_path / 'verify-copy.ini'), QSettings.Format.IniFormat))
    qtbot.addWidget(window)
    window.show_page('verify')
    window.show()
    window.busy = True
    window._started_at = time.monotonic()
    try:
        window._progress_changed('capture', 256, 1024)
        for language in ('zh_CN', 'en_US'):
            window.set_language(language)
            assert tr('stage_capture', language) in window.status_label.text()
            assert '25%' in window.status_label.text()
            assert window.progress.value() == 250

        window._progress_changed('capture', None, None)
        for language in ('zh_CN', 'en_US'):
            window.set_language(language)
            assert tr('stage_capture', language) in window.status_label.text()
            assert '%' not in window.status_label.text()
            assert window.progress.minimum() == window.progress.maximum() == 0
    finally:
        window.busy = False
